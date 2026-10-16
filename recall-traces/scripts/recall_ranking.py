def relevance(matched, total, when, excerpt=''):
    words = [word.casefold() for word in matched]
    local = max((sum(word in line for word in words)
                 for line in (excerpt or '').casefold().splitlines()), default=0)
    return len(matched), local, total, when
