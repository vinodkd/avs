import os
import shutil
from pathlib import Path

import imageio_ffmpeg

APP_NAME = "axedup"

# --- Directories ---

# Where finished export files are written (user-visible)
OUTPUT_DIR = Path(os.environ.get("AXEDUP_OUTPUT_DIR", Path.home() / "Videos" / "AxEdUp"))

# App data: database lives here
DATA_DIR = Path(os.environ.get("AXEDUP_DATA_DIR", Path.home() / ".local" / "share" / APP_NAME))

# Cache: proxies, thumbnails, previews, temp segments (safe to delete)
CACHE_DIR = Path(os.environ.get("AXEDUP_CACHE_DIR", Path.home() / ".cache" / APP_NAME))

PROXY_DIR       = CACHE_DIR / "proxies"
THUMB_DIR       = CACHE_DIR / "thumbnails"
PREVIEW_DIR     = CACHE_DIR / "previews"
SEGMENT_DIR     = CACHE_DIR / "segments"
REVIEW_DIR      = CACHE_DIR / "review"
JPEG_FRAMES_DIR = CACHE_DIR / "jpeg_frames"

DB_PATH = DATA_DIR / f"{APP_NAME}.db"

# --- FFmpeg ---

# imageio-ffmpeg ships a pre-built ffmpeg binary; no system install required
FFMPEG_BIN = imageio_ffmpeg.get_ffmpeg_exe()

# ffprobe must be available on the system (sudo apt install ffmpeg on Ubuntu)
FFPROBE_BIN = shutil.which("ffprobe") or "ffprobe"

# --- Analysis defaults ---

PROXY_HEIGHT    = 480           # px; all CV work runs on this resolution
THUMB_INTERVAL  = 5             # seconds between thumbnails
SCENE_THRESHOLD = 20            # PySceneDetect ContentDetector threshold (10=sensitive, 27=coarse)
OPTICAL_FLOW_SAMPLE_INTERVAL = 0.5  # seconds between flow samples

# --- Ollama ---

OLLAMA_HOST  = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "phi3.5")


def ensure_dirs() -> None:
    """Create all app directories if they don't exist. Call at startup."""
    for d in (OUTPUT_DIR, DATA_DIR, PROXY_DIR, THUMB_DIR, PREVIEW_DIR, SEGMENT_DIR, REVIEW_DIR, JPEG_FRAMES_DIR):
        d.mkdir(parents=True, exist_ok=True)
