"""Host-only audit probe; an audit hook rejects fd wrapping, not file open."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile

repo = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(repo / "ci/project"))
import p05_bundle

spec = importlib.util.spec_from_file_location("a002_bundle", repo / "python/vortex_ai/_bundle.py")
bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle)

with tempfile.TemporaryDirectory(prefix="a002-fd-ownership-") as directory:
    root = Path(directory)
    path = root / "input"
    path.write_bytes(b"host-only checked bytes\n")
    target = path.stat()
    descriptors = []

    def audit(event, args):
        if event == "open" and type(args[0]) is int:
            stamp = os.fstat(args[0])
            if (stamp.st_dev, stamp.st_ino) == (target.st_dev, target.st_ino):
                descriptors.append(args[0])
                raise RuntimeError("a002: fd wrapper creation rejected")

    sys.addaudithook(audit)
    for label, call in (
        ("installed read_file", lambda: bundle.read_file(root, "input")),
        ("producer _consume", lambda: p05_bundle._consume(root, "input", limit=1024)),
    ):
        before = len(os.listdir("/proc/self/fd"))
        start = len(descriptors)
        for _ in range(3):
            try:
                call()
            except RuntimeError as error:
                assert str(error) == "a002: fd wrapper creation rejected"
            else:
                raise AssertionError("expected audit-hook rejection")
        leaked = []
        for fd in descriptors[start:]:
            try:
                stamp = os.fstat(fd)
            except OSError:
                continue
            if (stamp.st_dev, stamp.st_ino) == (target.st_dev, target.st_ino):
                leaked.append(fd)
        print(label, "open_after_three_failures=", leaked,
              "fd_count_delta=", len(os.listdir("/proc/self/fd")) - before)
        for fd in leaked:
            os.close(fd)
        print(label, "fd_count_after_probe_cleanup=", len(os.listdir("/proc/self/fd")) - before)
        assert len(leaked) == 3, "base must exhibit all three leaks"
