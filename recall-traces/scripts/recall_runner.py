from copy import deepcopy
from threading import Event
from uuid import uuid4

from pydantic import ValidationError

from recall_operations import Context, Lineage, Outcome, Passage, Record


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
                values = descriptor.parameters.model_validate(parameters if parameters is not None else {}).model_dump()
                supplied = inputs if inputs is not None else {}
                if not isinstance(supplied, dict) or set(supplied) != set(descriptor.inputs):
                    raise ValueError('Input ports do not match the operation.')
                batches = {}
                for name, batch in supplied.items():
                    if not isinstance(batch, list):
                        raise ValueError('Input ports require finite record lists.')
                    batches[name] = [Record.model_validate(item.model_dump() if isinstance(item, Record) else item)
                                     for item in batch]
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
                                terminal = event
                                continue
                            if not isinstance(event, Passage):
                                terminal = Outcome(status='failed', code='invalid_output')
                                break
                            context.require(*dependencies)
                            count += 1
                            record = Record(
                                **Passage.model_validate({key: getattr(event, key) for key in Passage.model_fields}).model_dump(),
                                id=f'{invocation}:{count}',
                                lineage=Lineage(invocation=invocation, inputs=input_ids),
                                access=sorted(context.resources),
                            )
                            trace['outputs'].append(record.id)
                            yield {'type': 'record', 'record': record.model_dump()}
                        if terminal is None:
                            terminal = Outcome(status='partial', code='missing_outcome',
                                               next_steps=['Retry the operation or inspect the plugin.'])
        except (ValidationError, ValueError, TypeError):
            terminal = Outcome(status='failed', code='invalid_call_or_output',
                               next_steps=['Inspect catalog parameter and input schemas.'])
        except PermissionError:
            terminal = Outcome(status='failed', code='access_denied')
        except FileNotFoundError:
            terminal = Outcome(status='unavailable', code='dependency_missing',
                               next_steps=['Check the configured source and its dependencies.'])
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
