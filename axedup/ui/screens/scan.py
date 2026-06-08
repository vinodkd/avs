import time

from nicegui import ui

from axedup.models.db import get_session as db_session
from axedup.models.schema import Clip, Mark, Session, SessionStatus
from axedup.ui import state
from axedup.ui.state import StageState
from axedup.ui.layout import sidebar

_STAGES = ['proxy', 'thumbnails', 'scenes', 'motion']

# Layman labels shown in the badge
_STAGE_LABEL = {
    'proxy':      'Creating working copy',
    'thumbnails': 'Taking snapshots',
    'scenes':     'Finding scene cuts',
    'motion':     'Finding highlights',
}

_BADGE_BASE = (
    'font-size:0.75rem;background:#1e1e1e;'
    'padding:0.15rem 0.5rem;border-radius:3px;display:inline-block;'
    'white-space:nowrap'
)


def _stage_html(s: StageState, label: str, stage: str) -> str:
    """Return an HTML badge for a stage's current state, with stage-appropriate detail."""
    if s.status in ('done', 'skipped'):
        return f'<span style="color:#5a9a5a;{_BADGE_BASE}">✓ {label}</span>'
    if s.status == 'running':
        if stage == 'proxy' and s.pct is not None:
            detail = f'  {s.pct}%'
        elif stage == 'motion' and s.completed is not None and s.total:
            detail = f'  {s.completed:,} / {s.total:,}'
        elif s.pct is not None:
            detail = f'  {s.pct}%'
        else:
            detail = ''
        return f'<span style="color:#f0a040;{_BADGE_BASE}">▶ {label}{detail}</span>'
    return f'<span style="color:#555;{_BADGE_BASE}">· {label}</span>'


def _fmt_elapsed(secs: float) -> str:
    m, s = divmod(int(secs), 60)
    return f'{m}m {s:02d}s' if m else f'{s}s'


@ui.page('/scan/{session_id}')
def scan_page(session_id: str) -> None:
    ui.dark_mode().enable()

    with db_session() as db:
        session = db.query(Session).filter(Session.id == session_id).first()
        if not session:
            ui.label('Session not found.').style('color: #e57373; padding: 2rem')
            return
        status = session.status
        clips = (
            db.query(Clip)
            .filter(Clip.session_id == session_id)
            .order_by(Clip.clip_order)
            .all()
        )
        clip_ids = [c.id for c in clips]
        clip_info = [(c.id, c.filename) for c in clips]
        total_duration_s = sum(c.duration_s or 0 for c in clips)

    task = state.get_task(session_id)

    drawer = ui.left_drawer(value=True).style('background: #1a1a1a; border-right: 1px solid #222')
    drawer.props('breakpoint=0 width=180 mini-width=48')
    with drawer:
        sidebar('scan', session_id, status)

    with ui.column().style('padding: 2rem; width: 100%; min-height: 100vh; background: #111'):
        ui.label('Scanning Footage').style(
            'color: #eee; font-size: 1.4rem; font-weight: 700; margin-bottom: 0.25rem'
        )

        # ── Completed summary view (navigating back after analysis finished) ──
        if status == SessionStatus.READY and task is None:
            with db_session() as db:
                mark_count = db.query(Mark).filter(Mark.clip_id.in_(clip_ids)).count()
            ui.label('Analysis complete').style(
                'color: #5a9a5a; font-size: 1rem; margin-bottom: 0.5rem'
            )
            ui.label(
                f'{len(clip_ids)} clip{"s" if len(clip_ids) != 1 else ""}  ·  '
                f'{mark_count} candidate mark{"s" if mark_count != 1 else ""} found'
            ).style('color: #777; font-size: 0.9rem; margin-bottom: 1.5rem')
            ui.button(
                'Continue to Pick →',
                on_click=lambda: ui.navigate.to(f'/pick/{session_id}'),
            ).props('color=positive')
            return

        # ── Interrupted state (stuck in ANALYZING with no live task) ──
        if status == SessionStatus.ANALYZING and task is None:
            ui.label('Analysis was interrupted.').style(
                'color: #e57373; font-size: 0.9rem; margin-bottom: 0.5rem'
            )
            ui.label(
                'Go back to Load to re-import and re-analyse this session.'
            ).style('color: #666; font-size: 0.85rem; margin-bottom: 1rem')
            ui.button('← Back to Home', on_click=lambda: ui.navigate.to('/')).props(
                'flat color=positive'
            )
            return

        # ── Active progress view ──
        est_s = max(60, int(total_duration_s * 1.0))
        est_str = _fmt_elapsed(est_s)
        start_time = time.time()

        headline = ui.label('Analysis running…').style(
            'color: #777; margin-bottom: 0.15rem; font-size: 0.9rem'
        )
        timing_lbl = ui.label(f'Estimated: ~{est_str}  ·  Elapsed: 0s').style(
            'color: #555; font-size: 0.78rem; margin-bottom: 1.25rem'
        )

        # Per-clip rows — filename then four stage badges (wrap on narrow screens)
        clip_stage_els: dict[str, dict[str, ui.html]] = {}

        for clip_id, filename in clip_info:
            with ui.row().style(
                'align-items: center; gap: 0.4rem; margin-bottom: 0.5rem; flex-wrap: wrap'
            ):
                ui.label(filename).style(
                    'color: #aaa; font-size: 0.82rem; font-family: monospace; '
                    'min-width: 200px; max-width: 280px; '
                    'overflow: hidden; text-overflow: ellipsis; white-space: nowrap'
                )
                stage_els: dict[str, ui.html] = {}
                for stage in _STAGES:
                    el = ui.html(
                        _stage_html(StageState(status='pending'), _STAGE_LABEL[stage], stage),
                        sanitize=False,
                        tag='span',
                    )
                    stage_els[stage] = el
                clip_stage_els[clip_id] = stage_els

        # Placeholder for the Continue button — shown after task completes
        done_container = ui.element('div').style('margin-top: 1.5rem')

        def poll() -> None:
            task = state.get_task(session_id)
            progress = state.get_clip_progress(session_id)

            # Update every badge
            for cid, stage_els in clip_stage_els.items():
                clip_prog = progress.get(cid, {})
                for stage, el in stage_els.items():
                    s = clip_prog.get(stage, StageState(status='pending'))
                    el.set_content(
                        _stage_html(s, _STAGE_LABEL[stage], stage)
                    )

            elapsed = time.time() - start_time
            timing_lbl.set_text(
                f'Estimated: ~{est_str}  ·  Elapsed: {_fmt_elapsed(elapsed)}'
            )

            if task and task.error:
                headline.set_text(f'Error: {task.error}')
                timer.active = False
                return

            with db_session() as db:
                sess = db.query(Session).filter(Session.id == session_id).first()
                if not sess:
                    return
                mark_count = db.query(Mark).filter(Mark.clip_id.in_(clip_ids)).count()

            done_clips = sum(
                1 for cid in clip_ids
                if all(
                    progress.get(cid, {}).get(s, StageState()).status in ('done', 'skipped')
                    for s in _STAGES
                )
            )
            total = len(clip_ids)

            if task is not None and task.done and not task.error:
                actual_str = _fmt_elapsed(time.time() - start_time)
                headline.set_text(
                    f'Done — {mark_count} mark{"s" if mark_count != 1 else ""} found  ·  '
                    f'Estimated {est_str}, took {actual_str}'
                )
                timing_lbl.set_text('')
                timer.active = False
                # Show Continue button — user decides when to proceed
                done_container.clear()
                with done_container:
                    ui.button(
                        f'Continue to Pick  ({mark_count} marks) →',
                        on_click=lambda: ui.navigate.to(f'/pick/{session_id}'),
                    ).props('color=positive')
            else:
                headline.set_text(
                    f'{done_clips}/{total} clips analysed  ·  {mark_count} marks so far…'
                )

        timer = ui.timer(0.5, poll)
