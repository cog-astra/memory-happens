import re


MESSAGE = re.compile(r'^## (\d{4}-\d{2}-\d{2}T[\d:.]+Z) \[(user|assistant)\] L\d+:B\d+$')


def escape_message_text(text):
    return ''.join(('\\' if MESSAGE.fullmatch(line.rstrip('\r\n')) else '') + line
                   for line in text.splitlines(keepends=True))
