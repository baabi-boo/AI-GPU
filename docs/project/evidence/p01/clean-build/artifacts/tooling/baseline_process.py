# Licensed under the Apache License, Version 2.0.
"""Bounded, failure-preserving execution for a single baseline command."""

import hashlib
import math
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import threading
import time


GIB = 1024 ** 3
MIB = 1024 ** 2
TERMINATE_GRACE_SECONDS = 1.0
REAP_TIMEOUT_SECONDS = 2.0
DRAIN_GRACE_SECONDS = 0.25
LIMITATIONS = (
    "Resource limits are polled budgets, not hard filesystem or memory quotas.",
    "Process-group RSS can count shared pages more than once and excludes page cache.",
    "Reported peak RSS is the highest sample and may miss peaks between polls.",
    "No container/cgroup memory limit is inferred by this process monitor.",
    "Descendants that deliberately leave the process group are outside its containment.",
)


def _positive_number(value, name):
    try:
        valid = type(value) in (int, float) and math.isfinite(value) and value > 0
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(name + " must be finite and positive")


def _positive_bytes(value, name):
    if type(value) is not int or value <= 0:
        raise ValueError(name + " must be a positive integer")


def _validate_inputs(argv, cwd, env, log_path, resource_paths):
    if (not isinstance(argv, list) or not argv
            or any(not isinstance(item, str) or not item or "\0" in item for item in argv)):
        raise ValueError("argv must be a nonempty list of nonempty strings")
    if (not isinstance(env, dict) or any(
            not isinstance(key, str) or not key or "=" in key or "\0" in key
            or not isinstance(value, str) or "\0" in value for key, value in env.items())):
        raise ValueError("env must contain valid string names and values")
    if isinstance(resource_paths, (str, bytes, Path)):
        raise ValueError("resource_paths must be a sequence of paths")
    working = Path(cwd).resolve(strict=True)
    if not working.is_dir():
        raise ValueError("cwd must be a directory")
    requested = Path(os.path.abspath(log_path))
    parent = requested.parent.resolve(strict=True)
    if requested.parent != parent or not parent.is_dir():
        raise ValueError("log parent must be an existing directory without symlink traversal")
    if os.path.lexists(requested):
        raise ValueError("log_path already exists")
    paths = [working, parent]
    for item in resource_paths:
        paths.append(Path(item).resolve(strict=True))
    return working, requested, tuple(dict.fromkeys(paths))


def _disk_has_reserve(paths, minimum):
    return all(shutil.disk_usage(path).free >= minimum for path in paths)


def _group_snapshot(group):
    """Return readable Linux process-group RSS and non-zombie member count."""
    rss_pages = 0
    live = 0
    with os.scandir("/proc") as entries:
        for entry in entries:
            if not entry.name.isdigit():
                continue
            try:
                text = Path(entry.path, "stat").read_text(encoding="ascii")
                fields = text.rsplit(") ", 1)[1].split()
                if int(fields[2]) != group:
                    continue
                if fields[0] not in ("Z", "X"):
                    live += 1
                    rss_pages += max(0, int(fields[21]))
            except (FileNotFoundError, ProcessLookupError):
                continue
            except (OSError, UnicodeError, ValueError, IndexError) as error:
                try:
                    belongs = os.getpgid(int(entry.name)) == group
                except (ProcessLookupError, PermissionError):
                    belongs = False
                if belongs:
                    raise OSError("process-group memory unavailable") from error
    return rss_pages * os.sysconf("SC_PAGE_SIZE"), live


def _signal_group(group, number):
    try:
        os.killpg(group, number)
        return True
    except ProcessLookupError:
        return True
    except OSError:
        return False


def _stop_group(process, drain):
    signalled = _signal_group(process.pid, signal.SIGTERM)
    deadline = time.monotonic() + TERMINATE_GRACE_SECONDS
    while time.monotonic() < deadline:
        process.poll()
        drain()
        try:
            _, live = _group_snapshot(process.pid)
        except OSError:
            live = 1
        if not live and process.returncode is not None:
            break
        time.sleep(0.02)
    signalled = _signal_group(process.pid, signal.SIGKILL) and signalled
    try:
        process.wait(timeout=REAP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return False
    deadline = time.monotonic() + DRAIN_GRACE_SECONDS
    while time.monotonic() < deadline and not drain():
        time.sleep(0.01)
    try:
        _, live = _group_snapshot(process.pid)
    except OSError:
        return False
    return signalled and live == 0


def run_bounded(argv, cwd, env, log_path, *, timeout_seconds=1800,
                min_free_bytes=15 * GIB, max_log_bytes=16 * MIB,
                max_rss_bytes=6 * GIB, resource_paths=(), poll_seconds=0.1):
    """Execute one command, retain bounded combined output, and return its outcome."""
    _positive_number(timeout_seconds, "timeout_seconds")
    _positive_number(poll_seconds, "poll_seconds")
    for value, name in ((min_free_bytes, "min_free_bytes"),
                        (max_log_bytes, "max_log_bytes"),
                        (max_rss_bytes, "max_rss_bytes")):
        _positive_bytes(value, name)
    if os.name != "posix":
        raise ValueError("bounded execution requires POSIX process groups")
    working, logfile, paths = _validate_inputs(argv, cwd, env, log_path, resource_paths)
    started = time.monotonic()
    result = {"outcome": "blocked", "exit_code": None, "reason": None,
              "duration_seconds": 0.0, "log_sha256": None, "log_size_bytes": 0,
              "peak_rss_bytes": 0, "cleanup_complete": True,
              "limitations": list(LIMITATIONS)}
    try:
        if not _disk_has_reserve(paths, min_free_bytes):
            result["reason"] = "disk_reserve"
            return result
        _group_snapshot(os.getpgrp())
    except OSError:
        result["reason"] = "resource_inventory_unavailable"
        return result

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(logfile, flags, 0o600)
    except OSError:
        result["reason"] = "log_open_failed"
        result["duration_seconds"] = round(time.monotonic() - started, 6)
        return result
    digest = hashlib.sha256()
    process = None
    selector = selectors.DefaultSelector()
    original_handlers = {}
    interrupted = []
    pipe_eof = False
    pipe_ready = False
    log_error = False
    reason = None

    def on_signal(number, frame):
        interrupted.append(number)

    def drain():
        nonlocal pipe_eof, reason, log_error
        if process is None or pipe_eof or not pipe_ready:
            return pipe_eof
        for _ in range(16):
            try:
                chunk = os.read(process.stdout.fileno(), 65536)
            except BlockingIOError:
                break
            except OSError:
                reason = reason or "log_read_failed"
                pipe_eof = True
                selector.unregister(process.stdout)
                break
            if not chunk:
                pipe_eof = True
                selector.unregister(process.stdout)
                break
            remaining = max_log_bytes - result["log_size_bytes"]
            kept = chunk[:remaining]
            if kept and not log_error:
                try:
                    view = memoryview(kept)
                    while view:
                        count = os.write(descriptor, view)
                        if count <= 0:
                            raise OSError("log write made no progress")
                        digest.update(view[:count])
                        result["log_size_bytes"] += count
                        view = view[count:]
                except OSError:
                    log_error = True
                    reason = reason or "log_write_failed"
            if len(chunk) > remaining:
                reason = reason or "log_limit"
        return pipe_eof

    try:
        if threading.current_thread() is threading.main_thread():
            for number in (signal.SIGINT, signal.SIGTERM):
                original_handlers[number] = signal.getsignal(number)
                signal.signal(number, on_signal)
        try:
            process = subprocess.Popen(
                argv, cwd=working, env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                start_new_session=True, close_fds=True, bufsize=0,
            )
        except OSError:
            reason = "launch_failed"
        if process is not None:
            result["outcome"] = "fail"
            os.set_blocking(process.stdout.fileno(), False)
            selector.register(process.stdout, selectors.EVENT_READ)
            pipe_ready = True
            next_check = started
            exited_at = None
            while reason is None:
                now = time.monotonic()
                if interrupted:
                    reason = "interrupted_signal_" + str(interrupted[0])
                    break
                if now - started >= timeout_seconds:
                    reason = "timeout"
                    break
                if now >= next_check:
                    if not _disk_has_reserve(paths, min_free_bytes):
                        reason = "disk_reserve"
                        break
                    rss, live = _group_snapshot(process.pid)
                    result["peak_rss_bytes"] = max(result["peak_rss_bytes"], rss)
                    if rss > max_rss_bytes:
                        reason = "memory_limit"
                        break
                    next_check = now + poll_seconds
                process.poll()
                drain()
                if interrupted:
                    reason = reason or "interrupted_signal_" + str(interrupted[0])
                    break
                if process.returncode is not None:
                    if exited_at is None:
                        exited_at = now
                    _, live = _group_snapshot(process.pid)
                    if live:
                        reason = reason or "descendants_after_exit"
                        break
                    if pipe_eof:
                        break
                    if now - exited_at >= DRAIN_GRACE_SECONDS:
                        reason = reason or "output_pipe_not_closed"
                        break
                if reason is None:
                    selector.select(min(poll_seconds, max(0, timeout_seconds - (now - started))))
            if reason is not None:
                result["cleanup_complete"] = _stop_group(process, drain)
            else:
                process.wait(timeout=REAP_TIMEOUT_SECONDS)
                if interrupted:
                    reason = "interrupted_signal_" + str(interrupted[0])
                elif process.returncode != 0:
                    reason = "nonzero_exit"
            result["exit_code"] = process.returncode
    except (OSError, ValueError, subprocess.TimeoutExpired):
        reason = reason or "monitor_failed"
        if process is not None:
            result["outcome"] = "fail"
            result["cleanup_complete"] = _stop_group(process, drain)
            result["exit_code"] = process.returncode
    except KeyboardInterrupt:
        reason = reason or "interrupted"
        if process is not None:
            result["outcome"] = "fail"
            result["cleanup_complete"] = _stop_group(process, drain)
            result["exit_code"] = process.returncode
    finally:
        selector.close()
        if process is not None and process.stdout is not None:
            process.stdout.close()
        os.close(descriptor)
        for number, previous in original_handlers.items():
            signal.signal(number, previous)
        if interrupted:
            reason = reason or "interrupted_signal_" + str(interrupted[0])
        if process is not None:
            result["outcome"] = "pass" if reason is None else "fail"
        result["log_sha256"] = digest.hexdigest()
        result["duration_seconds"] = round(time.monotonic() - started, 6)
        result["reason"] = reason
    return result
