import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from zero_config_claim_audit.audit import audit, claims, evidence
from zero_config_claim_audit.cli import main

FIXTURES = Path(__file__).parent / 'fixtures'


class ClaimTests(unittest.TestCase):
    pass


PHRASES = ['zero-config', 'zero config', 'no config', 'no configuration',
           'no setup', 'works out of the box', 'no config file',
           'no configuration file', 'configuration-free', 'setup-free',
           'no config needed', 'no configuration needed', 'configuration free',
           'setup free', 'ZERO-CONFIG', 'no-config', 'works-out-of-the-box']
REVERSE = ['requires a config file', 'requires configuration',
           'configuration required', 'config file required',
           'you must configure', 'must be configured']


def claim_case(phrase, expected):
    def test(self):
        self.assertEqual([c['family'] for c in claims(phrase + '.')], expected)
    return test


for i, phrase in enumerate(PHRASES + REVERSE):
    family = 'zero-config' if i < len(PHRASES) else 'requires-config'
    setattr(ClaimTests, 'test_phrase_%02d' % i, claim_case(phrase, [family]))
    setattr(ClaimTests, 'test_negation_%02d' % i, claim_case('Not ' + phrase, []))


class EvidenceTests(unittest.TestCase):
    def check(self, source, count=1, optional=False):
        found = evidence(source, 'app.py')
        self.assertEqual(len(found), count, found)
        if count:
            self.assertTrue(all(e['optional'] == optional for e in found), found)

    def test_parser_read_file(self):
        self.check('import configparser\np = configparser.ConfigParser()\np.read_file(stream)')

    def test_parser_readfp(self):
        self.check('from configparser import ConfigParser as CP\np = CP()\np.readfp(stream)')

    def test_parser_read(self):
        self.check('import configparser\np = configparser.ConfigParser()\np.read("settings.ini")', 0)

    def test_parser_dict(self):
        self.check('import configparser\np = configparser.ConfigParser()\np.read_dict({})', 0)

    def test_unrelated_read_file(self):
        self.check('obj.read_file(stream)', 0)

    def test_dynamic(self):
        self.check('open(filename)', 0)

    def test_dynamic_loader(self):
        self.check('import tomllib\ntomllib.load(stream)', 0)

    def test_toml_alias(self):
        self.check('import tomli as t\nt.load(open("data.bin"))')

    def test_json(self):
        self.check('import json\njson.load(open("settings.json"))', 2)

    def test_yaml(self):
        self.check('import yaml\nyaml.safe_load(open("app.yaml"))', 2)

    def test_yaml_load(self):
        self.check('import yaml\nyaml.load(open("app.yml"))', 2)

    def test_ordinary_json(self):
        self.check('import json\njson.load(open("data.json"))', 0)

    def test_exists(self):
        self.check('import os\nif os.path.exists("settings.ini"):\n open("settings.ini")', optional=True)

    def test_isfile(self):
        self.check('import os\nif os.path.isfile("settings.ini"):\n open("settings.ini")', optional=True)

    def test_path_exists(self):
        self.check('from pathlib import Path\np = Path("settings.ini")\nif p.exists():\n p.read_text()', optional=True)

    def test_path_is_file(self):
        self.check('from pathlib import Path\nif Path("settings.ini").is_file():\n Path("settings.ini").read_bytes()', optional=True)

    def test_wrong_path(self):
        self.check('import os\nif os.path.exists("other.ini"):\n open("settings.ini")')

    def test_negative_guard(self):
        self.check('import os\nif not os.path.exists("settings.ini"):\n open("settings.ini")')

    def test_else_not_guarded(self):
        self.check('import os\nif os.path.exists("settings.ini"):\n pass\nelse:\n open("settings.ini")')

    def test_other_function(self):
        self.check('import os\nif os.path.exists("settings.ini"):\n def f():\n  open("settings.ini")')

    def test_try(self):
        self.check('try:\n open("settings.ini")\nexcept FileNotFoundError:\n pass', optional=True)

    def test_oserror(self):
        self.check('try:\n open("settings.ini")\nexcept (ValueError, OSError):\n pass', optional=True)

    def test_wrong_exception(self):
        self.check('try:\n open("settings.ini")\nexcept ValueError:\n pass')

    def test_try_else(self):
        self.check('try:\n pass\nexcept OSError:\n pass\nelse:\n open("settings.ini")')


for i, path in enumerate(['config', 'settings.json', 'app.conf', 'app.ini', 'app.cfg', 'app.toml', 'app.yaml', 'app.yml', '.toolrc', '~/.config/tool/settings', 'SETTINGS.INI']):
    def test(self, path=path):
        self.check('open(' + repr(path) + ')')
    setattr(EvidenceTests, 'test_path_%02d' % i, test)

for i, expr in enumerate(['Path("app.ini").open()', 'Path("app.ini").read_text()', 'Path("app.ini").read_bytes()', 'io.open("app.ini")', '(Path.home() / ".config" / "app.ini").read_text()', 'Path("~/.config/app.ini").read_text()', 'open(os.path.join("/home", "app.ini"))']):
    def test(self, expr=expr):
        self.check('from pathlib import Path\nimport io\nimport os\n' + expr)
    setattr(EvidenceTests, 'test_open_form_%02d' % i, test)

for i, loader in enumerate(['tomllib.load', 'tomli.load', 'json.load', 'yaml.safe_load', 'yaml.load']):
    def test(self, loader=loader):
        self.check('import ' + loader.split('.')[0] + '\n' + loader + '(open("pyproject.toml", "rb"))', 0)
    setattr(EvidenceTests, 'test_pyproject_%02d' % i, test)


class IntegrationTests(unittest.TestCase):
    def cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            status = main([str(a) for a in args])
        return status, out.getvalue()

    def test_good(self):
        result = audit(FIXTURES / 'good')
        self.assertEqual(result['findings'], [])
        self.assertEqual(len(result['verified_optional_reads']), 1)
        self.assertEqual(len(result['verified_claims']), 1)

    def test_bad_grouping(self):
        result = audit(FIXTURES / 'bad')
        self.assertEqual(len(result['findings']), 1)
        f = result['findings'][0]
        self.assertEqual(f['severity'], 'HIGH')
        self.assertEqual(f['rule'], 'documented-zero-config-claim-false')
        self.assertEqual(len(f['evidence']), 4)

    def test_unused(self):
        f = audit(FIXTURES / 'bad/unused')['findings']
        self.assertEqual([x['rule'] for x in f], ['documented-config-required-unused'])

    def test_testonly(self):
        self.assertEqual(self.cli(FIXTURES / 'testonly')[0], 2)
        status, text = self.cli(FIXTURES / 'testonly', '--fail-on', 'HIGH')
        self.assertEqual(status, 0)
        self.assertIn('MEDIUM', text)

    def test_ignore(self):
        self.assertEqual(self.cli(FIXTURES / 'bad', '--ignore', 'documented-zero-config-claim-false')[0], 0)

    def test_json(self):
        status, text = self.cli(FIXTURES / 'good', '--json')
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(text)['summary']['status'], 'PASS')

    def test_verbose(self):
        self.assertIn('verified-optional', self.cli(FIXTURES / 'good', '--verbose')[1])

    def test_env_never_opened(self):
        original = Path.open
        def guarded(path, *args, **kwargs):
            self.assertNotEqual(path.name, '.env')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'open', guarded):
            for flags in [(), ('--json',), ('--verbose',)]:
                self.assertNotIn('NEVER_READ_ENV_MARKER_7F91', self.cli(FIXTURES / 'bad', *flags)[1])

    def test_fences(self):
        self.assertEqual(claims('```md\nzero config\n```\n~~~\nno setup\n~~~'), [])

    def test_inline(self):
        self.assertEqual(len(claims('Supports `zero-config`.')), 1)

    def test_sentence_negation(self):
        self.assertEqual(len(claims("It isn't zero-config. No setup.")), 1)
        self.assertEqual(claims('It never works out of the box.'), [])

    def temp_audit(self, files):
        with tempfile.TemporaryDirectory() as directory:
            for path, text in files.items():
                dest = Path(directory) / path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(text)
            return audit(directory)

    def test_no_source_both_families(self):
        result = self.temp_audit({'README.md': 'No setup. Requires configuration.'})
        self.assertEqual(len(result['findings']), 2)
        self.assertTrue(all(f['severity'] == 'HIGH' for f in result['findings']))

    def test_no_claims(self):
        self.assertEqual(self.temp_audit({'app.py': 'open("settings.ini")'})['findings'], [])

    def test_reverse_supported(self):
        self.assertEqual(self.temp_audit({'README.md': 'Requires configuration.', 'app.py': 'open("settings.ini")'})['findings'], [])

    def test_reverse_test_only(self):
        result = self.temp_audit({'README.md': 'Requires configuration.', 'tests/app.py': 'open("settings.ini")'})
        self.assertEqual(result['findings'][0]['severity'], 'MEDIUM')

    def test_docs_nested(self):
        result = self.temp_audit({'docs/a/b.md': 'No setup.', 'app.py': 'open("settings.ini")', 'other.md': 'Requires configuration.'})
        self.assertEqual(len(result['findings']), 1)

    def test_symlink_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'README.md').write_text('No setup.')
            (root / 'app.py').write_text('pass')
            (root / 'linked.py').symlink_to(FIXTURES.resolve() / 'bad/app.py')
            (root / 'loop').symlink_to(root, target_is_directory=True)
            self.assertEqual(audit(root)['findings'], [])

    def test_cli_subprocess(self):
        for fixture, expected in [('good', 0), ('bad', 2)]:
            proc = subprocess.run([sys.executable, '-m', 'zero_config_claim_audit', str(FIXTURES / fixture)], capture_output=True, text=True)
            self.assertEqual(proc.returncode, expected, proc.stderr)

    def test_version(self):
        proc = subprocess.run([sys.executable, '-m', 'zero_config_claim_audit', '--version'], capture_output=True, text=True)
        self.assertEqual((proc.returncode, proc.stdout.strip()), (0, '0.1.0'))

    def test_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
            main(['--fail-on', 'LOW'])
        self.assertEqual(exc.exception.code, 1)

    def test_input_error(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['/nonexistent/audit/path']), 1)

    def test_syntax_error(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'app.py').write_text('def invalid(')
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main([directory]), 1)


if __name__ == '__main__':
    unittest.main()
