import argparse
import json


def describe(parser):
    options = []
    for action in parser._actions:
        if action.dest in ('help', 'describe'):
            continue
        option = {
            'name': action.dest,
            'flags': action.option_strings,
            'required': action.required,
            'type': getattr(action.type, '__name__', 'string'),
            'default': action.default,
            'help': action.help,
        }
        if action.nargs is not None:
            option['nargs'] = action.nargs
        if action.choices is not None:
            option['choices'] = list(action.choices)
        if isinstance(action, (argparse._StoreTrueAction, argparse._StoreFalseAction)):
            option['type'] = 'boolean'
        if isinstance(action, argparse._AppendAction):
            option['repeatable'] = True
        options.append(option)
    return {
        'format': 'recall-cli-options-v1',
        'description': parser.description,
        'options': options,
        'exclusive_groups': [
            {'members': [a.dest for a in group._group_actions], 'required': group.required}
            for group in parser._mutually_exclusive_groups
        ],
        'usage_notes': parser.epilog,
        'validation': 'CLI syntax only; operation-specific constraints are checked during invocation.',
    }


class Describe(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        print(json.dumps(describe(parser), ensure_ascii=False, indent=2))
        parser.exit()


def publish_options(parser):
    parser.add_argument('--describe', action=Describe, nargs=0,
                        help='Print settings as JSON without searching or reading sources')
