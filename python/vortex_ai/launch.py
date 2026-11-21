# SPDX-License-Identifier: Apache-2.0
"""Verify a pinned bundle before starting Python with its native library path."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

from . import _bundle


def verified_environment(bundle_root, *, environment=None):
    """Return a child environment after checking the compiled pin and all files."""
    environment = dict(os.environ if environment is None else environment)
    for key in ("LD_PRELOAD", "LD_AUDIT", "LD_LIBRARY_PATH"):
        if environment.get(key):
            raise _bundle.BundleError(key + " must be absent before starting the bundle launcher")
    if environment.get("VORTEX_DRIVER") not in (None, "", "simx"):
        raise _bundle.BundleError("VORTEX_DRIVER conflicts with the SimX bundle")
    # Importing this extension loads no project runtime or simulator libraries.
    from . import _native

    identity = _native.build_info()
    if (type(identity) is not dict
            or set(identity) != {"bundle_sha256", "source_sha256", "binding_api"}
            or type(identity["binding_api"]) is not int or identity["binding_api"] != 1
            or not identity["bundle_sha256"]):
        raise _bundle.BundleError("the installed extension is not a bound API-1 package")
    root, digest, manifest = _bundle.read_manifest(bundle_root)
    if (digest != identity["bundle_sha256"]
            or manifest["binding_source_sha256"] != identity["source_sha256"]):
        raise _bundle.BundleError("the bundle does not match the installed extension's immutable pin")
    _bundle.validate_files(root, manifest)
    # The five checked project libraries must be the only entries on this path.
    environment["LD_LIBRARY_PATH"] = str(root / "lib")
    environment["VORTEX_DRIVER"] = "simx"
    for key in ("LD_PRELOAD", "LD_AUDIT", "PYTHONPATH", "PYTHONHOME", "VORTEX_AI_BUNDLE"):
        environment.pop(key, None)
    return environment


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, help="directory matching this wheel's native pin")
    parser.add_argument("command", nargs=argparse.REMAINDER,
                        help="-- /absolute/script.py [script arguments]")
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command or command[0].startswith("-"):
        parser.error("supply a Python script after --")
    try:
        script = Path(command[0]).resolve(strict=True)
        if not script.is_file():
            raise _bundle.BundleError("the Python script must be a regular file")
        environment = verified_environment(args.bundle)
        result = subprocess.run([sys.executable, "-I", "-B", str(script), *command[1:]],
                                env=environment, check=False)
    except (_bundle.BundleError, ImportError, OSError, RuntimeError) as error:
        print("vortex_ai.launch: " + str(error), file=sys.stderr)
        return 2
    return result.returncode if result.returncode >= 0 else 128 - result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
