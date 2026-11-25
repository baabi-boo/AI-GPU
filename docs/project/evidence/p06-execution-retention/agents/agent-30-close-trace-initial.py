# SPDX-License-Identifier: Apache-2.0
"""Independent logical-ownership trace over real packaging setup descriptors."""
import errno
import json
import os
from pathlib import Path
import tempfile
from unittest import mock

import p06_qualified_warm_pack as pack


def is_open(descriptor):
    try:
        os.fstat(descriptor)
        return True
    except OSError as error:
        assert error.errno == errno.EBADF
        return False


def check(action, mode, cleanup_error=None):
    with tempfile.TemporaryDirectory(prefix="agent30-setup-") as temporary:
        root = Path(temporary).resolve()
        source, workspace, output = (root / part for part in ("source", "workspace", "output"))
        source.mkdir()
        workspace.mkdir()
        real_directory = pack._directory
        active = {}
        owned = {}
        closes = []
        unrelated = None
        failure = OSError(errno.EIO, mode)

        class OSProxy:
            def __getattr__(self, name):
                return getattr(os, name)

            def open(self, path, flags, *args, **kwargs):
                selected = path == output.name and kwargs.get("dir_fd") == owned.get("parent")
                if selected and mode == "output_open":
                    raise failure
                descriptor = os.open(path, flags, *args, **kwargs)
                if selected:
                    owned["output"] = descriptor
                    active[descriptor] = "output"
                return descriptor

            def mkdir(self, path, *args, **kwargs):
                if path == output.name and mode == "mkdir":
                    raise failure
                return os.mkdir(path, *args, **kwargs)

            def close(self, descriptor):
                nonlocal unrelated
                role = active.pop(descriptor, None)
                if role is not None:
                    closes.append({"role": role, "fd": descriptor})
                os.close(descriptor)
                if (role, mode) in (("parent", "parent_close"), ("source", "source_close")):
                    unrelated = os.open("/dev/null", os.O_RDONLY | os.O_CLOEXEC)
                    assert unrelated == descriptor, "exact descriptor reuse required"
                    raise failure
                if role == "output" and cleanup_error is not None:
                    raise cleanup_error

        def directory(path):
            descriptor = real_directory(path)
            role = "source" if path == source else "parent" if path == output.parent else None
            if role is not None:
                owned[role] = descriptor
                active[descriptor] = role
            return descriptor

        try:
            caught = None
            with mock.patch.object(pack, "os", OSProxy()), \
                    mock.patch.object(pack, "_directory", side_effect=directory), \
                    mock.patch.object(pack, "_inventory") as inventory:
                try:
                    action(source_dir=source, workspace_dir=workspace, output_dir=output,
                           writers_finished=True)
                except BaseException as error:
                    caught = error
            assert caught is failure, "original setup exception must survive"
            inventory.assert_not_called()
            counts = {role: sum(event["role"] == role for event in closes) for role in owned}
            assert all(count == 1 for count in counts.values()), counts
            assert not active, active
            expected = {"source"} if mode == "source_close" else {"source", "parent"}
            if mode == "parent_close":
                expected.add("output")
            assert set(owned) == expected, owned
            for role, descriptor in owned.items():
                if descriptor != unrelated:
                    assert not is_open(descriptor), (role, descriptor)
            if unrelated is not None:
                assert is_open(unrelated), "unrelated reused descriptor must survive"
            return {"api": action.__name__, "mode": mode,
                    "cleanup_error": None if cleanup_error is None else type(cleanup_error).__name__,
                    "owned_fds": owned, "close_events": closes, "close_counts": counts,
                    "original_exception_preserved": caught is failure,
                    "unrelated_reused_fd": unrelated,
                    "unrelated_fd_survives": None if unrelated is None else is_open(unrelated),
                    "all_owned_lifetimes_closed_once": True, "inventory_not_called": True}
        finally:
            for descriptor in set(owned.values()) | ({unrelated} if unrelated is not None else set()):
                if is_open(descriptor):
                    os.close(descriptor)


results = []
for api in (pack.package_success, pack.package_partial):
    for secondary in (None, OSError(errno.ENOSPC, "consumed output cleanup"), KeyboardInterrupt()):
        results.append(check(api, "parent_close", secondary))
    for boundary in ("source_close", "mkdir", "output_open"):
        results.append(check(api, boundary))
print(json.dumps({"case_count": len(results), "outcome": "pass", "cases": results}, indent=2))
