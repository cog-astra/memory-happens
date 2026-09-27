from datetime import datetime, timezone

from pydantic import Field

from recall_operations import Operation, Outcome, Value, passage


class Parameters(Value):
    order: str = Field(default='recent', pattern='^(recent|relevance)$')
    limit: int | None = Field(default=None, ge=1)
    per_source: bool = False


def moment(record):
    raw = record.context.get('event_time') or record.context.get('modified_at')
    try:
        value = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        return value.replace(tzinfo=timezone.utc).timestamp() if value.tzinfo is None else value.timestamp()
    except (AttributeError, ValueError, TypeError):
        return float('-inf')


class Plugin:
    def __init__(self, ports):
        self.ports = tuple(ports)

    def catalog(self):
        return [Operation('collect', 'Combine connected source results; sort by time or word matches.',
                          Parameters, inputs=self.ports)]

    def invoke(self, operation, parameters, inputs, context):
        records = [record for batch in inputs.values() for record in batch]
        key = moment if parameters['order'] == 'recent' else lambda record: (
            len(record.context.get('matched', [])), record.context.get('total', 0), moment(record))
        records.sort(key=key, reverse=True)
        counts, emitted = {}, 0
        for record in records:
            if context.cancelled.is_set():
                yield Outcome(status='cancelled', code='cancelled_during_collection')
                return
            source = record.evidence[0].source if record.evidence else ''
            group = source if parameters['per_source'] else ''
            if parameters['limit'] is not None and counts.get(group, 0) >= parameters['limit']:
                continue
            counts[group] = counts.get(group, 0) + 1
            emitted += 1
            yield passage(record)
        yield Outcome(status='success', message=f'{emitted} of {len(records)} input records.',
                      next_steps=[] if records else ['Try different words, a wider period or another connected source.'])
