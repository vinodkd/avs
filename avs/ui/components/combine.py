"""Combine-stage panel: grade swatch strip + combine progress watcher.

CombinePanel owns all combine-specific UI state so session.py doesn't have to.
It fires callbacks for the stage-table refs session.py still owns; those refs
migrate to engine/state in Step 7.
"""

from pathlib import Path
from typing import Callable

from nicegui import ui

from avs import config
from avs.ui import state
from avs.ui.components.progress import bar_html, dot_html
from avs.ui.state import StageState
from avs.utils import fmt_duration as _fmt

_GRADES     = ['punchy', 'cinematic', 'natural', 'warm', 'cool', 'vibrant']
_SOURCE_MAP = {'All accepted': None, 'Still-frame picks': 'jpg', 'Motion picks': 'proxy'}
_SWATCH_SELECTED = '#7a8fd8'
_SWATCH_DEFAULT  = '#2a2a2a'


class CombinePanel:
    """
    Owns: grade value, source selection, swatch strip, grade preview overlay,
    combining-lock flag, and the combine task watcher.

    session.py passes callbacks for the stage-table elements it still owns
    (dot, count, act-time, header-time, task-bar). Those callbacks go away in
    Step 7 when state moves to engine/state and the stage table subscribes directly.
    """

    def __init__(
        self,
        session_id: str,
        still_path: Path,
        mark_data: list,
        clip_ids: list,
        initial_grade: str = 'natural',
        on_grade_change: Callable[[str], None] | None = None,
    ) -> None:
        self.session_id       = session_id
        self._still_path      = still_path
        self._mark_data       = mark_data
        self._clip_ids        = clip_ids
        self._grade           = initial_grade
        self._source          = 'All accepted'
        self._combining       = False
        self._on_grade_change = on_grade_change

        self._swatch_row   = None
        self._swatch_built = False
        self._swatch_paths: dict[str, Path] = {}
        self._swatch_cards: dict            = {}
        self._grade_sel    = None
        self._grade_prev   = None
        self._player_tag_ref: list          = [None]
        self._tag_before_preview            = None

    # ── Build (called once per page load) ─────────────────────────────────────

    def build_in_action_bar(self) -> None:
        """Render the grade <select> inside whatever action-bar container is active."""
        sel = ui.select(
            options=_GRADES, value=self._grade, label='Grade',
        ).style('min-width:110px').props('dense outlined')
        sel.on_value_change(
            lambda e: (self._set_grade(e.value), self._show_grade_preview(e.value))
        )
        self._grade_sel = sel

    def build_swatch_row(self) -> None:
        """Render the swatch-row container (cards are populated lazily)."""
        row = ui.row().style(
            'flex-shrink:0;gap:0.55rem;padding:0.45rem 0.9rem;align-items:flex-start;'
            'background:#0f0f0f;border-bottom:1px solid #1a1a1a;flex-wrap:nowrap;overflow-x:auto'
        )
        row.set_visibility(False)
        self._swatch_row = row

    def build_grade_preview(self, player_tag_ref: list) -> None:
        """Render the full-size grade preview overlay in the player area."""
        self._player_tag_ref = player_tag_ref
        gp = ui.image('').props('fit=contain').style(
            'position:absolute;top:0;left:0;width:100%;height:100%;'
            'background:#000;z-index:6;cursor:pointer'
        ).tooltip('Click to return to the video')
        gp.on('click', lambda: self._hide_grade_preview())
        gp.set_visibility(False)
        self._grade_prev = gp

    # ── Public interface ───────────────────────────────────────────────────────

    @property
    def is_combining(self) -> bool:
        return self._combining

    @property
    def grade(self) -> str:
        return self._grade

    @property
    def source_filter(self) -> str | None:
        return _SOURCE_MAP.get(self._source)

    def show_swatches(self) -> None:
        if self._swatch_row:
            ui.timer(0.05, self._ensure_swatches, once=True)

    def hide_swatches(self) -> None:
        if self._swatch_row:
            self._swatch_row.set_visibility(False)
            self._hide_grade_preview()

    def set_grade_selector_visible(self, visible: bool) -> None:
        if self._grade_sel:
            self._grade_sel.set_visibility(visible)

    # ── Combine action ─────────────────────────────────────────────────────────

    def run_combine(
        self,
        on_hdr_time:    Callable[[str], None],
        on_task_bar:    Callable[[str], None],
        on_dot:         Callable[[str], None],
        on_count:       Callable[[str], None],
        on_act:         Callable[[float | None], None],
        on_nav:         Callable[[str], None],
        on_act_done:    Callable[[float], None] | None = None,
    ) -> None:
        """Start assembly and attach the progress watcher."""
        self._combining = True
        key = f'assemble_{self.session_id}'
        state.start_task(key)

        def _on_prog(done: int, total: int) -> None:
            state.update_task_progress(
                key,
                pct=int(done / total * 100) if total else None,
                message=f'{done} of {total} segments' if total else None,
            )

        from avs.engine import pipeline as engine
        engine.run_assemble(
            self.session_id,
            grade=self._grade,
            source_filter=self.source_filter,
            remove_mark_ids=[],
            swap_music=False,
            disable_overlay=False,
            on_progress=_on_prog,
            on_done=lambda err: state.finish_task(key, error=err),
        )
        on_dot('running')
        self._watch(on_hdr_time, on_task_bar, on_dot, on_count, on_act, on_nav, on_act_done)

    def reattach_watcher(
        self,
        on_hdr_time: Callable[[str], None],
        on_task_bar: Callable[[str], None],
        on_dot:      Callable[[str], None],
        on_count:    Callable[[str], None],
        on_act:      Callable[[float | None], None],
        on_nav:      Callable[[str], None],
        on_act_done: Callable[[float], None] | None = None,
    ) -> None:
        """Re-attach after a page reload if combine is still in progress."""
        t = state.get_task(f'assemble_{self.session_id}')
        if t and not t.done:
            self._combining = True
            self._watch(on_hdr_time, on_task_bar, on_dot, on_count, on_act, on_nav, on_act_done)

    # ── Internal ───────────────────────────────────────────────────────────────

    def _watch(
        self,
        on_hdr_time: Callable[[str], None],
        on_task_bar: Callable[[str], None],
        on_dot:      Callable[[str], None],
        on_count:    Callable[[str], None],
        on_act:      Callable[[float | None], None],
        on_nav:      Callable[[str], None],
        on_act_done: Callable[[float], None] | None = None,
    ) -> None:
        key = f'assemble_{self.session_id}'

        def _poll() -> None:
            t = state.get_task(key)
            if not t:
                return
            elapsed_s = t.elapsed or 0.0
            elapsed   = _fmt(elapsed_s)
            on_hdr_time(f'combining: {elapsed}')

            if t.error:
                self._combining = False
                ui.notify(f'Combine error: {t.error}', type='negative', timeout=0)
                on_dot('pending')
                on_count('error')
                on_act(None)
                on_task_bar('')
                _ct.active = False
                return

            if t.done:
                self._combining = False
                on_hdr_time(f'combined: {elapsed}')
                on_dot('done')
                (on_act_done or on_act)(elapsed_s)
                on_count('done')
                _ct.active = False
                on_nav(f'/session/{self.session_id}')
            else:
                pct_str = f'{t.pct}%' if t.pct is not None else '…'
                on_count(pct_str)
                on_act(elapsed_s)
                on_task_bar(bar_html(
                    StageState(status='running', pct=t.pct, message=t.message),
                    'Combining clips', 'combine',
                ))

        _ct = ui.timer(2.0, _poll)

    def _set_grade(self, grade: str) -> None:
        self._grade = grade
        if self._on_grade_change:
            self._on_grade_change(grade)
        for g, card in self._swatch_cards.items():
            card.style(replace=self._swatch_style(g == grade))

    def _swatch_style(self, selected: bool) -> str:
        bc = _SWATCH_SELECTED if selected else _SWATCH_DEFAULT
        return (f'border:2px solid {bc};border-radius:4px;overflow:hidden;cursor:pointer;'
                'flex-shrink:0;background:#161616;padding:0')

    def _show_grade_preview(self, grade: str) -> None:
        gp = self._grade_prev
        p  = self._swatch_paths.get(grade)
        if gp is None or p is None:
            return
        tag = self._player_tag_ref[0]
        cur = tag.text if tag else ''
        if not cur.startswith('Grade preview'):
            self._tag_before_preview = cur
        gp.set_source(f'/stills/{p.name}')
        gp.set_visibility(True)
        if tag:
            tag.set_text(f'Grade preview: {grade} — click image to return to the video')
        ui.run_javascript('var v=document.getElementById("main-player"); if(v) v.pause();')

    def _hide_grade_preview(self) -> None:
        gp = self._grade_prev
        if gp is None:
            return
        gp.set_visibility(False)
        tag = self._player_tag_ref[0]
        if tag and self._tag_before_preview is not None:
            tag.set_text(self._tag_before_preview)

    async def _ensure_swatches(self) -> None:
        if self._swatch_row is None:
            return
        if self._swatch_built:
            self._swatch_row.set_visibility(True)
            return
        src: Path | None = self._still_path if self._still_path.exists() else None
        if src is None:
            for mid, cid, *_ in self._mark_data:
                p = config.THUMB_DIR / cid / f'mark_{mid}.jpg'
                if p.exists():
                    src = p
                    break
        if src is None:
            return
        from nicegui import run as ng_run
        from avs.processing.assembly import render_grade_swatches
        try:
            paths = await ng_run.io_bound(render_grade_swatches, src, config.STILL_DIR, self.session_id)
        except Exception as exc:
            ui.notify(f'Grade preview failed: {exc}', type='warning')
            return
        self._swatch_built = True
        self._swatch_paths.update(paths)
        with self._swatch_row:
            for g in _GRADES:
                p = paths.get(g)
                if not p or not p.exists():
                    continue
                card = ui.element('div').style(self._swatch_style(g == self._grade))
                with card:
                    ui.image(f'/stills/{p.name}').style(
                        'width:104px;height:58px;display:block;object-fit:cover'
                    )
                    ui.label(g).style(
                        'font-size:0.62rem;color:#999;text-align:center;width:100%;padding:1px 0 2px'
                    )
                card.on('click', lambda g=g: (
                    self._set_grade(g),
                    self._grade_sel.set_value(g) if self._grade_sel else None,
                    self._show_grade_preview(g),
                ))
                self._swatch_cards[g] = card
        self._swatch_row.set_visibility(True)
