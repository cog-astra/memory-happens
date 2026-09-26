def message_blocks(record, line_number):
    if record.get('type') != 'response_item':
        return
    payload = record.get('payload', {})
    if payload.get('type') != 'message':
        return
    role = payload.get('role')
    if role == 'assistant':
        channel, phase = payload.get('channel'), payload.get('phase')
        if channel not in (None, 'final', 'commentary') or phase not in (None, 'final_answer', 'commentary'):
            return
        if channel is None and phase is None:
            return
    if role not in ('user', 'assistant'):
        return
    for block, item in enumerate(payload.get('content', [])):
        if item.get('type') not in ('input_text', 'output_text'):
            continue
        text = item.get('text')
        if isinstance(text, str):
            yield {
                'line': line_number, 'block': block,
                'recorded_at': record.get('timestamp'),
                'role': role, 'text': text,
            }
