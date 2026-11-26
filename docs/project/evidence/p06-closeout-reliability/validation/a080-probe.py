"""Temporary, bounded setup-failure probe; outside unittest discovery."""

import copy
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent / "AI-GPU"
sys.path.insert(0, str(ROOT / "ci/project"))
import test_p06_hosted_prelaunch_emission as target


class SetupMarker(RuntimeError):
    pass


def main():
    mode = sys.argv[1]
    assert mode in ("before", "after")
    signal.alarm(20)
    hosted = target.hosted
    fixture = target.fixtures.HostedCompositionTests
    original_setup = fixture.setUp
    registry = hosted.runner.ORIGINAL_ARCHIVES
    saved_registry = copy.deepcopy(registry)
    saved_environment = dict(os.environ)
    attributes = [
        (hosted, "preflight"),
        (hosted.encryption, "validate_recipient"),
        (hosted.sys, "version_info"),
        (hosted.sys, "executable"),
        (hosted.platform, "machine"),
        (hosted.platform, "python_implementation"),
        (hosted, "provision_age"),
        (hosted, "provision_host"),
        (hosted, "capacity_gate"),
        (hosted, "run_bounded"),
    ]
    saved_attributes = [(owner, name, getattr(owner, name)) for owner, name in attributes]
    captured = []
    evidence = {
        "mode": mode,
        "source_sha256": hashlib.sha256(Path(target.__file__).read_bytes()).hexdigest(),
        "fixture_sha256": hashlib.sha256(Path(target.fixtures.__file__).read_bytes()).hexdigest(),
    }

    def late_failure(case):
        captured.append(case)
        original_setup(case)
        assert len(case._cleanups) == 2
        assert len(case.stack._exit_callbacks) == 12
        assert registry != saved_registry
        assert dict(os.environ) != saved_environment
        assert all(getattr(owner, name) is not value for owner, name, value in saved_attributes)
        assert case.root.is_dir()
        evidence["real_setup_completed"] = True
        evidence["registered_cleanups"] = len(case._cleanups)
        evidence["registered_patch_exits"] = len(case.stack._exit_callbacks)
        raise SetupMarker("a080-after-real-setup")

    def observations(case):
        return {
            "registry_restored": registry == saved_registry,
            "environment_restored": dict(os.environ) == saved_environment,
            "all_patched_attributes_restored": all(
                getattr(owner, name) is value for owner, name, value in saved_attributes),
            "temporary_directory_removed": not case.root.exists(),
            "cleanup_registry_drained": not case._cleanups,
            "patch_exit_registry_drained": not case.stack._exit_callbacks,
        }

    try:
        with mock.patch.object(fixture, "setUp", new=late_failure):
            try:
                with target._composition():
                    raise AssertionError("fixture context unexpectedly yielded")
            except SetupMarker as error:
                assert str(error) == "a080-after-real-setup"
                evidence["marker_propagated"] = True
            else:
                raise AssertionError("setup marker did not propagate")
        assert len(captured) == 1
        case = captured[0]
        evidence["automatic_cleanup"] = observations(case)
        assert all(value is (mode == "after") for value in evidence["automatic_cleanup"].values())
        assert hosted.runner.ORIGINAL_ARCHIVES is registry
        evidence["registry_identity_preserved"] = True
    finally:
        for case in captured:
            case.doCleanups()
        assert captured and all(observations(captured[0]).values())
        assert fixture.setUp is original_setup
        evidence["probe_safeguard_cleanup_restored_all"] = True
        signal.alarm(0)
    evidence["result"] = "expected-leak-reproduced" if mode == "before" else "cleanup-restored"
    print(json.dumps(evidence, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
