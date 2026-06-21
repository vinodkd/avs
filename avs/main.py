"""
Packaged app entry point. Used by PyInstaller and the avs-ui console script.
Runs DB migrations before starting the UI so the schema is always current.
"""
from __future__ import annotations

import sys


def _run_migrations() -> None:
    from pathlib import Path
    from alembic import command
    from alembic.config import Config

    if getattr(sys, "frozen", False):
        # Running inside a PyInstaller bundle
        bundle_dir = Path(sys._MEIPASS)  # type: ignore[attr-defined]
        migrations_dir = bundle_dir / "avs" / "models" / "migrations"
        cfg = Config()
        cfg.set_main_option("script_location", str(migrations_dir))
    else:
        # Dev mode: use alembic.ini from project root
        project_root = Path(__file__).resolve().parent.parent
        cfg = Config(str(project_root / "alembic.ini"))

    command.upgrade(cfg, "head")


def main() -> None:
    _run_migrations()

    from avs import __version__
    from avs.models.db import init_db
    init_db()

    from avs.updater import check_for_updates
    check_for_updates("vinodkd/avs", __version__)

    from avs.ui.app import start
    start()


if __name__ == "__main__":
    main()
