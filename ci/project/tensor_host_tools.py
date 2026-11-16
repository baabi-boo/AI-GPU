# SPDX-License-Identifier: Apache-2.0
"""Bounded compilation and execution of small tensor-oracle host tests."""

from pathlib import Path
from uuid import uuid4

from baseline_process import GIB, MIB, run_bounded


def run_host_command(argv, *, cwd, env, timeout, max_output_bytes=MIB):
    working = Path(cwd).resolve(strict=True)
    log = working / ("host-command-" + uuid4().hex + ".log")
    result = run_bounded(
        argv, working, env, log, timeout_seconds=timeout,
        min_free_bytes=GIB, max_log_bytes=max_output_bytes,
        max_rss_bytes=GIB, resource_paths=(working,),
    )
    output = log.read_text(encoding="utf-8") if log.exists() else ""
    if result["outcome"] != "pass" or not result["cleanup_complete"]:
        raise AssertionError(
            "Host command failed: " + str(result["reason"])
            + " (exit " + str(result["exit_code"]) + ")\n" + output[-4096:]
        )
    return output
