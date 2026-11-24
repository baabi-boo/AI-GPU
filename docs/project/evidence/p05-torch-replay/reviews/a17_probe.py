"""Independent inert-data review probe; never import a producer."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess

import p05_replay_native as r

ROOT = Path(__file__).resolve().parents[1] / "AI-GPU"
REV = "c0b44ce64665fe11895f869eea8c38c9b820d6f7"
historical = {}


def body(path):
    if path not in historical:
        historical[path] = subprocess.check_output(["git", "show", REV + ":" + path], cwd=ROOT)
    return historical[path]


def parsed(path):
    return ast.parse(body(path))


names = set(subprocess.check_output(
    ["git", "ls-tree", "-r", "--name-only", REV, "ci/project"], cwd=ROOT).decode().splitlines())


def imports(entry):
    seen, pending = set(), [entry]
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        for node in parsed(path).body:
            modules = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                       else [node.module] if isinstance(node, ast.ImportFrom) else [])
            for module in modules:
                candidate = "ci/project/" + module.replace(".", "/") + ".py"
                if candidate in names:
                    pending.append(candidate)
    return seen


def expr(node, env):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return env[node.id]
    if isinstance(node, ast.Tuple):
        return tuple(expr(item, env) for item in node.elts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return expr(node.left, env) + expr(node.right, env)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        assert node.func.id in ("tuple", "sorted") and len(node.args) == 1 and not node.keywords
        value = expr(node.args[0], env)
        return tuple(value) if node.func.id == "tuple" else sorted(value)
    if isinstance(node, ast.GeneratorExp):
        gen, = node.generators
        assert isinstance(gen.target, ast.Name) and not gen.ifs and not gen.is_async
        return [expr(node.elt, dict(env, **{gen.target.id: value})) for value in expr(gen.iter, env)]
    raise AssertionError(ast.dump(node))


def constants(path, wanted):
    env = {}
    for node in parsed(path).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in wanted | {"APP"}:
                    env[target.id] = expr(node.value, env)
    return env


p02 = constants("ci/project/p02_matrix.py", {"TOOLING", "CORPUS"})
p03 = constants("ci/project/p03_execute.py", {"SOURCE_FILES"})
p04 = constants("ci/project/p04_execute.py", {"SOURCE_FILES"})
p05 = constants("ci/project/p05_execute.py", {"SOURCE_FILES"})
bundle = constants("python/vortex_ai/_bundle.py", {"SOURCE_PATHS"})
nh = imports("ci/project/p04_execute.py")
ph = imports("ci/project/p05_execute.py") | {"python/vortex_ai/_bundle.py"}
assert nh == set(r.NATIVE_HELPERS)
assert ph == set(r.PYTHON_HELPERS)
updates = [node for node in ast.walk(parsed("ci/project/p04_execute.py"))
           if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
           and isinstance(node.func.value, ast.Name) and node.func.value.id == "retained"
           and node.func.attr == "update"]
runtime = ast.literal_eval(updates[0].args[0].generators[0].iter)
assert len(runtime) == 9 and all(body(path) for path in runtime)
native = nh | set(p02["TOOLING"] + p02["CORPUS"] + p03["SOURCE_FILES"]
                  + p04["SOURCE_FILES"] + runtime + ("profiles/p02-tfr.json",))
python = ph | set(p05["SOURCE_FILES"] + bundle["SOURCE_PATHS"])
assert native == set(r.NATIVE_RETAINED_SOURCES) and len(native) == 57
assert python == set(r.PYTHON_RETAINED_SOURCES) and len(python) == 49

# Reverse only the retention constants/selection and chronology additions.
# Matching a13's complete-file hash proves unrelated numerical code is intact.
source = (ROOT / "ci/project/p05_replay_native.py").read_text()
old = source[:source.index("# Freeze the retention contract")] + source[source.index("\n\n\ndef _same"):]
old = old.replace("\n\n\n\ndef _same", "\n\n\ndef _same")
old = old.replace('    native = report["contract_id"] == "p04-managed-model-execution-v1"\n'
    '    expected_sources = NATIVE_RETAINED_SOURCES if native else PYTHON_RETAINED_SOURCES\n'
    '    retained = _inventory(report["retained_sources"], "retained sources", sorted_paths=True,\n'
    '                          expected=("artifacts/source/" + name for name in expected_sources))',
    '    retained = _inventory(report["retained_sources"], "retained sources", sorted_paths=True)')
old = old.replace('    expected_helpers = NATIVE_HELPERS if native else PYTHON_HELPERS',
    '    expected_helpers = NATIVE_HELPERS if report["contract_id"] == "p04-managed-model-execution-v1" else PYTHON_HELPERS')
start = old.index("def _command_interval(")
old = old[:start] + old[old.index("def _command(row", start):]
old = old.replace("    _command_interval(report, commands)\n", "")
old_digest = hashlib.sha256(old.encode()).hexdigest()
assert old_digest == "68353accd535c95faaccf9725cb6fb611152773ef4a25bb1474114d9b35b4967"


class InertLogs:
    def files(self):
        return ["logs/c" + str(i) + ".log" for i in range(4)]

    def verified(self, row, path, *, limit):
        assert row == {"path": path, "sha256": hashlib.sha256(b"").hexdigest(), "size_bytes": 0}
        return b""


report = dict(schema_version=1, contract_id="p04-managed-model-execution-v1", state="finished",
              outcome="pass", reason=None, development=False, acceptance_claimed=False,
              phase_complete=False, iterations=2, started_at="2025-12-31T23:59:59+00:00",
              finished_at="2026-01-01T00:00:00+00:00", limitations=["synthetic inert data"],
              budget={"max_rss_bytes": 1024}, commands=[])
for i in range(4):
    report["commands"].append(dict(id="c" + str(i), argv=["/missing/tool"], cwd="/missing/work",
        environment={}, log="logs/c" + str(i) + ".log", timeout_seconds=1, outcome="pass",
        exit_code=0, reason=None, process_started=True, duration_seconds=0.75,
        log_sha256=hashlib.sha256(b"").hexdigest(), log_size_bytes=0, peak_rss_bytes=0,
        cleanup_complete=True, limitations=list(r.PROCESS_LIMITATIONS)))
r._finished(report, report["contract_id"])
commands = r._commands(InertLogs(), report, ["c" + str(i) for i in range(4)])
r._command_interval(report, commands)
report["commands"][-1]["duration_seconds"] += 0.000001
commands = r._commands(InertLogs(), report, list(commands))
try:
    r._command_interval(report, commands)
except ValueError as error:
    assert str(error) == "commands exceed the recorded execution interval"
else:
    raise AssertionError("one-microsecond sequential overrun accepted")
print(json.dumps({"historical_revision": REV, "native_helpers": len(nh), "python_helpers": len(ph),
    "required_native": len(native), "required_python": len(python), "runtime_files_present": len(runtime),
    "reverse_patch_sha256": old_digest,
    "year_boundary_elapsed_seconds": 1, "control_sum_seconds": 3.0, "control": "accepted",
    "negative_sum_seconds": sum(row["duration_seconds"] for row in commands.values()),
    "negative": "rejected", "scope": "static historical AST plus validated helper composition"}, sort_keys=True))
