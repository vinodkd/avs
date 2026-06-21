#!/usr/bin/env python3
"""
Generate tests/fixtures/source.mp4 — a synthetic ~120s test video designed to
exercise every stage of the aVs pipeline with multiple examples of each signal type.

Timeline and expected detections are printed at the end and match README.md.

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
#   bg         : hex colour string            (hard scene cut when it changes)
#   label      : str                          (for README)
#
# Designed so the pipeline should find:
#   Motion peaks  : segments with motion='high' (~4 peaks)
#   Boring regions: segments with motion='low', duration >= 10s (~4 regions)
#   Audio spikes  : segments with audio='spike' (~4 spikes)
#   Scene cuts    : background colour changes (~4 hard transitions)

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

def _motion_filter(bg: str, motion: str, t_offset: float) -> str:
    """Build a lavfi filter string that produces the requested motion level."""
    if motion == "low":
        # Near-static: one very slowly drifting box
        return (
            f"color=c={bg}:size={W}x{H}:rate={FPS},"
            f"drawbox=x='560+10*sin(t*0.3)':y='280+8*sin(t*0.2)'"
            f":w=160:h=160:c=0x222233:t=fill"
        )
    if motion == "medium":
        # Two boxes moving at moderate speed
        return (
            f"color=c={bg}:size={W}x{H}:rate={FPS},"
            f"drawbox=x='mod(t*120+200,{W-160})':y='mod(t*90+100,{H-160})'"
            f":w=160:h=160:c=0x6688aa:t=fill,"
            f"drawbox=x='mod(-t*100+800,{W-120})':y='mod(t*110+300,{H-120})'"
            f":w=120:h=120:c=0xaa8866:t=fill"
        )
    # high: three boxes moving fast in different directions
    return (
        f"color=c={bg}:size={W}x{H}:rate={FPS},"
        f"drawbox=x='mod(t*480+50,{W-180})':y='mod(t*340+80,{H-180})'"
        f":w=180:h=180:c=0xff5555:t=fill,"
        f"drawbox=x='mod(-t*420+{W-200},{ W-140})':y='mod(t*390+200,{H-140})'"
        f":w=140:h=140:c=0x55ff55:t=fill,"
        f"drawbox=x='mod(t*460+400,{W-160})':y='mod(-t*370+{H-200},{H-160})'"
        f":w=160:h=160:c=0x5555ff:t=fill"
    )


def _audio_filter(audio: str) -> str:
    if audio == "spike":
        return f"sine=frequency=880:sample_rate={SR},volume=0.92"
    return f"sine=frequency=180:sample_rate={SR},volume=0.025"


# ── Build segments ─────────────────────────────────────────────────────────────

def build_segment(label: str, duration: float, motion: str, audio: str,
                  bg: str, dest: Path) -> None:
    vf = _motion_filter(bg, motion, 0.0)
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
    lines.append("**Scene cuts** (background colour transitions):")
    t = 0.0
    prev_bg = None
    cut_n = 0
    for label, dur, motion, audio, bg in segments:
        if bg != prev_bg and prev_bg is not None:
            cut_n += 1
            lines.append(f"  - Cut {cut_n}: ~{t:.0f}s  (into: {label})")
        prev_bg = bg
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
