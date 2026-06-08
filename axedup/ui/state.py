"""Shared mutable state for background pipeline tasks and per-clip progress."""
import threading
from dataclasses import dataclass, field


@dataclass
class TaskState:
    done: bool = False
    error: str | None = None


@dataclass
class StageState:
    status: str = 'pending'       # pending | running | done | skipped
    pct: int | None = None        # 0-100, derived from completed/total when available
    completed: int | None = None  # raw numerator (frames, seconds, percent-points)
    total: int | None = None      # raw denominator


# {session_id: {clip_id: {stage: StageState}}}
_tasks: dict[str, TaskState] = {}
_progress: dict[str, dict[str, dict[str, StageState]]] = {}
_lock = threading.Lock()


def start_task(key: str) -> None:
    with _lock:
        _tasks[key] = TaskState()


def finish_task(key: str, error: str | None = None) -> None:
    with _lock:
        if key in _tasks:
            _tasks[key].done = True
            _tasks[key].error = error


def get_task(key: str) -> TaskState | None:
    with _lock:
        t = _tasks.get(key)
        return TaskState(done=t.done, error=t.error) if t else None


def update_clip_stage(
    session_id: str,
    clip_id: str,
    stage: str,
    status: str,
    *,
    pct: int | None = None,
    completed: int | None = None,
    total: int | None = None,
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
        )


def get_clip_progress(session_id: str) -> dict[str, dict[str, StageState]]:
    with _lock:
        session = _progress.get(session_id, {})
        return {
            cid: {
                stage: StageState(status=s.status, pct=s.pct, completed=s.completed, total=s.total)
                for stage, s in stages.items()
            }
            for cid, stages in session.items()
        }
