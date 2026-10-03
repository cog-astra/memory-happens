import re


DESCRIPTION = ('Whitespace-separated words, matched as case-insensitive substrings; any word may match. '
               'No Boolean operators or quoted phrases.')
RECOVERY = ('Use unquoted words separated by spaces, then read findings to check phrases or exclusions. '
            'For literal operator words, use lowercase (and, or, not).')


def syntax_problem(query):
    words = query.split()
    if (len(words) > 1 and any(word in {'AND', 'OR', 'NOT'} for word in words)
            or re.search(r'(?:^|\s)["“]|["”](?=\s|$)', query)):
        return 'Boolean operators and quoted phrases are not supported. No search was performed. ' + DESCRIPTION
    return None
