"""Settings screen — UI preferences + per-sport profile editor.

Preferences are UI defaults stored in a JSON file (avs/prefs.py).
Profile editing creates/updates the sport's DB row; reset deletes the row so
the built-in defaults in presets/sports.py apply again (same fallback the
pipeline uses).
"""
from datetime import datetime

from nicegui import ui

from avs import config
from avs.models.db import get_session as db_session
from avs.models.schema import Profile
from avs.prefs import get_prefs, save_prefs
from avs.presets.sports import DEFAULT_PROFILES, display_name
from avs.processing.assembly import GRADE_FILTERS
from avs.ui.layout import sidebar

_GRADES   = list(GRADE_FILTERS.keys())
_METHODS  = {'jpg': 'Quick (1fps sample)', 'proxy': 'Full (all frames)'}
_DETECTORS = ['content', 'adaptive', 'threshold']
_ENERGIES  = ['high', 'medium', 'chill']

# Profile fields the pipeline reads today vs. stored-but-inert ones.
_ACTIVE_FIELDS = ['color_grade', 'motion_threshold',
                  'scene_detector', 'scene_threshold', 'scene_min_scene_len']
_INERT_FIELDS  = ['music_energy', 'min_clip_s', 'max_clip_s',
                  'target_duration_youtube_s', 'target_duration_short_s',
                  'speed_threshold_kmh',
                  'overlay_speed', 'overlay_altitude', 'overlay_gps_map']

_CARD = 'background:#1a1a1a;width:100%;max-width:680px;padding:1.1rem 1.3rem'
_H    = 'color:#ddd;font-size:1.0rem;font-weight:700;margin-bottom:0.6rem'
_SUB  = 'color:#666;font-size:0.72rem;margin-bottom:0.6rem'


def _profile_values(sport: str) -> tuple[dict, bool]:
    """Current values for *sport* and whether they come from a DB row."""
    with db_session() as db:
        p = db.query(Profile).filter(Profile.sport == sport).first()
        if p:
            return {f: getattr(p, f) for f in _ACTIVE_FIELDS + _INERT_FIELDS}, True
    return dict(DEFAULT_PROFILES.get(sport, {})), False


@ui.page('/settings')
def settings_page() -> None:
    ui.dark_mode().enable()

    drawer = ui.left_drawer(value=True).style('background:#1a1a1a;border-right:1px solid #222')
    drawer.props('breakpoint=0 width=180 mini-width=48')
    with drawer:
        sidebar('settings')

    sports = sorted(DEFAULT_PROFILES.keys(), key=lambda s: (s != 'moto', s))
    sport_opts = {s: display_name(s) for s in sports}
    prefs = get_prefs()

    with ui.column().style('padding:1.5rem 2rem;width:100%;min-height:100vh;'
                           'background:#111;align-items:center;gap:1rem'):
        ui.label('Settings').style('color:#eee;font-size:1.4rem;font-weight:700;'
                                   'width:100%;max-width:680px')

        # ── Preferences ───────────────────────────────────────────────────────
        with ui.card().style(_CARD):
            ui.label('Preferences').style(_H)
            ui.label('Defaults pre-selected when you start or edit a session.').style(_SUB)

            with ui.row().style('gap:1rem;flex-wrap:wrap;align-items:center'):
                _p_sport = ui.select(options=sport_opts, value=prefs['default_sport']
                                     if prefs['default_sport'] in sports else sports[0],
                                     label='Default sport').style('min-width:160px')
                _p_grade = ui.select(options=_GRADES, value=prefs['default_grade']
                                     if prefs['default_grade'] in _GRADES else 'natural',
                                     label='Default grade').style('min-width:130px')
                _p_method = ui.select(options=_METHODS, value=prefs['default_scan_method'],
                                      label='Default scan method').style('min-width:170px')
            with ui.row().style('gap:1rem;align-items:center;margin-top:0.4rem'):
                _p_a16 = ui.checkbox('Export 16:9', value=bool(prefs['export_16_9']))
                _p_a9  = ui.checkbox('Export 9:16', value=bool(prefs['export_9_16']))
                _p_out = ui.input(label='Output folder',
                                  placeholder=str(config.OUTPUT_DIR),
                                  value=prefs['output_dir']).style('min-width:280px;flex:1')

            ui.label('Boring-region detection').style(
                'color:#999;font-size:0.78rem;font-weight:600;margin-top:0.7rem'
            )
            ui.label('A span is skipped when motion stays below the threshold for the '
                     'minimum duration; brief blips within the gap tolerance are ignored. '
                     'Skipped spans can always be rescued in review.').style(_SUB)
            with ui.row().style('gap:1rem;flex-wrap:wrap;align-items:center'):
                _p_bpct = ui.number(label='Threshold (% of sport motion threshold)',
                                    min=5, max=95, step=5,
                                    value=prefs['boring_threshold_pct']).style('width:250px')
                _p_bmin = ui.number(label='Min duration (s)', min=2.0, step=1.0,
                                    value=prefs['boring_min_s']).style('width:140px')
                _p_bgap = ui.number(label='Gap tolerance (s)', min=0.0, step=0.5,
                                    value=prefs['boring_gap_s']).style('width:140px')
                _p_dmin = ui.number(label='Min dull gap (s)', min=1.0, step=1.0,
                                    value=prefs['dull_min_s']).style('width:140px').tooltip(
                    'Unclaimed footage between marks shorter than this is not shown as a dull section')

            ui.label('Audio scoring').style(
                'color:#999;font-size:0.78rem;font-weight:600;margin-top:0.7rem'
            )
            ui.label('Spikes are loud moments relative to each clip\'s own noise floor. '
                     'Marks containing a spike score higher; spikes outside any mark '
                     'become their own candidates (mic icon).').style(_SUB)
            with ui.row().style('gap:1rem;flex-wrap:wrap;align-items:center'):
                _p_ak = ui.number(label='Spike sensitivity (k)', min=1.0, max=10.0, step=0.5,
                                  value=prefs['audio_spike_k']).style('width:160px').tooltip(
                    'Lower = more spikes detected. Spike when energy > median + k × MAD')
                _p_ab = ui.number(label='Score boost (×)', min=1.0, max=3.0, step=0.05,
                                  value=prefs['audio_boost']).style('width:140px')

            def _save_prefs() -> None:
                save_prefs({
                    'default_sport': _p_sport.value,
                    'default_grade': _p_grade.value,
                    'default_scan_method': _p_method.value,
                    'export_16_9': _p_a16.value,
                    'export_9_16': _p_a9.value,
                    'output_dir': (_p_out.value or '').strip(),
                    'boring_threshold_pct': int(_p_bpct.value or 35),
                    'boring_min_s': float(_p_bmin.value or 8.0),
                    'boring_gap_s': float(_p_bgap.value or 2.0),
                    'dull_min_s': float(_p_dmin.value or 3.0),
                    'audio_spike_k': float(_p_ak.value or 3.0),
                    'audio_boost': float(_p_ab.value or 1.25),
                })
                ui.notify('Preferences saved', type='positive')

            ui.button('Save preferences', on_click=_save_prefs).props(
                'color=positive size=sm'
            ).style('margin-top:0.6rem')

        # ── Profile editor ────────────────────────────────────────────────────
        with ui.card().style(_CARD):
            ui.label('Sport profiles').style(_H)
            ui.label('Per-sport pipeline tuning. Saving stores a customised copy; '
                     'Reset returns the sport to the built-in defaults.').style(_SUB)

            _sel = ui.select(options=sport_opts, value=sports[0], label='Sport').style(
                'min-width:180px'
            )
            _state = ui.label('').style('color:#666;font-size:0.7rem;margin-bottom:0.4rem')

            ui.label('Used by the pipeline').style(
                'color:#999;font-size:0.78rem;font-weight:600;margin-top:0.5rem'
            )
            with ui.row().style('gap:1rem;flex-wrap:wrap;align-items:center'):
                _f_grade = ui.select(options=_GRADES, label='Color grade').style('min-width:130px')
                _f_motion = ui.number(label='Motion threshold', min=0.0, max=1.0,
                                      step=0.05, format='%.2f').style('width:140px')
            with ui.row().style('gap:1rem;flex-wrap:wrap;align-items:center'):
                _f_det = ui.select(options=_DETECTORS, label='Scene detector').style('min-width:130px')
                _f_sthr = ui.number(label='Scene threshold', min=0.0, step=0.5).style('width:140px')
                _f_slen = ui.number(label='Min scene length (frames)', min=1, step=1).style('width:180px')

            ui.label('Stored but not used by the pipeline yet').style(
                'color:#555;font-size:0.78rem;font-weight:600;margin-top:0.8rem'
            )
            with ui.row().style('gap:1rem;flex-wrap:wrap;align-items:center'):
                _f_energy = ui.select(options=_ENERGIES, label='Music energy').style('min-width:120px')
                _f_minc = ui.number(label='Min clip (s)', min=0.5, step=0.5).style('width:110px')
                _f_maxc = ui.number(label='Max clip (s)', min=1.0, step=0.5).style('width:110px')
                _f_speed = ui.number(label='Speed threshold (km/h)', min=0, step=5).style('width:160px')
            with ui.row().style('gap:1rem;flex-wrap:wrap;align-items:center'):
                _f_yt  = ui.number(label='Target YouTube (s)', min=30, step=30).style('width:150px')
                _f_sh  = ui.number(label='Target short (s)', min=10, step=5).style('width:140px')
                _f_osp = ui.checkbox('Speed overlay')
                _f_oal = ui.checkbox('Altitude overlay')
                _f_ogp = ui.checkbox('GPS map overlay')

            _fields = {
                'color_grade': _f_grade, 'motion_threshold': _f_motion,
                'scene_detector': _f_det, 'scene_threshold': _f_sthr,
                'scene_min_scene_len': _f_slen,
                'music_energy': _f_energy, 'min_clip_s': _f_minc, 'max_clip_s': _f_maxc,
                'target_duration_youtube_s': _f_yt, 'target_duration_short_s': _f_sh,
                'speed_threshold_kmh': _f_speed,
                'overlay_speed': _f_osp, 'overlay_altitude': _f_oal, 'overlay_gps_map': _f_ogp,
            }

            def _load(sport: str) -> None:
                vals, customised = _profile_values(sport)
                for name, el in _fields.items():
                    el.set_value(vals.get(name))
                _state.set_text(
                    'Customised — stored in the database'
                    if customised else 'Using built-in defaults'
                )

            def _save_profile() -> None:
                sport = _sel.value
                with db_session() as db:
                    p = db.query(Profile).filter(Profile.sport == sport).first()
                    if p is None:
                        p = Profile(sport=sport, **DEFAULT_PROFILES.get(sport, {}))
                        db.add(p)
                    for name, el in _fields.items():
                        v = el.value
                        if isinstance(el, ui.number) and v is not None:
                            v = float(v) if name.endswith(('_s', '_kmh', 'threshold')) \
                                and name != 'scene_min_scene_len' else v
                        if name in ('scene_min_scene_len',
                                    'target_duration_youtube_s', 'target_duration_short_s') \
                                and v is not None:
                            v = int(v)
                        setattr(p, name, v)
                    p.updated_at = datetime.utcnow()
                _load(sport)
                ui.notify(f'{display_name(sport)} profile saved', type='positive')

            def _reset_profile() -> None:
                sport = _sel.value
                with db_session() as db:
                    p = db.query(Profile).filter(Profile.sport == sport).first()
                    if p:
                        db.delete(p)
                _load(sport)
                ui.notify(f'{display_name(sport)} reset to built-in defaults', type='info')

            _sel.on_value_change(lambda e: _load(e.value))
            _load(_sel.value)

            with ui.row().style('gap:0.6rem;margin-top:0.8rem'):
                ui.button('Save profile', on_click=_save_profile).props('color=positive size=sm')
                ui.button('Reset to defaults', on_click=_reset_profile).props(
                    'flat size=sm color=orange'
                )
