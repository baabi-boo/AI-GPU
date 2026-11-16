#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check early rejection of invalid selections by generated tensor test binaries."""

import argparse
import os
from pathlib import Path
import selectors
import signal
import subprocess
import tempfile
import time


TIMEOUT_SECONDS = 5
MAX_OUTPUT_BYTES = 64 * 1024
SIMULATION_MARKERS = ("PASSED", "Testing WMMA", "Testing floating-point",
                      "Testing integer", "Simulation completed", "Using configuration:")
COMMON_CASES = (
    ("zero-count", ["--tests=0"], "--tests"),
    ("negative-count", ["--tests=-1"], "--tests"),
    ("count-suffix", ["--tests=1junk"], "--tests"),
    ("fractional-count", ["--tests=1.5"], "--tests"),
    ("empty-count", ["--tests="], "--tests"),
    ("count-overflow", ["--tests=2147483648"], "--tests"),
    ("negative-tolerance", ["--ulp=-1"], "--ulp"),
    ("tolerance-suffix", ["--ulp=1junk"], "--ulp"),
    ("negative-index", ["--test=-2"], "--test"),
    ("index-outside-count", ["--tests=2", "--test=2"], "--test"),
    ("index-suffix", ["--test=0junk"], "--test"),
    ("negative-seed", ["--seed=-1"], "--seed"),
    ("seed-suffix", ["--seed=1junk"], "--seed"),
    ("negative-format", ["--fmt=-1"], "--fmt"),
    ("unsupported-format", ["--fmt=99"], "--fmt"),
    ("empty-features", ["--features="], "--features"),
    ("unknown-feature", ["--features=unknown"], "feature"),
    ("unsupported-rounding", ["--frm=RTZ"], "--frm"),
    ("unknown-option", ["--not-an-option"], "Unknown option"),
    ("zero-window", ["--W=0"], "--W"),
)
WMMA_CASES = (
    ("directed-selected-conflict", ["--directed", "--test=0"], "--directed"),
    ("empty-middle-feature", ["--features=normals,,zeros"], "feature"),
    ("empty-final-feature", ["--features=normals,"], "--features"),
    ("incompatible-window", ["--W=26"], "--W"),
    ("reversed-trace-range", ["--trace-start=10", "--trace-end=9"], "--trace-start"),
)
FEDP_CASES = (
    ("unsupported-format-gap", ["--fmt=6"], "Unsupported source format"),
    ("unsupported-fp32", ["--fmt=0"], "Source format is unavailable in the configured DUT backend"),
    ("unsupported-int32", ["--fmt=16"], "Source format is unavailable in the configured DUT backend"),
    ("sparsity-out-of-range", ["--sparsity=101"], "--sparsity"),
    ("scale-out-of-range", ["--sfa=256"], "--sfa"),
    ("exponent-out-of-range", ["--ext=9"], "--ext"),
    ("significand-out-of-range", ["--sig=24"], "--sig"),
)
FEDP_SCALE_CASES = (
    ("non-mx-a-scale", ["--sfa=0"], "require an MX source format"),
    ("non-mx-b-scale", ["--sfb=0"], "require an MX source format"),
)
WMMA_TFR_NO_TF32_CASES = (
    ("unsupported-tfr-fp32", ["--fmt=0", "--features=zeros", "--tests=1"], "FP32"),
    ("disabled-tfr-tf32", ["--fmt=1", "--features=zeros", "--tests=1"], "TF32"),
)
FEDP_NO_TF32_FP8_MX_CASES = (
    ("disabled-tfr-tf32", ["--fmt=1", "--features=normals", "--sparsity=100", "--tests=1"],
     "Source format is unavailable in the configured DUT backend"),
    ("disabled-tfr-fp8", ["--fmt=4", "--features=normals", "--sparsity=100", "--tests=1"],
     "Source format is unavailable in the configured DUT backend"),
    ("disabled-tfr-bf8", ["--fmt=5", "--features=normals", "--sparsity=100", "--tests=1"],
     "Source format is unavailable in the configured DUT backend"),
    ("disabled-tfr-mxfp8", ["--fmt=8", "--features=normals", "--sparsity=100", "--tests=1"],
     "MX source formats require VX_CFG_TCU_MX_ENABLE in the DUT build"),
    ("disabled-tfr-mxbf8", ["--fmt=9", "--features=normals", "--sparsity=100", "--tests=1"],
     "MX source formats require VX_CFG_TCU_MX_ENABLE in the DUT build"),
    ("disabled-tfr-mxfp4", ["--fmt=10", "--features=normals", "--sparsity=100", "--tests=1"],
     "MX source formats require VX_CFG_TCU_MX_ENABLE in the DUT build"),
    ("disabled-tfr-nvfp4", ["--fmt=11", "--features=normals", "--sparsity=100", "--tests=1"],
     "MX source formats require VX_CFG_TCU_MX_ENABLE in the DUT build"),
)


def executable(value):
    path = Path(value)
    if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
        raise argparse.ArgumentTypeError("use an absolute path to an executable test binary")
    return path.resolve(strict=True)


def run_command(argv, cwd):
    environment = {"PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C",
                   "TMPDIR": str(cwd)}
    output = bytearray()
    reason = None
    process = subprocess.Popen(argv, cwd=cwd, env=environment, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, start_new_session=True)
    deadline = time.monotonic() + TIMEOUT_SECONDS
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    reason = "command exceeded its five-second deadline"
                    break
                for key, _ in selector.select(min(remaining, 0.05)):
                    chunk = os.read(key.fd, 4096)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    if len(output) + len(chunk) > MAX_OUTPUT_BYTES:
                        reason = "command exceeded its 64 KiB output limit"
                        break
                    output.extend(chunk)
                if reason:
                    break
        if reason is None:
            try:
                process.wait(timeout=max(0.001, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                reason = "command exceeded its five-second deadline"
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=1)
        process.stdout.close()
    return process.returncode, output.decode("utf-8", errors="replace"), reason


def check_family(family, binary, work, *, wmma_tfr_no_tf32=False,
                 fedp_no_tf32_fp8_mx=False):
    cases = (("help", ["--help"], "Usage:"),) + COMMON_CASES
    cases += WMMA_CASES if family == "WMMA" else FEDP_CASES
    if family == "FEDP":
        cases += FEDP_SCALE_CASES
        if fedp_no_tf32_fp8_mx:
            cases += FEDP_NO_TF32_FP8_MX_CASES
            print("FEDP profile: TFR with TF32, FP8 and MX disabled (caller-selected)")
    elif wmma_tfr_no_tf32:
        cases += WMMA_TFR_NO_TF32_CASES
        print("WMMA profile: TFR with TF32 disabled (caller-selected)")
    failures = 0
    for name, arguments, diagnostic in cases:
        cwd = work / name
        cwd.mkdir()
        command = [str(binary), "--no-trace", "--fmt=2", "--W=25", *arguments]
        try:
            code, output, reason = run_command(command, cwd)
            if reason is None and ((name == "help" and code != 0)
                                   or (name != "help" and code <= 0)):
                reason = "unexpected exit status " + str(code)
            if reason is None and diagnostic not in output:
                reason = "missing expected diagnostic: " + diagnostic
            if reason is None and any(marker in output for marker in SIMULATION_MARKERS):
                reason = "reported simulation activity or a numerical pass"
            if reason is None and name != "help" and not (
                    output.startswith("Error:") or output.startswith("Invalid test configuration:")):
                reason = "missing parser error diagnostic"
        except (OSError, subprocess.SubprocessError) as error:
            reason, output = str(error), ""
        if reason:
            failures += 1
            print(f"{family} {name}: FAIL: {reason}")
            if output:
                print(output[-1024:].rstrip())
        else:
            print(f"{family} {name}: pass")
    print(f"{family}: {len(cases) - failures}/{len(cases)} CLI checks passed")
    return len(cases), failures


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wmma", type=executable, help="absolute path to generated tcu_unit")
    parser.add_argument("--fedp", type=executable, help="absolute path to generated tcu_fedp")
    parser.add_argument("--wmma-tfr-no-tf32", action="store_true",
                        help="add format-rejection checks for a TFR WMMA build with TF32 disabled")
    parser.add_argument("--fedp-no-tf32-fp8-mx", action="store_true",
                        help="add format-rejection checks for a TFR FEDP build with TF32, FP8 and MX disabled")
    args = parser.parse_args(argv)
    if args.wmma_tfr_no_tf32 and not args.wmma:
        parser.error("--wmma-tfr-no-tf32 requires --wmma")
    if args.fedp_no_tf32_fp8_mx and not args.fedp:
        parser.error("--fedp-no-tf32-fp8-mx requires --fedp")
    if not args.wmma and not args.fedp:
        parser.error("at least one of --wmma or --fedp is required")
    if os.name != "posix":
        parser.error("bounded tensor CLI checks require POSIX process groups")
    total = failures = 0
    with tempfile.TemporaryDirectory(prefix="tensor-cli-check-") as directory:
        for family, binary in (("WMMA", args.wmma), ("FEDP", args.fedp)):
            if binary is None:
                continue
            work = Path(directory) / family.lower()
            work.mkdir()
            count, failed = check_family(family, binary, work,
                                        wmma_tfr_no_tf32=args.wmma_tfr_no_tf32,
                                        fedp_no_tf32_fp8_mx=args.fedp_no_tf32_fp8_mx)
            total += count
            failures += failed
    print(f"Total: {total - failures}/{total} CLI checks passed; no numerical coverage claimed")
    return 1 if failures or total == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
