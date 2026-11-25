# SPDX-License-Identifier: Apache-2.0
"""Independent, inert real-fd reproduction of final packaging-close masking.

Run from the source root with PYTHONPATH=ci/project and bytecode disabled.
No native workload, network, source mutation, or fixture model is used.
"""

import errno
import hashlib
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

import p06_qualified_warm_pack as pack


def is_open(descriptor):
    try:
        os.fstat(descriptor)
        return True
    except OSError as error:
        if error.errno != errno.EBADF:
            raise
        return False


def probe(action, primary):
    real_open, real_close, real_dup2 = os.open, os.close, os.dup2
    state = {"output_fd": None, "unrelated_fd": None, "close_attempts": 0}
    secondary = OSError(errno.EIO, "output close failed after consuming descriptor")
    with tempfile.TemporaryDirectory(prefix="agent47-final-close-") as temporary:
        root = Path(temporary)
        source, workspace, output = (root / name for name in ("source", "workspace", "packet"))
        source.mkdir()
        workspace.mkdir()

        def opened(path, *args, **kwargs):
            descriptor = real_open(path, *args, **kwargs)
            if path == output.name and kwargs.get("dir_fd") is not None:
                state["output_fd"] = descriptor
            return descriptor

        def closed(descriptor):
            real_close(descriptor)
            if descriptor == state["output_fd"]:
                state["close_attempts"] += 1
                unrelated = real_open("/dev/null", os.O_RDONLY | os.O_CLOEXEC)
                # The earlier parent number may be the lowest free fd. Assign
                # the consumed number explicitly to model exact-number reuse.
                if unrelated != descriptor:
                    real_dup2(unrelated, descriptor, inheritable=False)
                    real_close(unrelated)
                    unrelated = descriptor
                state["unrelated_fd"] = unrelated
                raise secondary

        caught = None
        try:
            with patch.object(pack, "_inventory", side_effect=primary), \
                    patch.object(pack.os, "open", side_effect=opened), \
                    patch.object(pack.os, "close", side_effect=closed):
                try:
                    action(source_dir=source, workspace_dir=workspace,
                           output_dir=output, writers_finished=True)
                except BaseException as error:
                    caught = error
            receipt = json.loads((output / pack.FAILURE_NAME).read_text())
            result = {
                "action": action.__name__,
                "primary_type": type(primary).__name__,
                "raised_primary": caught is primary,
                "raised_secondary": caught is secondary,
                "secondary_context_is_primary": caught is not None and caught.__context__ is primary,
                "output_fd": state["output_fd"],
                "unrelated_fd": state["unrelated_fd"],
                "unrelated_survived": is_open(state["unrelated_fd"]),
                "output_close_attempts": state["close_attempts"],
                "failure_receipt_outcome": receipt["outcome"],
                "failure_receipt_error_type": receipt["error_type"],
                "failure_receipt_stage": receipt["stage"],
                "retained_names": sorted(item.name for item in output.iterdir()),
            }
            assert result["unrelated_survived"] and result["output_close_attempts"] == 1
            assert result["failure_receipt_outcome"] == "fail"
            assert result["failure_receipt_error_type"] == type(primary).__name__
            assert caught is primary or caught is secondary, "unexpected probe failure"
            return result
        finally:
            if state["unrelated_fd"] is not None and is_open(state["unrelated_fd"]):
                real_close(state["unrelated_fd"])


source = Path(pack.__file__)
rows = [probe(action, error_type("primary inventory failure"))
        for action in (pack.package_success, pack.package_partial)
        for error_type in (KeyboardInterrupt, ValueError, RuntimeError)]
print(json.dumps({
    "scope": "independent-final-packaging-close-host-fault-probe",
    "source_path": str(source),
    "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    "cases": rows,
    "case_count": len(rows),
    "masked_primary_count": sum(row["raised_secondary"] for row in rows),
    "preserved_primary_count": sum(row["raised_primary"] for row in rows),
}, indent=2, sort_keys=True))
