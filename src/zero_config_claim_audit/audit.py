"""Syntactic, non-executing Markdown and AST analysis."""
import ast
import re
from pathlib import Path

ZERO = r'zero[ -]config|no[ -](?:configuration|config)(?:[ -](?:file|needed))?|no[ -]setup|works[ -]out[ -]of[ -]the[ -]box|configuration[ -]free|setup[ -]free'
REQUIRED = r'requires a config file|requires configuration|configuration required|config file required|you must configure|must be configured'
RULE_ZERO = 'documented-zero-config-claim-false'
RULE_TEST = RULE_ZERO + '-test-only'
RULE_REQUIRED = 'documented-config-required-unused'


def claims(text, path='README.md'):
    lines = []
    fence = None
    for line in text.splitlines():
        m = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
        if m:
            mark = m.group(1)
            if fence is None:
                fence = mark
            elif mark[0] == fence[0] and len(mark) >= len(fence):
                fence = None
            lines.append('')
        else:
            lines.append('' if fence else line)
    out = []
    for match in re.finditer(r'[^.!?]+(?:[.!?]|$)', '\n'.join(lines)):
        sentence = match.group().strip()
        if re.search(r"\b(?:not|never|isn't|isn’t|doesn't|doesn’t|don't|don’t|cannot|can't|can’t|no longer)\b", sentence, re.I):
            continue
        for family, pattern in [('zero-config', ZERO), ('requires-config', REQUIRED)]:
            if re.search(r'\b(?:' + pattern + r')\b', sentence, re.I):
                out.append(dict(family=family, path=path, line='\n'.join(lines)[:match.start()].count('\n') + 1, text=sentence))
    return out


def config_like(value):
    value = value.lower().replace('\\', '/')
    base = value.rsplit('/', 1)[-1]
    return base != 'pyproject.toml' and (any(x in value for x in ('config', 'settings')) or value.endswith(('.conf', '.ini', '.cfg', '.toml', '.yaml', '.yml')) or (base.startswith('.') and base.endswith('rc')))


def dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return dotted(node.value) + '.' + node.attr
    return ''


def evidence(source, path):
    tree = ast.parse(source, filename=path)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    aliases, bindings = {}, {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                aliases[a.asname or a.name] = a.name
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                aliases[a.asname or a.name] = (node.module or '') + '.' + a.name
    def name(n):
        raw = dotted(n)
        first, dot, rest = raw.partition('.')
        return aliases.get(first, first) + (dot + rest if dot else '')
    def scope(n):
        while n in parents:
            n = parents[n]
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                return n
        return tree
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    bindings[(id(scope(node)), target.id)] = node.value
        elif isinstance(node, ast.withitem) and isinstance(node.optional_vars, ast.Name):
            bindings[(id(scope(node)), node.optional_vars.id)] = node.context_expr
    def resolve(n, seen=None):
        seen = set() if seen is None else seen
        if isinstance(n, ast.Name) and n.id not in seen:
            value = bindings.get((id(scope(n)), n.id))
            if value is not None:
                return resolve(value, seen | {n.id})
        return n
    def literal(n):
        n = resolve(n)
        if n is None:
            return None
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            return n.value
        if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Div, ast.Add)):
            left, right = literal(n.left), literal(n.right)
            if right is not None and (left is not None or config_like(right)):
                return (left or '') + '/' + right
        if isinstance(n, ast.Call):
            label = name(n.func)
            if label in ('pathlib.Path.home', 'Path.home'):
                return '~'
            if label in ('pathlib.Path', 'Path', 'os.path.join'):
                values = [literal(a) for a in n.args]
                if values and all(v is not None for v in values):
                    return '/'.join(values)
        return None
    def opened(n):
        n = resolve(n)
        if isinstance(n, ast.Call):
            label = name(n.func)
            if label in ('open', 'io.open'):
                return literal(n.args[0]) if n.args else next((literal(k.value) for k in n.keywords if k.arg == 'file'), None)
            if isinstance(n.func, ast.Attribute) and n.func.attr in ('open', 'read_text', 'read_bytes'):
                return literal(n.func.value)
        return None
    def guard_paths(n):
        if isinstance(n, ast.BoolOp) and isinstance(n.op, ast.And):
            return sum((guard_paths(v) for v in n.values), [])
        if isinstance(n, ast.Call):
            if name(n.func) in ('os.path.exists', 'os.path.isfile') and n.args:
                return [literal(n.args[0])]
            if isinstance(n.func, ast.Attribute) and n.func.attr in ('exists', 'is_file'):
                return [literal(n.func.value)]
        return []
    def optional(n, value):
        child = n
        while child in parents:
            p = parents[child]
            if isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                break
            if isinstance(p, ast.If) and child in p.body and value is not None and value in guard_paths(p.test):
                return True
            if isinstance(p, ast.Try) and child in p.body:
                for handler in p.handlers:
                    types = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
                    if any(name(t) in ('FileNotFoundError', 'OSError', 'builtins.FileNotFoundError', 'builtins.OSError') for t in types if t):
                        return True
            child = p
        return False
    # Resolve ConfigParser instances rather than treating every read_file method as configparser.
    def parser(n):
        n = resolve(n)
        return isinstance(n, ast.Call) and name(n.func) in ('configparser.ConfigParser', 'configparser.RawConfigParser')
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        label = name(node.func)
        value = opened(node)
        strong = value is not None and config_like(value)
        if isinstance(node.func, ast.Attribute) and node.func.attr in ('read_file', 'readfp') and parser(node.func.value):
            strong = True
            value = opened(node.args[0]) if node.args else None
        if label in ('tomllib.load', 'tomli.load', 'json.load', 'yaml.safe_load', 'yaml.load'):
            value = opened(node.args[0]) if node.args else None
            strong = (label in ('tomllib.load', 'tomli.load') or (value is not None and config_like(value)))
            if value is not None and value.replace('\\', '/').rsplit('/', 1)[-1] == 'pyproject.toml':
                strong = False
            # Unknown file objects are dynamic and do not prove file requirements.
            if value is None:
                strong = False
        if strong:
            out.append(dict(path=path, line=node.lineno, operation=label or node.func.attr, config_path=value, optional=optional(node, value)))
    return sorted(out, key=lambda e: e['line'])


def audit(root):
    root = Path(root)
    if not root.is_dir():
        raise ValueError('audit path must be a directory')
    found, reads, sources = [], [], []
    def walk(directory):
        for p in sorted(directory.iterdir()):
            if p.is_symlink() or p.name in ('.git', '.venv', 'venv', '__pycache__', 'build', 'dist'):
                continue
            if p.is_dir():
                yield from walk(p)
            else:
                yield p
    for p in walk(root):
        rel = p.relative_to(root)
        if rel.as_posix() == 'README.md' or (rel.parts[0] == 'docs' and p.suffix == '.md'):
            found.extend(claims(p.read_text(encoding='utf-8'), rel.as_posix()))
        if p.suffix == '.py':
            sources.append(p)
            items = evidence(p.read_text(encoding='utf-8'), rel.as_posix())
            test = any(x in ('tests', 'fixtures') for x in rel.parts[:-1]) or p.name.startswith('test_') or p.name.endswith('_test.py')
            reads.extend(dict(e, test_only=test) for e in items)
    prod = [e for e in reads if not e['test_only'] and not e['optional']]
    test = [e for e in reads if e['test_only'] and not e['optional']]
    findings, verified = [], []
    for family in ('zero-config', 'requires-config'):
        relevant = [c for c in found if c['family'] == family]
        if not relevant:
            continue
        rule, severity, items = None, 'MEDIUM', []
        if not sources:
            rule = RULE_ZERO if family == 'zero-config' else RULE_REQUIRED
            severity = 'HIGH'
        elif family == 'zero-config' and (prod or test):
            rule, severity, items = (RULE_ZERO, 'HIGH', prod) if prod else (RULE_TEST, 'MEDIUM', test)
        elif family == 'requires-config' and not any(not e['test_only'] for e in reads):
            rule = RULE_REQUIRED
        if rule:
            findings.append(dict(rule=rule, severity=severity, family=family, claims=relevant, evidence=items, message='No Python source found' if not sources else 'Documented claim conflicts with static config-read evidence'))
        else:
            verified.extend(relevant)
    return dict(findings=findings, verified_claims=verified, verified_optional_reads=[e for e in reads if e['optional']], summary=dict(claims=len(found), python_files=len(sources), strong_reads=len(reads), findings=len(findings)))
