"""
Non-blocking update check against GitHub Releases API.
Call check_for_updates() at startup; read get_update_available() from the UI.
"""
from __future__ import annotations

import threading
from typing import Optional

_latest_version: Optional[str] = None
_check_done: bool = False


def _do_check(repo: str, current: str) -> None:
    global _latest_version, _check_done
    try:
        import json
        import urllib.request

        url = f"https://api.github.com/repos/{repo}/releases/latest"
        req = urllib.request.Request(url, headers={"User-Agent": f"avs/{current}"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read())
        tag = data.get("tag_name", "").lstrip("v")
        if tag and tag != current:
            _latest_version = tag
    except Exception:
        pass
    finally:
        _check_done = True


def check_for_updates(repo: str, current: str) -> None:
    """Fire-and-forget background update check. Safe to call at app startup."""
    threading.Thread(target=_do_check, args=(repo, current), daemon=True).start()


def get_update_available() -> Optional[str]:
    """Returns the latest version string if a newer release exists, else None.
    Returns None also if the check hasn't finished yet."""
    return _latest_version if _check_done else None
