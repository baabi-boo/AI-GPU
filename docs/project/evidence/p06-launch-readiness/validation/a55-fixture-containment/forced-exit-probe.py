"""Probe parent ownership after killing the unchanged warm scenario at setup."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time


CHILD = """
import os
from pathlib import Path
import signal
import sys
from unittest import mock
import test_p06_qualified_warm_cancellation as cancellation

def stop_after_fixture_setup(argv):
    paths = cancellation.PREFLIGHT.base.resolve_paths(None)
    Path(sys.argv[1], 'fixture-root').write_text(str(paths['source'].parent), encoding='utf-8')
    os.kill(os.getpid(), signal.SIGKILL)

with mock.patch.object(cancellation.runner, 'main', side_effect=stop_after_fixture_setup):
    cancellation._scenario(sys.argv[1], 'source')
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    project = args.source.resolve()
    source = project / "ci/project/test_p06_qualified_warm_cancellation.py"
    started = time.monotonic()
    report = {"scope": "host fixture containment only; no native execution",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "interpreter": sys.executable}
    fixture_root = None
    try:
        with tempfile.TemporaryDirectory(prefix="a55-warm-forced-exit-") as temporary:
            directory = Path(temporary).resolve()
            command = [sys.executable, "-B", "-c", CHILD, str(directory)]
            result = subprocess.run(command, cwd=project / "ci/project",
                env=dict(os.environ, TMPDIR=str(directory), PYTHONDONTWRITEBYTECODE="1"),
                capture_output=True, text=True, timeout=10, check=False)
            report.update(child_returncode=result.returncode,
                child_stdout=result.stdout, child_stderr=result.stderr)
            assert result.returncode == -signal.SIGKILL, report
            fixture_root = Path((directory / "fixture-root").read_text(encoding="utf-8"))
            report.update(parent_directory=str(directory), fixture_root=str(fixture_root),
                fixture_present_after_sigkill=fixture_root.is_dir(),
                fixture_contained_by_parent=fixture_root.is_relative_to(directory))
            assert report["fixture_present_after_sigkill"], report
            assert report["fixture_contained_by_parent"], report
        report.update(parent_present_after_cleanup=directory.exists(),
            fixture_present_after_parent_cleanup=fixture_root.exists(),
            duration_seconds=time.monotonic() - started)
        assert not report["parent_present_after_cleanup"], report
        assert not report["fixture_present_after_parent_cleanup"], report
        report["status"] = "pass"
        print(json.dumps(report, indent=2))
    finally:
        if fixture_root is not None and fixture_root.exists():
            shutil.rmtree(fixture_root)


if __name__ == "__main__":
    main()
