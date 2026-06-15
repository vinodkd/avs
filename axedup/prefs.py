"""User preferences — stored in the app_settings table (SQLite), one row per key.

These are UI defaults (what's pre-selected when a session page opens), not
pipeline configuration. Per-sport pipeline tuning lives in Profile rows /
DEFAULT_PROFILES. Stored in the DB so all app state lives in one place.
"""
import json

DEFAULTS: dict = {
    "default_sport": "moto",
    "default_grade": "natural",
    "default_scan_method": "proxy",   # 'jpg' = Quick (1fps), 'proxy' = Full
    "export_16_9": True,
    "export_9_16": False,
    "output_dir": "",                 # empty = config.OUTPUT_DIR
    # Boring-region detection (global; per-profile overrides only if usage
    # shows sports need different tolerances)
    "boring_threshold_pct": 35,       # dull = motion < pct% of sport motion_threshold
    "boring_min_s": 8.0,              # dull stretches shorter than this are pacing, not boredom
    "boring_gap_s": 2.0,              # blips above the line shorter than this don't break a region
    "dull_min_s": 3.0,                # unclaimed gaps shorter than this aren't worth a mark
    # Audio scoring
    "audio_spike_k": 3.0,             # spike = energy > median + k × MAD of the clip's own baseline
    "audio_boost": 1.25,              # score multiplier for marks containing an audio spike
}


def get_prefs() -> dict:
    from axedup.models.db import get_session
    from axedup.models.schema import AppSetting
    prefs = dict(DEFAULTS)
    with get_session() as db:
        for row in db.query(AppSetting).all():
            if row.key in DEFAULTS:
                try:
                    prefs[row.key] = json.loads(row.value)
                except json.JSONDecodeError:
                    pass
    return prefs


def save_prefs(values: dict) -> None:
    from axedup.models.db import get_session
    from axedup.models.schema import AppSetting
    with get_session() as db:
        for key, val in values.items():
            if key not in DEFAULTS:
                continue
            row = db.query(AppSetting).filter(AppSetting.key == key).first()
            if row is None:
                db.add(AppSetting(key=key, value=json.dumps(val)))
            else:
                row.value = json.dumps(val)
