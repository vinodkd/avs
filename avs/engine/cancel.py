import threading


class CancelToken:
    def __init__(self) -> None:
        self._cancel = threading.Event()
        self._done = threading.Event()
        self.error: str | None = None

    def cancel(self) -> None:
        self._cancel.set()

    def is_cancelled(self) -> bool:
        return self._cancel.is_set()

    def wait(self) -> str | None:
        """Block until the operation finishes. Returns the error string or None."""
        self._done.wait()
        return self.error

    # Called by engine internals only
    def _finish(self, error: str | None = None) -> None:
        self.error = error
        self._done.set()
