#!/usr/bin/env python3
"""
Generate tests/fixtures/source.mp4 — a synthetic ~120s test video designed to
exercise every stage of the aVs pipeline with multiple examples of each signal type.

Motion is produced by a scrolling sinusoidal texture (all pixels move → realistic
optical flow values). Scene cuts are created by alternating between solid-colour
LOW segments and textured HIGH/MEDIUM segments.

Timeline and expected detections are printed at the end.

Usage:
    python3 tests/fixtures/create_fixture.py
"""
import subprocess
import sys
import tempfile
from pathlib import Path

FFMPEG = None  # resolved at runtime

OUT = Path(__file__).parent / "source.mp4"
W, H, FPS, SR = 1280, 720, 30, 44100

# ── Segment definitions ───────────────────────────────────────────────────────
#
# Each segment is a dict:
#   duration   : float  seconds
#   motion     : 'high' | 'medium' | 'low'   (optical flow intensity)
#   audio      : 'spike' | 'quiet'            (RMS level)
#   bg         : hex colour string            (used for solid LOW segments;
#                  scene cuts occur at LOW↔HIGH transitions)
#   label      : str
#
# Expected optical flow intensities (at 480p proxy, OPTICAL_FLOW_SAMPLE_INTERVAL=0.5s):
#   high   ~ 0.69   (above all sport motion_threshold values: 0.40–0.70)
#   medium ~ 0.28   (below all thresholds — boring-region candidate)
#   low    ~ 0.00   (solid colour, no motion — boring/dull candidate)
#
# Scene cuts are all LOW↔HIGH transitions (solid→texture or texture→solid).

SEGMENTS = [
    # label                     dur   motion    audio    bg
    ("intro – low motion",       6,   "low",   "quiet",  "0x0d0d1a"),
    ("boring 1",                14,   "low",   "quiet",  "0x0d0d1a"),  # boring region 1
    ("scene A – motion peak 1", 6,   "high",  "quiet",  "0x1a0a0a"),  # scene cut + peak
    ("audio spike 1",            2,   "high",  "spike",  "0x1a0a0a"),  # spike 1
    ("motion peak 2",            5,   "high",  "quiet",  "0x1a0a0a"),  # peak 2 (same scene)
    ("boring 2",                13,   "low",   "quiet",  "0x0a1a0a"),  # scene cut + boring 2
    ("scene B – motion peak 3",  6,   "high",  "quiet",  "0x1a0a1a"),  # scene cut + peak 3
    ("audio spike 2",            2,   "high",  "spike",  "0x1a0a1a"),  # spike 2
    ("medium motion",            8,   "medium","quiet",  "0x1a0a1a"),
    ("boring 3",                14,   "low",   "quiet",  "0x0a1a1a"),  # scene cut + boring 3
    ("scene C – motion peak 4",  6,   "high",  "quiet",  "0x1a100a"),  # scene cut + peak 4
    ("audio spike 3",            2,   "medium","spike",  "0x1a100a"),  # spike 3
    ("medium motion",            7,   "medium","quiet",  "0x1a100a"),
    ("boring 4",                12,   "low",   "quiet",  "0x111111"),  # scene cut + boring 4
    ("scene D – motion peak 5",  5,   "high",  "quiet",  "0x0a0a2a"),  # scene cut + peak 5
    ("motion peak 6",            5,   "high",  "quiet",  "0x0a0a2a"),  # peak 6
    ("audio spike 4",            2,   "high",  "spike",  "0x0a0a2a"),  # spike 4
    ("outro – low motion",       5,   "low",   "quiet",  "0x0d0d1a"),
]

# ── Video filter builders ─────────────────────────────────────────────────────

def _motion_filter(bg: str, motion: str) -> str:
    """Return a lavfi filtergraph string for the requested motion level.

    LOW  → solid colour (no motion), ~0.00 intensity.
    HIGH → scrolling sinusoidal texture, ~0.69 intensity at 480p proxy.
    MED  → same texture, slower scroll, ~0.28 intensity.

    The scroll is vertical (v=) so all pixels move; optical flow sees realistic
    mean magnitudes across the whole frame.  Scroll speed is chosen to keep the
    per-sample displacement (0.5 s × 30 fps = 15 frames) well below the pattern
    half-period (~21 px at proxy), avoiding aliasing.
    """
    if motion == "low":
        return f"color=c={bg}:size={W}x{H}:rate={FPS}"

    speed = "0.002" if motion == "high" else "0.0008"
    # Sinusoidal texture on a neutral base — period ~63 px at source (~42 px at proxy).
    # Displacement per sample at proxy: 14 px (high) or 6 px (medium) — below half-period.
    return (
        f"color=c=0x111111:size={W}x{H}:rate={FPS},"
        f"geq=r='128+100*sin(X*0.1)*sin(Y*0.1)'"
        f":g='128+100*cos(X*0.1+Y*0.1)':b='64',"
        f"scroll=v={speed}"
    )


def _audio_filter(audio: str) -> str:
    if audio == "spike":
        return f"sine=frequency=880:sample_rate={SR},volume=0.92"
    return f"sine=frequency=180:sample_rate={SR},volume=0.025"


# ── Build segments ─────────────────────────────────────────────────────────────

def build_segment(label: str, duration: float, motion: str, audio: str,
                  bg: str, dest: Path) -> None:
    vf = _motion_filter(bg, motion)
    af = _audio_filter(audio)
    cmd = [
        FFMPEG, "-y",
        "-f", "lavfi", "-i", vf,
        "-f", "lavfi", "-i", af,
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        str(dest),
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        print(f"ERROR building segment '{label}':", file=sys.stderr)
        print(result.stderr.decode()[-800:], file=sys.stderr)
        sys.exit(1)
    print(f"  [{duration:5.1f}s  {motion:6s}  {audio:5s}]  {label}")


# ── Concatenate ───────────────────────────────────────────────────────────────

def concat(parts: list[Path], dest: Path) -> None:
    list_file = dest.parent / "_concat_list.txt"
    list_file.write_text("\n".join(f"file '{p}'" for p in parts))
    cmd = [
        FFMPEG, "-y",
        "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-c", "copy",
        str(dest),
    ]
    result = subprocess.run(cmd, capture_output=True)
    list_file.unlink(missing_ok=True)
    if result.returncode != 0:
        print("ERROR concatenating:", file=sys.stderr)
        print(result.stderr.decode()[-800:], file=sys.stderr)
        sys.exit(1)


# ── README ────────────────────────────────────────────────────────────────────

def write_readme(segments: list[tuple]) -> None:
    lines = [
        "# Test fixture: source.mp4",
        "",
        "Synthetic ~120s video for pipeline testing. Generated by `create_fixture.py`.",
        "",
        "## Motion encoding",
        "",
        "| Level  | Filter                        | Approx intensity at 480p proxy |",
        "|--------|-------------------------------|--------------------------------|",
        "| high   | sinusoidal texture, v=0.002   | ~0.69                          |",
        "| medium | sinusoidal texture, v=0.0008  | ~0.28                          |",
        "| low    | solid colour (no motion)      | ~0.00                          |",
        "",
        "Scene cuts occur at all LOW↔HIGH/MEDIUM transitions.",
        "",
        "## Timeline",
        "",
        "| Start | End | Duration | Motion | Audio | Label |",
        "|-------|-----|----------|--------|-------|-------|",
    ]
    t = 0.0
    for label, dur, motion, audio, bg in segments:
        lines.append(
            f"| {t:5.1f}s | {t+dur:5.1f}s | {dur:4.1f}s "
            f"| {motion:6s} | {audio:5s} | {label} |"
        )
        t += dur

    lines += [
        "",
        "## Expected pipeline detections",
        "",
        "These are approximate — exact timestamps depend on threshold settings.",
        "",
        "**Motion peaks** (high-motion sections, default sport thresholds):",
    ]
    t = 0.0
    peak_n = 0
    for label, dur, motion, audio, bg in segments:
        if motion == "high":
            peak_n += 1
            lines.append(f"  - Peak {peak_n}: ~{t:.0f}s–{t+dur:.0f}s  ({label})")
        t += dur

    lines.append("")
    lines.append("**Boring regions** (low-motion, ≥10s):")
    t = 0.0
    bore_n = 0
    for label, dur, motion, audio, bg in segments:
        if motion == "low" and dur >= 10:
            bore_n += 1
            lines.append(f"  - Boring {bore_n}: ~{t:.0f}s–{t+dur:.0f}s  ({label})")
        t += dur

    lines.append("")
    lines.append("**Audio spikes** (high-amplitude bursts):")
    t = 0.0
    spike_n = 0
    for label, dur, motion, audio, bg in segments:
        if audio == "spike":
            spike_n += 1
            lines.append(f"  - Spike {spike_n}: ~{t:.0f}s  ({label})")
        t += dur

    lines.append("")
    lines.append("**Scene cuts** (LOW↔HIGH transitions):")
    t = 0.0
    prev_motion = None
    cut_n = 0
    for label, dur, motion, audio, bg in segments:
        if prev_motion is not None and motion != prev_motion:
            cut_n += 1
            lines.append(f"  - Cut {cut_n}: ~{t:.0f}s  (into: {label})")
        prev_motion = motion
        t += dur

    Path(__file__).parent.joinpath("README.md").write_text("\n".join(lines) + "\n")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    global FFMPEG
    try:
        import imageio_ffmpeg
        FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        import shutil
        FFMPEG = shutil.which("ffmpeg")
    if not FFMPEG:
        print("ffmpeg not found — install imageio-ffmpeg or system ffmpeg", file=sys.stderr)
        sys.exit(1)

    total = sum(d for _, d, *_ in SEGMENTS)
    print(f"Generating {len(SEGMENTS)} segments → {total:.0f}s total → {OUT}")

    with tempfile.TemporaryDirectory() as tmp:
        parts = []
        for i, (label, dur, motion, audio, bg) in enumerate(SEGMENTS):
            part = Path(tmp) / f"seg_{i:02d}.mp4"
            build_segment(label, dur, motion, audio, bg, part)
            parts.append(part)

        print(f"\nConcatenating → {OUT} …")
        OUT.parent.mkdir(parents=True, exist_ok=True)
        concat(parts, OUT)

    write_readme(SEGMENTS)
    print(f"\nDone. {OUT.stat().st_size // 1024} KB")
    print(f"README written to {OUT.parent / 'README.md'}")


if __name__ == "__main__":
    main()
