"""Independent inventory error-precedence control using synthetic input only."""

import errno
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest import mock


source = Path(sys.argv[1])
expected = sys.argv[2]
spec = importlib.util.spec_from_file_location("a038_encrypt_subject", source)
subject = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = subject
spec.loader.exec_module(subject)
real_close = os.close
results = []

for operation in ("read", "verify"):
    for primary_type in (OSError, KeyboardInterrupt):
        for cleanup_type in (OSError, KeyboardInterrupt):
            primary = primary_type("synthetic primary failure")
            secondary = cleanup_type("synthetic consuming parent-close failure")
            seen = {}

            def fail_operation(reader, *args, **kwargs):
                seen["parent"] = reader.parent
                seen["source"] = reader.stream.fileno()
                raise primary

            def close_once(descriptor):
                real_close(descriptor)
                if descriptor == seen.get("parent"):
                    seen["parent_closes"] = seen.get("parent_closes", 0) + 1
                    raise secondary

            with tempfile.TemporaryDirectory(prefix="a038-primary-") as temporary:
                root = Path(temporary)
                (root / "synthetic.bin").write_bytes(b"synthetic inventory bytes")
                with mock.patch.object(subject._VerifiedReader, operation, fail_operation), \
                        mock.patch.object(subject.os, "close", close_once):
                    try:
                        subject._inventory(root, time.monotonic() + 2)
                    except BaseException as actual:
                        observed = ("primary" if actual is primary else
                                    "secondary" if actual is secondary else "other")
                    else:
                        observed = "none"
                assert observed == expected, (operation, primary_type, cleanup_type, observed)
                assert seen["parent_closes"] == 1, seen
                for key in ("source", "parent"):
                    try:
                        os.fstat(seen[key])
                    except OSError as error:
                        assert error.errno == errno.EBADF, error
                    else:
                        raise AssertionError(key + " descriptor remained open")
                results.append({"operation": operation, "primary": primary_type.__name__,
                                "cleanup": cleanup_type.__name__, "observed": observed})

print(json.dumps({"source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                  "case_count": len(results), "results": results}, sort_keys=True))
