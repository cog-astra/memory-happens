TOOL_PREFIX = '[tool:'
INTENT_FIELDS = ('description', 'file_path', 'notebook_path')


def tool_intent(item):
    fields = item.get('input') or {}
    parts = [str(fields[key]) for key in INTENT_FIELDS if isinstance(fields.get(key), str) and fields[key].strip()]
    return f"{TOOL_PREFIX}{item.get('name')}] " + ' — '.join(parts) if parts else None


def message_blocks(record, line_number):
    if record.get('type') not in ('user', 'assistant') or record.get('isMeta'):
        return
    message = record.get('message') or {}
    role = message.get('role')
    if role not in ('user', 'assistant'):
        return
    content = message.get('content')
    items = [{'type': 'text', 'text': content}] if isinstance(content, str) else content or []
    for block, item in enumerate(items):
        if item.get('type') == 'text':
            text = item.get('text')
        elif item.get('type') == 'tool_use' and role == 'assistant':
            text = tool_intent(item)
        else:
            continue
        if isinstance(text, str) and text.strip():
            yield {
                'line': line_number, 'block': block,
                'recorded_at': record.get('timestamp'),
                'role': role, 'text': text,
            }
