# Licensed under the Apache License, Version 2.0.
"""Cancellation handling for orchestration outside bounded command execution."""

from contextlib import contextmanager
import signal
import threading


@contextmanager
def terminate_as_interrupt():
    """Unwind on SIGTERM while preserving enclosing and nested signal handlers."""
    if threading.current_thread() is not threading.main_thread():
        raise ValueError("SIGTERM interruption handling requires the main thread")

    def interrupt(number, frame):
        raise KeyboardInterrupt

    previous = signal.getsignal(signal.SIGTERM)
    try:
        signal.signal(signal.SIGTERM, interrupt)
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)
