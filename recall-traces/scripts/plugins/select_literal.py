from pydantic import Field

from recall_operations import Operation, Outcome, Value, passage


class Parameters(Value):
    query: str = Field(min_length=1)
    limit: int = Field(default=5, gt=0)


class Plugin:
    def catalog(self):
        return [Operation('select', 'Select passages containing any literal query term.',
                          Parameters, ('passages',), requires_text=True)]

    def invoke(self, operation, parameters, inputs, context):
        terms = parameters['query'].casefold().split()
        count = 0
        for record in inputs['passages']:
            if context.cancelled.is_set():
                yield Outcome(status='cancelled')
                return
            if any(term in record.text.casefold() for term in terms):
                yield passage(record)
                count += 1
                if count == parameters['limit']:
                    break
        yield Outcome(status='success')
