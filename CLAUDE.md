# aVs — Claude Code Instructions

## Project Status: Active Development (post-prototype)

The prototype phase is complete. The full pipeline runs end-to-end: ingest → proxy → scan → peaks → pick → combine → export. The NiceGUI desktop UI is the primary interface. The CLI exists but is behind the UI in capability and needs refactoring to match the current backend.

Priorities and pending work live in **`docs/backlog.md`** — that file is the source
of truth (see its "Current priorities" section). Keep it updated as work lands;
do not duplicate the list here.

## Project Overview

aVs is a desktop tool for editing and uploading action camera footage. It reads video files from an SD card or local folder, analyzes them using computer vision and telemetry data, guides the user through a review workflow, assembles a finished video using sport-specific presets, and exports it ready for upload.

See `/brainstorm/` for full design history and decision rationale.
See `/docs/design.md` for current architecture and build plan.

## Commit Policy

**Never commit until tested.** Write the change, test it against real data, wait for confirmation it works, then commit. No speculative commits.

For assembly changes: human approval of the preview is sufficient. Export does not need to be tested before committing — it is a separate step with no new pipeline logic.

## Keeping Docs in Sync

**This is mandatory.** Whenever you add, change, or remove a feature, data model field, CLI command, processing step, or dependency, update the relevant doc in `/docs/` before considering the task done.

- `/docs/requirements.md` — update when scope changes: features added, deferred, or removed
- `/docs/design.md` — update when architecture, tech choices, data models, pipeline steps, or CLI interface change

If a code change contradicts what a doc says, the code is the truth — fix the doc to match.
Do not defer doc updates to a separate task. Update them in the same pass as the code change.

## Project Structure

```
/docs/              — requirements and design docs (keep current)
/brainstorm/        — decision history and research (read-only reference)
/avs/            — Python package
  /processing/      — ingest, telemetry, analysis, assembly, export
  /models/          — SQLAlchemy ORM models
  /presets/         — sport profiles, LUT files, bundled music
  /ui/              — NiceGUI screens (Phase 2)
  /llm/             — Ollama integration (Phase 2)
  cli.py            — CLI entry point
  config.py         — paths, constants, settings
/tests/             — pytest tests for processing pipeline
CLAUDE.md           — this file
run.py              — convenience entry point
```

## Tech Stack

- **Language:** Python 3.11+
- **CLI:** `click` or `typer`
- **UI:** NiceGUI — Python-native, browser-rendered, zero JavaScript (primary interface)
- **Video processing:** ffmpeg-python + imageio-ffmpeg (bundles FFmpeg binary)
- **Scene detection:** PySceneDetect
- **Motion analysis:** OpenCV (cv2)
- **Database:** SQLite via SQLAlchemy + Alembic
- **LLM (future):** Ollama (separate install) + `ollama` Python client
- **Packaging:** PyInstaller — AppImage (Linux), Setup.exe (Windows), dmg (macOS) via GitHub Releases on `v*` tags
- **No GPU assumed** — all processing runs on CPU only
- **No FastAPI, no React** — decided against; too heavy

## Coding Conventions

- Use `pathlib.Path` everywhere — never string path concatenation
- All video analysis runs on 480p proxy files, not originals
- FFmpeg calls go through `ffmpeg-python` — no manual subprocess string construction
- Database access via SQLAlchemy ORM — no raw SQL strings
- One processing stage per module in `/avs/processing/`
- Original source files are never modified

## What's Out of Scope (do not build unless requirements change)

- FastAPI or any HTTP server
- React or any JavaScript frontend
- Camera WiFi / BLE integration
- Direct platform upload (YouTube, Instagram, etc.) — deferred to post-v1, not permanently excluded
- 360 footage (aVs360)
- Mobile / Android / iOS builds
- Cloud processing or hosted backend
- Multi-day trip session grouping
- Windows or Mac builds (Linux dev first; cross-platform by design for later)
