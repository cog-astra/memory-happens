import os
import re


def slug(path):
    return re.sub(r'[^A-Za-z0-9]', '-', os.path.abspath(str(path))).casefold()
