"""
Audio energy analysis: RMS loudness series from proxy audio.

Decodes the proxy's audio track to mono PCM via FFmpeg and computes RMS
loudness per window, written to telemetry rows as audio_energy. Spike
detection is relative to each clip's own noise floor (median + k x MAD),
because the baseline (wind, engine drone) varies wildly between clips —
absolute loudness is meaningless.
"""
import subprocess

import numpy as np

from avs import config
from avs.models.db import get_session
from avs.models.schema import Clip, TelemetryPoint

WINDOW_S = 1.0
_RATE = 8000  # plenty for loudness; keeps the pipe small

_NOOP = lambda *_: None


def run_audio_scan(session_id: str, on_event=None) -> int:
    """Compute and store audio_energy for every clip with a proxy.
    Returns the number of windows written."""
    _notify = on_event or _NOOP
    with get_session() as db:
        clips = (
            db.query(Clip)
            .filter(Clip.session_id == session_id)
            .order_by(Clip.clip_order)
            .all()
        )
    total = 0
    for clip in clips:
        proxy = config.PROXY_DIR / f"{clip.id}.mp4"
        if not proxy.exists():
            continue
        _notify(clip.id, 'audio', 'running', clip.filename, None, None)
        series = _rms_series(proxy)
        _write_series(clip.id, series)
        _notify(clip.id, 'audio', 'done', f"{clip.filename}: {len(series)} window(s)", None, None)
        total += len(series)
    return total


def _rms_series(proxy_path) -> list[tuple[float, float]]:
    """[(timestamp_s, rms 0..1)] per WINDOW_S of the proxy's audio."""
    cmd = [config.FFMPEG_BIN, "-i", str(proxy_path),
           "-vn", "-ac", "1", "-ar", str(_RATE), "-f", "s16le", "pipe:1"]
    res = subprocess.run(cmd, capture_output=True, timeout=600)
    raw = res.stdout
    if len(raw) < 2:
        return []
    arr = np.frombuffer(raw[: len(raw) // 2 * 2], dtype=np.int16).astype(np.float32) / 32768.0
    n = int(_RATE * WINDOW_S)
    m = len(arr) // n
    if m == 0:
        return []
    win = arr[: m * n].reshape(m, n)
    rms = np.sqrt(np.mean(win * win, axis=1))
    return [(i * WINDOW_S, float(r)) for i, r in enumerate(rms)]


def _write_series(clip_id: str, series: list[tuple[float, float]]) -> None:
    """Attach energies to existing telemetry rows by nearest second; create
    rows where none exist (e.g. quick-scan sessions with sparse samples)."""
    with get_session() as db:
        rows = (
            db.query(TelemetryPoint)
            .filter(TelemetryPoint.clip_id == clip_id)
            .order_by(TelemetryPoint.timestamp_s)
            .all()
        )
        by_sec = {}
        for r in rows:
            by_sec.setdefault(round(r.timestamp_s), r)
        for t, e in series:
            row = by_sec.get(round(t))
            if row is not None:
                row.audio_energy = e
            else:
                nr = TelemetryPoint(clip_id=clip_id, timestamp_s=float(t), audio_energy=e)
                db.add(nr)
                by_sec[round(t)] = nr


def clip_audio_spikes(clip_id: str, k: float = 3.0) -> list[float]:
    """Timestamps where audio energy exceeds the clip's noise floor by
    k robust standard deviations (median + k x 1.4826 x MAD)."""
    with get_session() as db:
        rows = (
            db.query(TelemetryPoint)
            .filter(TelemetryPoint.clip_id == clip_id)
            .filter(TelemetryPoint.audio_energy.isnot(None))
            .order_by(TelemetryPoint.timestamp_s)
            .all()
        )
        pairs = [(r.timestamp_s, r.audio_energy) for r in rows]
    if len(pairs) < 5:
        return []
    vals = np.array([v for _, v in pairs])
    med = float(np.median(vals))
    mad = float(np.median(np.abs(vals - med)))
    if mad <= 1e-6:
        return []
    thr = med + k * 1.4826 * mad
    return [t for t, v in pairs if v > thr]
