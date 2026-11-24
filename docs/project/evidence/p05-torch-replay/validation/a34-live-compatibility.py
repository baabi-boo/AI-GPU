#!/usr/bin/env python3
"""One synthetic host witness plus static comparison of the live P05 seam."""
from contextlib import ExitStack
import ast
import builtins
import copy
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
from unittest import mock

ROOT = Path(__file__).resolve().parents[1] / "AI-GPU"
BASE = "f01c9d03147343d274ee0a45b71b34f004709c0e"
SEAM = "c6fb039e706e812b6b3f4d2a5db1828076fe50df"
NAMES = ("p05_installed_check", "p05_execution_records", "p05_torch_records")
EXPECTED = (
    "69d530bea385f2d0545cc677b8205585c42398f4ace2837b840b14d5cabfac5b",
    "1f5c9f7d0e66de1537e952b9432e10543563c61eab164e1762416bae07fa7ffe",
    "3ff925b09b3176b1f328101bfa9d062aac48f0c3f0939fd847646128f8587639",
)
CALLERS = ("p05_execute", "p05_torch_execute", "p05_torch_installed_check")
PATHS = ["ci/project/" + name + ".py" for name in (*NAMES, *CALLERS, "p05_torch_replay",
    "p05_qualification_test_fixture", "p05_torch_qualification_test_fixture")]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git_bytes(revision, path):
    return subprocess.run(["git", "show", revision + ":" + path], cwd=ROOT,
                          check=True, stdout=subprocess.PIPE).stdout


def dump(node):
    return ast.dump(node, include_attributes=False)


def body(function):
    result = copy.deepcopy(function.body)
    if result and isinstance(result[0], ast.Expr) and isinstance(result[0].value, ast.Constant) \
            and isinstance(result[0].value.value, str):
        result.pop(0)
    return result


def functions(data):
    return {node.name: node for node in ast.parse(data).body if isinstance(node, ast.FunctionDef)}


def bodies_equal(left, right):
    return dump(ast.Module(body=left, type_ignores=[])) == dump(ast.Module(body=right, type_ignores=[]))


def merged_guard(first, second):
    # Sequential require(A, message); require(B, message) preserves A-and-B
    # short-circuit order. Only apply when both use the identical guard/message.
    assert first.value.func.id == second.value.func.id == "require"
    assert dump(first.value.args[1]) == dump(second.value.args[1])
    first = copy.deepcopy(first)
    first.value.args[0] = ast.BoolOp(op=ast.And(),
        values=first.value.args[0].values + copy.deepcopy(second.value.args[0].values))
    return first


snapshot = {path: (ROOT / path).read_bytes() for path in PATHS}
evidence = {"scope": "synthetic host-only; no native/framework package execution",
            "base": BASE, "reviewed_seam": SEAM,
            "source_sha256": {path: sha(data) for path, data in snapshot.items()},
            "current_matches_agent11_and_c6": {}, "normalized_base_ast": {},
            "callers_unchanged_from_base": {}, "caller_map": []}
old, current = {}, {}
for name, expected in zip(NAMES, EXPECTED):
    path = "ci/project/" + name + ".py"
    data, seam = snapshot[path], git_bytes(SEAM, path)
    assert sha(data) == expected and data == seam and dump(ast.parse(data)) == dump(ast.parse(seam))
    evidence["current_matches_agent11_and_c6"][name] = True
    old[name], current[name] = functions(git_bytes(BASE, path)), functions(data)

# Reconstitute only the mechanically extracted live bodies. The only local
# alias normalization is request['binding'] -> binding after its assignment.
name = NAMES[0]
before, after = old[name], current[name]
header = body(after["_request_header_data"])
loop = body(after["validate_request"])[1]
loop.iter.elts[0].elts[0].value = ast.Name(id="binding", ctx=ast.Load())
loop.body = body(after["_request_path_data"]) + loop.body[1:]
cases = body(after["_request_cases_data"])
cases[0].value.value = ast.Name(id="binding", ctx=ast.Load())
evidence["normalized_base_ast"][name + ".validate_request"] = bodies_equal(
    body(before["validate_request"]), header + [loop] + cases)

name = NAMES[1]
before, after = old[name], current[name]
live = body(after["_installation"])
loop = live[1]
path_body = body(after["_installation_path"])[:-1]
loop.body = path_body[:-1] + [merged_guard(path_body[-1], loop.body[1])]
evidence["normalized_base_ast"][name + "._installation"] = bodies_equal(
    body(before["_installation"]), body(after["_installation_data"])[:-1] + [loop]
    + body(after["_installation_layout_data"]))
evidence["normalized_base_ast"][name + ".verify_observations"] = bodies_equal(
    body(before["verify_observations"]), body(after["_observation_header"])
    + [body(after["verify_observations"])[1]] + body(after["_verify_observation_records"]))

name = NAMES[2]
before, after = old[name], current[name]
evidence["normalized_base_ast"][name + ".validate_request"] = bodies_equal(
    body(before["validate_request"]), body(after["_request_header"]) + body(after["validate_request"])[1:])
framework_data, live = body(after["_framework_data"]), body(after["_framework"])
evidence["normalized_base_ast"][name + "._framework"] = bodies_equal(
    body(before["_framework"]), framework_data[:-1]
    + [merged_guard(framework_data[-1], live[2])] + live[3:])
live = body(after["verify_observations"])
evidence["normalized_base_ast"][name + ".verify_observations"] = bodies_equal(
    body(before["verify_observations"]), live[:2] + body(after["_observation_header"])[:-1]
    + live[3:5] + body(after["_verify_framework_records"])[1:])
assert all(evidence["normalized_base_ast"].values()), evidence["normalized_base_ast"]

interesting = {"validate_request", "validate_request_data", "verify_observations",
               "verify_retained_observations", "read_request", "inspect_installation",
               "inspect_framework", "_installed_inventory"}
for name in (*CALLERS, "p05_torch_replay"):
    path = "ci/project/" + name + ".py"
    data = snapshot[path]
    if name in CALLERS:
        assert data == git_bytes(BASE, path)
        evidence["callers_unchanged_from_base"][name] = True
        assert "verify_retained_observations" not in data.decode()
        assert "validate_request_data" not in data.decode()
    for function in functions(data).values():
        for node in ast.walk(function):
            if isinstance(node, ast.Call):
                callee = ast.unparse(node.func)
                if callee.split(".")[-1] in interesting:
                    evidence["caller_map"].append({"file": path, "function": function.name,
                        "line": node.lineno, "callee": callee})

sys.path.insert(0, str(ROOT / "ci/project"))
import p05_installed_check as installed
import p05_execution_records as base_records
import p05_torch_records as torch_records
from p05_qualification_test_fixture import raw_log as base_raw_log
from p05_torch_qualification_test_fixture import raw_log, synthetic


def deny(*args, **kwargs):
    raise AssertionError("unexpected entry point or I/O")


def rejected(label, callback):
    try:
        callback()
    except (OSError, ValueError, installed.CheckError) as error:
        return {"label": label, "type": type(error).__name__, "message": str(error)}
    raise AssertionError(label + " unexpectedly passed")


with tempfile.TemporaryDirectory(prefix="a34-owned-host-fixture-") as temporary:
    producer = Path(temporary).resolve() / "producer"
    value, request, native = synthetic(producer, "bf16")
    observation, base_request = value["base_observations"], request["base_request"]
    installation = observation["installation"]
    adapter_path = Path(value["framework"]["adapter_file"])
    adapter = adapter_path.read_bytes()
    names = [installation[key] for key in ("executable", "package_file", "extension_file")]
    receipts = tuple((name, sha(data), len(data)) for name in (*names, str(adapter_path))
                     for data in (Path(name).read_bytes(),))
    identity = base_records.RetainedIdentity(sha(torch_records.canonical(base_request)), receipts)
    assert identity.__dataclass_params__.frozen and type(identity.installed_files) is tuple
    base_raw, framework_raw = base_raw_log(observation), raw_log(value)
    input_before = sha(torch_records.canonical([value, request, native]))
    live_calls = {
        "installed_request": lambda: installed.validate_request(base_request),
        "framework_request": lambda: torch_records.validate_request(request),
        "base_observations": lambda: base_records.verify_observations(
            observation, base_request, **native, raw_log=base_raw),
        "framework_observations": lambda: torch_records.verify_observations(
            value, request, **native, raw_log=framework_raw),
    }
    with ExitStack() as stack:
        for owner, name in ((installed, "validate_request_data"),
                            (torch_records, "validate_request_data"),
                            (base_records, "verify_retained_observations"),
                            (torch_records, "verify_retained_observations")):
            stack.enter_context(mock.patch.object(owner, name, deny))
        live = {label: callback() for label, callback in live_calls.items()}
        adapter_path.write_bytes(b"!" + adapter[1:])
        changed = rejected("same-size adapter mutation", live_calls["framework_observations"])
        assert changed["message"] == "installed framework adapter bytes differ"
        adapter_path.write_bytes(adapter)
        Path(installation["extension_file"]).unlink()
        extension = rejected("deleted extension with directories present", live_calls["base_observations"])
        assert extension["type"] == "FileNotFoundError"
        shutil.rmtree(producer)
        missing = [rejected(label, callback) for label, callback in live_calls.items()]

    denied = ((installed, "validate_request"), (installed, "inspect_installation"),
        (base_records, "verify_observations"), (base_records, "_installation"),
        (torch_records, "validate_request"), (torch_records, "verify_observations"),
        (torch_records, "_framework"), (builtins, "open"), (io, "open"), (os, "open"),
        (os, "stat"), (os, "lstat"), (os, "readlink"), (os, "listdir"), (os, "scandir"),
        (Path, "resolve"), (Path, "open"), (Path, "stat"), (Path, "is_file"), (Path, "is_dir"),
        (subprocess, "Popen"), (subprocess, "run"), (socket, "socket"),
        (socket, "create_connection"), (importlib, "import_module"))
    with ExitStack() as stack:
        for owner, name in denied:
            stack.enter_context(mock.patch.object(owner, name, deny))
        retained_base = base_records.verify_retained_observations(
            observation, base_request, retained_identity=identity, **native, raw_log=base_raw)
        retained_framework = torch_records.verify_retained_observations(
            value, request, retained_identity=identity, adapter_bytes=adapter, **native,
            raw_log=framework_raw)
    assert retained_base == live["base_observations"]
    assert retained_framework == live["framework_observations"]
    assert sha(torch_records.canonical([value, request, native])) == input_before
    evidence["witness"] = {"format": "bf16", "live_passed_with_retained_entrypoints_denied": list(live),
        "same_size_adapter_change": changed, "deleted_extension": extension,
        "deleted_producer": missing, "retained_matches_live_with_io_and_live_validators_denied": True,
        "counts_are_synthetic": True, "framework_result": retained_framework,
        "inputs_unchanged": True, "immutable_request_sha256": identity.request_sha256,
        "immutable_receipt_count": len(identity.installed_files)}

assert not any(name == "torch" or name.startswith("torch.") or name == "vortex_ai"
               or name.startswith("vortex_ai.") for name in sys.modules)
assert all((ROOT / path).read_bytes() == data for path, data in snapshot.items())
evidence.update(outcome="pass", source_unchanged=True, framework_native_packages_imported=False)
destination = ROOT.parent / "validation/a34-live-compatibility.json"
destination.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
print(json.dumps({"outcome": evidence["outcome"], "normalized_base_ast": evidence["normalized_base_ast"],
    "live_calls": len(live), "live_rejections": len(missing) + 2,
    "retained_matches_live": True, "source_unchanged": True, "result": str(destination)}, sort_keys=True))
