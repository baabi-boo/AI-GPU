"""Agent14 independent host-only probes; imports only trusted checkout fixtures."""
import copy
import json
from test_p05_replay_installation import SyntheticInstallation, encoded, record
import p05_replay_installation as replay


def emit(name, result):
    print(json.dumps({"probe": name, **result}, sort_keys=True))


fixture = SyntheticInstallation()
emit("positive-control", {"accepted": fixture.run()["summary"]["scope"]})

fixture = SyntheticInstallation()
tools = fixture.snapshot_value("python", fixture.pr, "package_tools_before")
identity = fixture.tr["provisioning_interpreter"]
conflicting = record(identity["path"], b"Contradictory absent interpreter bytes")
assert conflicting["sha256"] != identity["sha256"]
tools["distributions"]["setuptools"]["files"] = [conflicting]
for when in ("before", "after"):
    fixture.snapshot("python", fixture.pr, "package_tools_" + when, tools)
    fixture.put("python", "logs/package-tools-" + when + ".log", b"P05_PACKAGE_TOOLS " + encoded(tools) + b"\n")
emit("tool-file-conflicts-with-provisioning-interpreter", {
    "accepted": fixture.run()["summary"]["scope"],
    "path": identity["path"], "interpreter_sha256": identity["sha256"],
    "package_tool_sha256": conflicting["sha256"],
})

fixture = SyntheticInstallation()
before = fixture.snapshot_value("torch", fixture.tr, "framework_before")
original = copy.deepcopy(before["distributions"]["vortex_ai"]["files"])
assert len(original) > 1
moved = original[1:]
before["distributions"]["vortex_ai"]["files"] = original[:1]
before["distributions"]["torch"]["files"] += moved
raw_path = "torch/logs/framework-environment-before.log"
raw = json.loads(fixture.files[raw_path].split(b" ", 1)[1])
raw["distributions"]["vortex_ai"]["files"] = [row["path"].removeprefix(replay.SITE) for row in original[:1]]
raw["distributions"]["torch"]["files"] += [row["path"].removeprefix(replay.SITE) for row in moved]
raw["distributions"]["torch"]["files"].sort()
installed = {row["path"]: row for row in fixture.snapshot_value("torch", fixture.tr, "installed_before")}
for name, distribution in raw["distributions"].items():
    before["distributions"][name]["files"] = [installed[replay._distribution_path(path, replay._archive_api())] for path in distribution["files"]]
for when in ("before", "after"):
    fixture.snapshot("torch", fixture.tr, "framework_" + when, before)
    fixture.put("torch", "logs/framework-environment-" + when + ".log", b"P05_TORCH_ENVIRONMENT " + encoded(raw) + b"\n")
emit("retained-first-party-files-claimed-by-torch-distribution", {
    "accepted": fixture.run()["summary"]["scope"],
    "retained_vortex_files": len(original), "vortex_distribution_files": 1,
    "transferred_first_party_rows": len(moved),
})

fixture = SyntheticInstallation()
value = fixture.snapshot_value("torch", fixture.tr, "installed_after")
value[0]["sha256"] = "0" * 64
fixture.snapshot("torch", fixture.tr, "installed_after", value)
try:
    fixture.run()
except ValueError as error:
    emit("negative-control-installed-stability", {"rejected": str(error)})
else:
    raise AssertionError("negative control incorrectly accepted")
