import re
from typing import Literal

from pydantic import Field, ValidationError

from recall_operations import Outcome, Value

MAX_STEPS = 10


class Step(Value):
    name: str = Field(pattern=r'^[A-Za-z0-9_-]{1,40}$')
    plugin: str = Field(pattern=r'^[A-Za-z0-9_.-]{1,60}$')
    operation: str = Field(pattern=r'^[A-Za-z0-9_.-]{1,60}$')
    parameters: dict = Field(default_factory=dict)
    inputs: dict[str, str | list[dict]] = Field(default_factory=dict)
    on_error: Literal['stop', 'continue'] = 'stop'


def invalid(message, max_steps=MAX_STEPS):
    return [], [], Outcome(status='failed', code='invalid_recipe', message=message,
                           next_steps=[f'Give 1-{max_steps} uniquely named steps; an input port names an earlier step '
                                       'or holds a list of complete records.'])


def run(runner, steps, *, max_steps=MAX_STEPS):
    """Runs a finite recipe: each port takes the records of an earlier step, so they never leave the call.

    Returns the last step's records, a summary of every step that ran, and the recipe's outcome."""
    try:
        steps = [Step.model_validate(step) for step in steps]
    except ValidationError as error:
        first = error.errors()[0]
        return invalid(f'Invalid step field {".".join(map(str, first["loc"]))}: {first["msg"]}', max_steps)
    if not 1 <= len(steps) <= max_steps:
        return invalid(f'A recipe has 1-{max_steps} steps, not {len(steps)}.', max_steps)
    names = set()
    for step in steps:
        unknown = [source for source in step.inputs.values() if isinstance(source, str) and source not in names]
        if step.name in names or unknown:
            return invalid(f'Step {step.name}: ' + (f'input names no earlier step: {unknown[0]}' if unknown
                                                    else 'name is used twice'), max_steps)
        names.add(step.name)

    outputs, summaries, partial = {}, [], None
    for step in steps:
        inputs = {port: outputs[source] if isinstance(source, str) else source for port, source in step.inputs.items()}
        events = list(runner.invoke(step.plugin, step.operation, step.parameters, inputs))
        records = [event['record'] for event in events if event['type'] == 'record']
        outcome = Outcome.model_validate(events[-1]['outcome'])
        summaries.append({'name': step.name, 'operation': f'{step.plugin}.{step.operation}',
                          'parameters': step.parameters, 'records': len(records),
                          'outcome': outcome.model_dump(), 'time': timeline(records)})
        if outcome.status not in ('success', 'partial'):
            if step.on_error == 'stop' or outcome.status == 'cancelled':
                return [], summaries, attributed(step, outcome)
            records = []
            if partial is None:
                partial = Outcome(status='partial', code='incomplete_sources',
                                  message=f'Step {step.name}: {outcome.status}/{outcome.code}. Inspect step outcomes.',
                                  next_steps=outcome.next_steps)
        if outcome.status == 'partial' and partial is None:
            partial = attributed(step, outcome)
        outputs[step.name] = records
    return outputs[steps[-1].name], summaries, partial or attributed(steps[-1], outcome)


def attributed(step, outcome):
    if outcome.status == 'success' and not outcome.message:
        return outcome
    return outcome.model_copy(update={'message': f'Step {step.name}: {outcome.message or outcome.code}'})


def timeline(records):
    """Month by month, so that gaps between periods stay visible."""
    months = {}
    for record in records:
        moment = record['context'].get('event_time')
        day = moment[:10] if isinstance(moment, str) and re.match(r'\d{4}-\d{2}-\d{2}', moment) else None
        key = day[:7] if day else 'undated'
        count, first, last = months.get(key, (0, day, day))
        months[key] = (count + 1, day and min(first, day), day and max(last, day))
    return [{'month': month, 'count': count, **({'first': first, 'last': last} if first else {})}
            for month, (count, first, last) in sorted(months.items())]
