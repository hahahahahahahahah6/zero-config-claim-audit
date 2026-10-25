# zero-config-claim-audit

Audit documented “zero-config” and “requires configuration” claims against
Python source, offline, without importing or executing audited code. Uses only
the standard library at runtime. Version 0.1.0; Python 3.9 or newer.

```sh
python3 -m pip install .
zero-config-claim-audit ./project
zero-config-claim-audit ./project --json
zero-config-claim-audit ./project --verbose --fail-on HIGH
zero-config-claim-audit --version
```

The default path is `.`. Exit codes: 0 PASS, 2 FAIL, 1 usage/input error.
`--fail-on MEDIUM` (default) fails on HIGH or MEDIUM; `--fail-on HIGH` still
prints MEDIUM findings but exits 0 for those alone. `--ignore RULE,...` removes
named rules. JSON includes `findings`, `verified_claims`,
`verified_optional_reads`, and `summary`. Verbose text lists optional reads.
Verified means supported by these static rules, not a semantic guarantee.

## Claims and evidence

Reads root `README.md` and `docs/**/*.md`, excluding fenced code; inline code
counts as prose. Case-insensitive, sentence-level zero-config phrases include
zero config, no config, no configuration, no setup, works out of the box,
no config file, no configuration file, configuration-free, setup-free,
no config needed, and no configuration needed. Hyphen/space variants collapse.
Reverse phrases: requires a config file, requires configuration, configuration
required, config file required, you must configure, must be configured.
Sentence negations such as “not”, “isn't”, and “never” suppress claims.

Strong reads include ConfigParser `read_file`/`readfp`, `tomllib.load` and
`tomli.load` of statically identified opened files, and built-in `open`,
`io.open`, or Path `open`/`read_text`/`read_bytes` on config-like paths.
JSON `load` and YAML `load`/`safe_load` count for config-like file objects.
Config-like paths contain config/settings, end in .conf/.ini/.cfg/.toml/.yaml/
.yml, or have a dotfile rc basename, including home-directory joins.
`pyproject.toml` is excluded as packaging metadata. ConfigParser `read()`
is deliberately excluded because it silently ignores missing files;
`read_dict()` is in-memory and excluded.

A positive existence check (`os.path.exists`, `os.path.isfile`, Path `exists`
or `is_file`) enclosing the read on the same statically resolved path, or an
enclosing `try` with `except FileNotFoundError`/`OSError`, makes a read optional.
Optional reads appear as verified-optional and never falsify a claim.

## Rules

| Rule | Severity | Trigger |
| --- | --- | --- |
| documented-zero-config-claim-false | HIGH | Claim plus unguarded production read |
| documented-zero-config-claim-false-test-only | MEDIUM | Claim plus unguarded reads only in tests/fixtures |
| documented-config-required-unused | MEDIUM | Requirement claim without production strong evidence |

One finding per claim family groups all its evidence. No claims passes.
With no Python source, each claimed family gets one HIGH finding.
Production excludes tests/ and fixtures/ trees, test_*.py and *_test.py.
Symlinks are skipped. `.env` contents are never opened or used as evidence.

## Limitations

Static pattern matching is not semantics. Guard detection is syntactic,
same-function, and based on matching statically resolved path literals;
negative guards, indirect control flow, arbitrary wrappers and complex aliases
may be missed. Dynamic paths with no literal are unknown and skipped.
Non-Python source, environment variables alone and a `--config` flag alone are
out of scope. No reverse HIGH rule exists for undocumented config reads.
Malformed Python and unreadable input produce input errors.

## Differentiation

| Tool | Focus compared with this tool |
| --- | --- |
| config-claim-audit | Default VALUES, rather than whether config is required at all |
| env-drift | Environment PRESENCE, rather than config files |
| auth-claim-audit | CREDENTIAL requirements, rather than general config |
| dotenv-linter | .env syntax, rather than documentation versus code |
| readme-claim-audit | Install/flag/link/version claims, rather than config requirements |

## Development

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m build
# Offline fallback if isolated dependencies are unavailable:
python3 -m build --no-isolation
```

The source distribution includes the fixture corpus and tests. The marker-only
fixture `.env` contains no credentials and tests enforce that it is never read.
MIT licensed.
