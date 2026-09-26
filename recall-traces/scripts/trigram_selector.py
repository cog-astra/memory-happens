import re
import unicodedata
from fractions import Fraction

from pydantic import Field

from recall_operations import Operation, Outcome, Value, passage

# Matches a query word to a passage word by shared character trigrams, so inflected forms
# still meet: «оптимизацию» finds «оптимизация», «gardens» finds «garden».
WORD_MATCH = Fraction(2, 3)


class SelectParameters(Value):
    query: str = Field(min_length=1)
    limit: int = Field(default=5, gt=0)


SELECT = Operation(
    name='select',
    purpose='Keep the passages whose words resemble the query words; closest first.',
    parameters=SelectParameters,
    inputs=('passages',),
    requires_text=True,
)


def catalog():
    return [SELECT]


def invoke(operation, parameters, inputs, context):
    if operation not in (SELECT, SELECT.name):
        yield Outcome(status='unsupported', code='unknown_operation',
                      message=f'This plugin supplies only {SELECT.name!r}.')
        return
    query = [trigrams(word) for word in dict.fromkeys(words(parameters['query']))]
    ranked = []
    for index, record in enumerate(inputs['passages']):
        if context.cancelled.is_set():
            yield Outcome(status='cancelled')
            return
        rank = resemblance(query, record.text)
        if rank[0]:
            ranked.append((rank, index, record))
    ranked.sort(key=lambda item: (-item[0][0], -item[0][1], item[1]))
    for _, _, record in ranked[:parameters['limit']]:
        yield passage(record)
    yield Outcome(status='success', code='' if query else 'no_searchable_words')


def resemblance(query, text):
    candidates = [trigrams(word) for word in set(words(text))]
    best = [max((containment(word, other) for other in candidates), default=0) for word in query]
    matched = [score for score in best if score >= WORD_MATCH]
    return len(matched), sum(matched)


def words(text):
    return re.findall(r'\w+', unicodedata.normalize('NFKC', text).casefold())


def trigrams(word):
    padded = f' {word} '
    return {padded[i:i + 3] for i in range(len(padded) - 2)}


def containment(word, other):
    return Fraction(len(word & other), len(word))
