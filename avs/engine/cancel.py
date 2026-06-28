import threading
from typing import Callable


class CancelledError(Exception):
    """Raised inside a processing loop when cancellation is detected."""


class CancelToken:
    def __init__(self) -> None:
        self._cancel = threading.Event()
        self._done = threading.Event()
        self._cleanups: list[Callable] = []
        self.error: str | None = None

    def cancel(self) -> None:
        self._cancel.set()
        for fn in self._cleanups:
            try:
                fn()
            except Exception:
                pass

    def is_cancelled(self) -> bool:
        return self._cancel.is_set()

    def register_cleanup(self, fn: Callable) -> None:
        """Register a function called immediately when cancel() fires.
        Used to terminate FFmpeg subprocesses that won't stop on their own."""
        self._cleanups.append(fn)

    def unregister_cleanup(self, fn: Callable) -> None:
        self._cleanups = [c for c in self._cleanups if c is not fn]

    def wait(self) -> str | None:
        """Block until the operation finishes. Returns the error string or None."""
        self._done.wait()
        return self.error

    # Called by engine internals only
    def _finish(self, error: str | None = None) -> None:
        self.error = error
        self._done.set()
