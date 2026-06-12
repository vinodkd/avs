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
