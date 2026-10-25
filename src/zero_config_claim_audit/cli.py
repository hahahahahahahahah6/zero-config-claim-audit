"""Command-line interface."""
import argparse
import json
import sys
from . import __version__
from .audit import audit


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(1, 'error: ' + message + '\n')


def main(argv=None):
    parser = Parser(description='Audit documented config requirements offline.')
    parser.add_argument('path', nargs='?', default='.')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--fail-on', choices=('HIGH', 'MEDIUM'), default='MEDIUM')
    parser.add_argument('--ignore', default='', metavar='RULE,...')
    parser.add_argument('--version', action='version', version=__version__)
    args = parser.parse_args(argv)
    try:
        result = audit(args.path)
    except (OSError, ValueError, SyntaxError, UnicodeError) as exc:
        print('error: ' + str(exc), file=sys.stderr)
        return 1
    ignored = set(args.ignore.split(','))
    result['findings'] = [f for f in result['findings'] if f['rule'] not in ignored]
    result['summary']['findings'] = len(result['findings'])
    failed = any(f['severity'] == 'HIGH' or args.fail_on == 'MEDIUM' for f in result['findings'])
    result['summary']['status'] = 'FAIL' if failed else 'PASS'
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(result['summary']['status'])
        for finding in result['findings']:
            print(finding['severity'] + ' ' + finding['rule'])
            for item in finding['evidence']:
                print('  {path}:{line}: {operation} ({config_path})'.format(**item))
        if args.verbose:
            for item in result['verified_optional_reads']:
                print('verified-optional {path}:{line}: {operation}'.format(**item))
            for item in result['verified_claims']:
                print('verified-claim {path}:{line}: {family}'.format(**item))
    return 2 if failed else 0
