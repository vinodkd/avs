"""Scan progress strip: per-clip proxy/scan bars + single task-bar slot.

The strip sits above the player during analysis (proxy, scan, peaks) and is
reused as a one-line progress bar during combine/export via set_task_bar().
ScanProgressStrip owns strip_ref, bar_refs, and task_bar_ref so session.py
doesn't have to carry those as raw mutable lists.
"""

from nicegui import ui

from avs.ui import state
from avs.ui.components.progress import bar_html
from avs.ui.state import StageState

PROXY_STAGES = ['proxy']
SCAN_STAGES  = ['scenes', 'motion', 'audio']
STAGE_LABEL  = {
    'proxy':  'Working copy',
    'scenes': 'Scene cuts',
    'motion': 'Optical flow',
    'audio':  'Audio energy',
}


class ScanProgressStrip:
    """
    Owns the progress strip above the player.

    session.py builds it once, then calls update_bars() from _poll and
    set_task_bar() from the combine/export watchers.
    """

    def __init__(self, session_id: str, clip_info: list, detect_method_ref: list) -> None:
        self.session_id        = session_id
        self._clip_info        = clip_info          # [(cid, fname, dur_s), ...]
        self._detect_method_ref = detect_method_ref  # [str] — shared ref
        self._strip    = None
        self._task_bar = None
        self._bar_refs: dict[str, dict] = {}        # {cid: {stage: ui.html}}

    # ── Build (called once during page construction) ───────────────────────────

    def build(self, proxy_running: bool, scan_running: bool, highlights_running: bool) -> None:
        """Render the strip into the current NiceGUI context."""
        bg_running = proxy_running or scan_running or highlights_running
        strip = ui.element('div').style(
            'flex-shrink:0;background:#0d0d0d;border-bottom:1px solid #1a1a1a;'
            'padding:0.6rem 1rem 0.2rem'
        )
        self._strip = strip
        with strip:
            if bg_running:
                method = self._detect_method_ref[0]
                prog   = state.get_clip_progress(self.session_id)
                stages = PROXY_STAGES if proxy_running else SCAN_STAGES
                for cid, _fname, _ in self._clip_info:
                    self._bar_refs.setdefault(cid, {})
                    cp = prog.get(cid, {})
                    for stage in stages:
                        s  = cp.get(stage, StageState())
                        el = ui.html(bar_html(s, STAGE_LABEL[stage], stage, method),
                                     sanitize=False)
                        self._bar_refs[cid][stage] = el
            self._task_bar = ui.html('', sanitize=False)
        if not bg_running:
            strip.set_visibility(False)

    # ── Public interface ───────────────────────────────────────────────────────

    def set_visible(self, visible: bool) -> None:
        if self._strip:
            self._strip.set_visibility(visible)

    def set_task_bar(self, html: str) -> None:
        """Set the task-bar slot (combine/export one-liner). Also shows/hides strip."""
        if self._task_bar:
            self._task_bar.set_content(html)
        if self._strip:
            self._strip.set_visibility(bool(html))

    def ensure_bars_for_scan(self, method: str) -> None:
        """Create scan bars if the page loaded before the scan was started."""
        if not self._strip or self._bar_refs:
            return
        with self._strip:
            for cid, _fname, _ in self._clip_info:
                self._bar_refs.setdefault(cid, {})
                for stage in SCAN_STAGES:
                    el = ui.html(bar_html(StageState(), STAGE_LABEL[stage], stage, method),
                                 sanitize=False)
                    self._bar_refs[cid][stage] = el
        self._strip.set_visibility(True)

    def update_bars(self, prog: dict, stages: list) -> None:
        """Refresh bar HTML from clip progress dict. Called from _poll."""
        method = self._detect_method_ref[0]
        for cid, stage_map in self._bar_refs.items():
            cp = prog.get(cid, {})
            for stage, el in stage_map.items():
                if stage in stages:
                    el.set_content(bar_html(cp.get(stage, StageState()), STAGE_LABEL[stage],
                                            stage, method))
