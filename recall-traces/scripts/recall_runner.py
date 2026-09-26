from copy import deepcopy
from threading import Event
from uuid import uuid4

from pydantic import ValidationError

from recall_operations import AccessDenied, Context, Lineage, Outcome, Passage, Record


class InvalidCall(Exception):
    pass


def prepare(descriptor, parameters, inputs):
    try:
        values = descriptor.parameters.model_validate(parameters if parameters is not None else {}).model_dump()
        supplied = inputs if inputs is not None else {}
        if not isinstance(supplied, dict) or set(supplied) != set(descriptor.inputs):
            raise InvalidCall('invalid_ports')
        batches = {}
        for name, batch in supplied.items():
            if not isinstance(batch, list):
                raise InvalidCall('finite_batch_required')
            batches[name] = [Record.model_validate(item.model_dump() if isinstance(item, Record) else item)
                             for item in batch]
    except (ValidationError, ValueError, TypeError) as error:
        raise InvalidCall('invalid_call') from error
    ids = [item.id for batch in batches.values() for item in batch]
    if len(ids) != len(set(ids)):
        raise InvalidCall('duplicate_input_ids')
    return values, batches


class Runner:
    def __init__(self, plugins, policy=None, trace=None):
        self.plugins = dict(plugins)
        self.policy = policy or (lambda resources: True)
        self.trace = trace if trace is not None else []

    def catalog(self):
        return [
            {'plugin': alias, 'name': op.name, 'version': op.version,
             'purpose': op.purpose, 'parameters': op.parameters.model_json_schema(),
             'inputs': list(op.inputs), 'requires_text': op.requires_text}
            for alias, plugin in self.plugins.items() for op in plugin.catalog()
        ]

    def invoke(self, plugin, operation, parameters=None, inputs=None, cancelled=None):
        invocation = uuid4().hex
        context = Context(self.policy, cancelled if cancelled is not None else Event())
        trace = {'invocation': invocation, 'plugin': plugin, 'operation': operation,
                 'inputs': [], 'outputs': [], 'outcome': 'cancelled'}
        self.trace.append(trace)
        stream, terminal = None, None
        count = 0
        try:
            implementation = self.plugins.get(plugin)
            matches = [op for op in implementation.catalog() if op.name == operation] if implementation else []
            if len(matches) != 1:
                terminal = Outcome(status='unsupported', code='unknown_operation',
                                   next_steps=['Inspect catalog for available operations.'])
            else:
                descriptor = matches[0]
                trace['version'] = descriptor.version
                values, batches = prepare(descriptor, parameters, inputs)
                records = [item for batch in batches.values() for item in batch]
                if descriptor.requires_text and any(item.text is None for item in records):
                    terminal = Outcome(status='unsupported', code='text_required')
                else:
                    dependencies = sorted({resource for item in records for resource in item.access})
                    context.require(*dependencies)
                    input_ids = [item.id for item in records]
                    trace['inputs'] = input_ids
                    if context.cancelled.is_set():
                        terminal = Outcome(status='cancelled', code='cancelled_before_start')
                    else:
                        stream = iter(implementation.invoke(operation, values, deepcopy(batches), context))
                        for event in stream:
                            if context.cancelled.is_set():
                                terminal = Outcome(status='cancelled', code='cancelled_between_events')
                                break
                            if terminal is not None:
                                terminal = Outcome(status='failed', code='event_after_outcome')
                                break
                            if isinstance(event, Outcome):
                                try:
                                    terminal = Outcome.model_validate({key: getattr(event, key) for key in Outcome.model_fields})
                                    terminal.model_dump(mode='json')
                                except (ValidationError, ValueError, TypeError):
                                    terminal = Outcome(status='failed', code='invalid_output')
                                    break
                                continue
                            if not isinstance(event, Passage):
                                terminal = Outcome(status='failed', code='invalid_output')
                                break
                            try:
                                released = Passage.model_validate({key: getattr(event, key) for key in Passage.model_fields})
                                access = context.access(released)
                                record = Record(**released.model_dump(), id=f'{invocation}:{count + 1}',
                                                lineage=Lineage(invocation=invocation, inputs=input_ids), access=access)
                                encoded = record.model_dump(mode='json')
                            except (ValidationError, ValueError, TypeError):
                                terminal = Outcome(status='failed', code='invalid_output')
                                break
                            if not self.policy(tuple(access)):
                                raise AccessDenied('Output access denied by configured policy.')
                            count += 1
                            trace['outputs'].append(record.id)
                            yield {'type': 'record', 'record': encoded}
                        if terminal is None:
                            terminal = Outcome(status='partial', code='missing_outcome',
                                               next_steps=['Retry the operation or inspect the plugin.'])
        except InvalidCall as error:
            terminal = Outcome(status='failed', code=str(error),
                               next_steps=['Supply distinct record IDs across all ports.' if str(error) == 'duplicate_input_ids'
                                           else 'Inspect catalog parameter and input schemas.'])
        except AccessDenied:
            terminal = Outcome(status='failed', code='access_denied')
        except Exception:
            terminal = Outcome(status='failed', code='operation_failed')
        finally:
            if stream is not None and hasattr(stream, 'close'):
                try:
                    stream.close()
                except Exception:
                    terminal = Outcome(status='failed', code='close_failed')
            trace['outcome'] = terminal.status if terminal is not None else 'cancelled'
            trace['code'] = terminal.code if terminal is not None else 'consumer_closed'
        yield {'type': 'outcome', 'invocation': invocation, 'records': count,
               'outcome': terminal.model_dump()}
