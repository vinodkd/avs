"""Shared mutable state for background pipeline tasks and per-clip progress."""
import threading
import time
from dataclasses import dataclass, field


@dataclass
class TaskState:
    done: bool = False
    error: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    pct: int | None = None        # 0-100 task-level progress, if reported
    message: str | None = None    # phase label e.g. current export aspect

    @property
    def elapsed(self) -> float | None:
        """Seconds since start; frozen at finish once done."""
        if self.started_at is None:
            return None
        end = self.finished_at if self.finished_at is not None else time.time()
        return end - self.started_at


@dataclass
class StageState:
    status: str = 'pending'       # pending | running | done | skipped
    pct: int | None = None        # 0-100, derived from completed/total when available
    completed: int | None = None  # raw numerator (frames, seconds, percent-points)
    total: int | None = None      # raw denominator
    message: str | None = None    # phase label e.g. "Extracting" / "Comparing"


# {session_id: {clip_id: {stage: StageState}}}
_tasks: dict[str, TaskState] = {}
_progress: dict[str, dict[str, dict[str, StageState]]] = {}
_lock = threading.Lock()


def start_task(key: str) -> None:
    with _lock:
        _tasks[key] = TaskState(started_at=time.time())


def finish_task(key: str, error: str | None = None) -> None:
    with _lock:
        if key in _tasks:
            _tasks[key].done = True
            _tasks[key].error = error
            _tasks[key].finished_at = time.time()


def update_task_progress(key: str, pct: int | None = None, message: str | None = None) -> None:
    with _lock:
        if key in _tasks:
            if pct is not None:
                _tasks[key].pct = pct
            if message is not None:
                _tasks[key].message = message


def get_task(key: str) -> TaskState | None:
    with _lock:
        t = _tasks.get(key)
        return TaskState(done=t.done, error=t.error,
                         started_at=t.started_at, finished_at=t.finished_at,
                         pct=t.pct, message=t.message) if t else None


def update_clip_stage(
    session_id: str,
    clip_id: str,
    stage: str,
    status: str,
    *,
    pct: int | None = None,
    completed: int | None = None,
    total: int | None = None,
    message: str | None = None,
) -> None:
    with _lock:
        if session_id not in _progress:
            _progress[session_id] = {}
        if clip_id not in _progress[session_id]:
            _progress[session_id][clip_id] = {}
        _progress[session_id][clip_id][stage] = StageState(
            status=status,
            pct=pct,
            completed=completed,
            total=total,
            message=message,
        )


def get_clip_progress(session_id: str) -> dict[str, dict[str, StageState]]:
    with _lock:
        session = _progress.get(session_id, {})
        return {
            cid: {
                stage: StageState(status=s.status, pct=s.pct, completed=s.completed, total=s.total, message=s.message)
                for stage, s in stages.items()
            }
            for cid, stages in session.items()
        }
