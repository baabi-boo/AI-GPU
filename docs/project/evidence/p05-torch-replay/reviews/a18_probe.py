"""Independent host-only probe of the a16 receipt joins; no retained code runs."""
import copy
import hashlib
import json
from pathlib import Path
import sys

import p05_replay_installation as installation
import p05_replay_native as native
from test_p05_replay_installation import SyntheticInstallation, encoded, record

FILES = (
    "ci/project/p05_replay_installation.py",
    "ci/project/test_p05_replay_installation_identity.py",
    "ci/project/test_p05_replay_installation.py",
    "ci/project/p05_replay_native.py",
    "ci/project/p05_torch_replay.py",
    "docs/project/evidence/p05-torch/reviews/archive_reader.py",
)

def hashes():
    return {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in FILES}

def forbid_producer_access(event, args):
    if event == "open" and isinstance(args[0], (str, bytes)):
        name = args[0].decode() if isinstance(args[0], bytes) else args[0]
        if name == "/producer" or name.startswith("/producer/"):
            raise AssertionError("producer path was opened")
    if event in ("subprocess.Popen", "os.system", "os.exec", "os.posix_spawn"):
        raise AssertionError("process execution attempted")

sys.addaudithook(forbid_producer_access)
before_hashes = hashes()

def tools_and_packages(fixture, *, tool_conflict=False, package_conflict=False):
    names = ("make", "g++", "gcc", "ar", "as", "ld", "python3", "bash", "perl", "clang", "clang++",
             "llvm-objcopy", "llvm-objdump", "riscv-gcc", "riscv-gcc-ar", "riscv-objcopy", "riscv-objdump",
             "libc64/lib/libc.a", "libc64/lib/libm.a", "libcrt64/lib/baremetal/libclang_rt.builtins-riscv64.a")
    tools = {name: {**record("/producer/tools/" + name, name.encode()),
                    "resolved_path": "/producer/tools/" + name} for name in names}
    tools["python3"] = copy.deepcopy(fixture.tr["provisioning_interpreter"])
    common = record("/producer/resolved/shared-tool", b"absent shared executable")
    for name in ("make", "gcc"):
        tools[name] = {**common, "path": "/producer/aliases/" + name, "resolved_path": common["path"]}
    if tool_conflict:
        tools["gcc"]["sha256"] = "0" * 64
    # Exercise the actual upstream row-shape validator too. It deliberately
    # does not perform the cross-path join now owned by installation replay.
    class View:
        def document(self, descriptor, path):
            return copy.deepcopy(tools)
    assert native._tools(View(), {"tools_before": None, "tools_after": None}) == tools
    for when in ("before", "after"):
        fixture.snapshot("python", fixture.pr, "tools_" + when, tools)
    package = fixture.snapshot_value("python", fixture.pr, "package_tools_before")
    package["distributions"]["wheel"]["files"] = [dict(common)]
    if package_conflict:
        package["distributions"]["wheel"]["files"][0]["size_bytes"] += 1
    for when in ("before", "after"):
        fixture.snapshot("python", fixture.pr, "package_tools_" + when, package)
        fixture.put("python", "logs/package-tools-" + when + ".log", b"P05_PACKAGE_TOOLS " + encoded(package) + b"\n")

def swap_ownership(fixture):
    value = fixture.snapshot_value("torch", fixture.tr, "framework_before")
    rows = value["distributions"]
    first = installation.SITE + installation.DIST + "direct_url.json"
    foreign = next(row["path"] for row in rows["torch"]["files"] if row["path"].endswith(".dist-info/WHEEL"))
    a = next(row for row in rows["vortex_ai"]["files"] if row["path"] == first)
    b = next(row for row in rows["torch"]["files"] if row["path"] == foreign)
    rows["vortex_ai"]["files"] = [b if row is a else row for row in rows["vortex_ai"]["files"]]
    rows["torch"]["files"] = [a if row is b else row for row in rows["torch"]["files"]]
    raw = copy.deepcopy(value)
    for name, distribution in rows.items():
        relative = lambda path: path[len(installation.SITE):] if path.startswith(installation.SITE) else "../../../" + path
        distribution["files"].sort(key=lambda row: relative(row["path"]))
        raw["distributions"][name]["files"] = [relative(row["path"]) for row in distribution["files"]]
    for when in ("before", "after"):
        fixture.snapshot("torch", fixture.tr, "framework_" + when, value)
        fixture.put("torch", "logs/framework-environment-" + when + ".log", b"P05_TORCH_ENVIRONMENT " + encoded(raw) + b"\n")

outcomes = []
for label, flags, swap, expected in (
    ("consistent resolved aliases and package receipt", {}, False, None),
    ("resolved executable alias digest collision", {"tool_conflict": True}, False, "recorded file identity /producer/resolved/shared-tool differs"),
    ("package/resolved executable size collision", {"package_conflict": True}, False, "recorded file identity /producer/resolved/shared-tool differs"),
    ("equal-count Vortex/Torch ownership swap", {}, True, "framework first-party distribution membership differs"),
):
    fixture = SyntheticInstallation()
    tools_and_packages(fixture, **flags)
    if swap:
        swap_ownership(fixture)
    try:
        result = fixture.run()
    except installation.InstallationError as error:
        assert expected is not None and str(error) == expected, (label, str(error))
        outcomes.append({"case": label, "outcome": "rejected", "message": str(error)})
    else:
        assert expected is None, (label, "unexpected acceptance")
        summary = result["summary"]
        assert summary["scope"] == "retained-installation-consistency"
        assert summary["native_execution"] == "not_run"
        assert len(summary["limitations"]) == 7
        assert all(summary[key] is False for key in ("third_party_bytes_rehashed", "interpreter_bytes_rehashed", "retained_code_executed", "acceptance_claimed", "phase_acceptance"))
        assert any(row[2] == 440280512 for row in result["torch_identity"].installed_files)
        outcomes.append({"case": label, "outcome": "accepted", "limits": 7, "large_absent_receipt_bytes": 440280512})

assert hashes() == before_hashes, "reviewed files changed during probe"
print(json.dumps({"scope": "four host-only helper probes", "outcomes": outcomes,
                  "source_sha256": before_hashes, "sources_stable": True}, indent=2))
