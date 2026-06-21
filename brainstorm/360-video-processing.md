# 360° Video Processing in aVs

Researched 2026-06-20.

## The user problem

Insta360 (and similar) cameras can shoot flat and 360° video on the same card in the same session.
The user shouldn't need a separate app to handle the 360° clips — they're part of the same footage,
same SD card, same editing session. aVs should accept both and produce a flat output regardless.

## What's on the SD card

Insta360 360° cameras write `.insv` files. These are an MP4-derived container with:

- **Dual-fisheye video stream** — two hemispherical images (one per lens), side-by-side or stacked.
  Raw, unstitched. Must be stitched to equirectangular before any useful processing.
- **Telemetry track** — gyroscope (angular velocity, per-frame), accelerometer, GPS on some models.
  This is the same camera-embedded telemetry documented in `insta360-telemetry.md`.
- **`.lrv`** — low-res proxy version of the same dual-fisheye content; on some camera models this
  is where the telemetry track actually lives (not the main file).

FFmpeg can open `.insv` in most cases (container is close enough to MP4). Stitching cannot be
skipped — the dual-fisheye stream is unusable as-is for analysis or output.

## Stitching: two quality levels

### Phase 1 — FFmpeg approximate stitch

FFmpeg's `v360` filter has a `dfisheye` (dual fisheye) input mode that handles the basic geometry
in a single pass:

```
ffmpeg -i input.insv -vf "v360=dfisheye:equirect:id_fov=190" equirect_proxy.mp4
```

Uses approximate FOV parameters (not per-camera calibration). Produces a visible seam at the
stitch line and some distortion near the poles. Acceptable for:
- Proxy generation (analysis doesn't care about a 2-pixel seam)
- Stylized effects like tiny planet or barrel roll (which naturally disguise or hide the seam)

Ship this first. See what the output looks like before building Phase 2.

### Phase 2 — Accurate stitch via Gyroflow lens profiles

Gyroflow ships ~200+ per-camera calibration profiles (MIT licensed, JSON). These contain OpenCV
fisheye model parameters:

```json
"fisheye_params": {
  "fx": 1823.4, "fy": 1823.4,   // focal length in pixels (intrinsic matrix)
  "cx": 1920.0, "cy": 1920.0,   // optical center
  "k1": -0.12, "k2": 0.08, "k3": -0.02, "k4": 0.001  // distortion coefficients
}
```

**These do not map to FFmpeg v360 parameters.** FFmpeg assumes ideal projections; the k-values
are distortion polynomial corrections for real lenses that FFmpeg has no equivalent for.
Accurate stitching requires:

1. Load Gyroflow profile → extract intrinsic matrix + k-values
2. `cv2.fisheye.undistortImage()` per frame → corrected fisheye frames
3. Stitch the two corrected frames → equirectangular
4. Hand equirectangular to FFmpeg for effects

OpenCV does the lens correction; FFmpeg only ever sees clean equirectangular.

## Gyro data: two uses

### 1. Moment detection (highlight finding)

The gyro track provides angular velocity at every frame. Large angular velocity = rapid rotation =
interesting moment: a fall, sharp turn, trick, impact. Reading this requires no video decode at all
— just parse the telemetry track and threshold the magnitude.

Maps naturally onto the existing peak-detection model: gyro magnitude spikes become a scoring
signal alongside optical flow and audio, fed into `peaks.py`.

Advantage over optical flow for 360°: much faster, and more reliable for body-mounted cameras
where the camera shake IS the interesting moment (a crash, a sharp drop).

The gyro axis also carries signal — not just when, but what kind of event:

| Gyro signal | Motion type | Likely event |
|---|---|---|
| High yaw, sustained | Spinning / panning | Turn, looking around |
| High pitch | Steep drop or climb | Jump, descent |
| High roll | Flip / tumble | Crash, trick |
| All axes, impulsive | Impact | Crash, impact |
| Low magnitude, sustained | Calm glide | Transition, establishing |

### 2. POV / framing for output

After integrating angular velocity → orientation quaternions, you know where the camera was
pointing at every frame relative to its starting orientation. This enables:

**Stabilization (gyro alone)**
Counter-rotate the virtual camera each frame to cancel shake. Output looks gimbal-smooth.

**Forward-lock (gyro + mount orientation)**
If the camera was mounted facing forward (helmet, chest, pole), the integrated orientation
gives you "direction of travel" per frame. Virtual camera follows the athlete's heading.
Covers the common case for most action sports.

**Auto-reframe toward action (gyro + optical flow)**
Detect where in the sphere the visually interesting content is. Requires optical flow on sphere
regions, not just gyro. Phase 2 capability.

### Summary: what gyro gives you

| Goal | Signal | Phase |
|---|---|---|
| When is something interesting | Gyro magnitude | 1 |
| What type of event | Gyro axis breakdown | 1 |
| Stable, smooth output | Gyro integration + remap | 1 |
| Forward-facing crop (common case) | Gyro + known mount orientation | 1 |
| Track action anywhere in sphere | Optical flow on sphere regions | 2 |

## Effects pipeline

The gyro doesn't just detect moments — it can inform which effect to apply at each moment,
giving the edit creative intelligence without requiring user decisions per clip.

| Gyro signature | Natural effect |
|---|---|
| High yaw, sustained | Barrel roll or slow pan |
| High pitch | Downward or upward crop |
| High roll | Roll effect |
| All axes impulsive | Freeze → slow-mo forward crop |
| Low magnitude | Tiny planet (establishing shot) |

All effects are FFmpeg `v360` filter operations on the equirectangular. No additional rendering
pipeline required.

**Available FFmpeg effects (examples):**

```
# 360° look-around sweep
v360=e:rectilinear:yaw='360*t/duration':pitch=0:v_fov=90

# Barrel roll
v360=e:rectilinear:yaw=0:pitch=0:roll='360*t/duration'

# Tiny planet (stereographic, looking down)
v360=e:stereographic:pitch=-90

# Wormhole/tunnel (stereographic, looking up)
v360=e:stereographic:pitch=90

# Static forward crop (with stabilization applied upstream)
v360=e:rectilinear:yaw=0:pitch=0:v_fov=90
```

## Full pipeline

```
.insv on SD card
  ├─ telemetry track (no video decode)
  │    └─ gyro magnitude  →  highlight peaks (WHEN)
  │    └─ gyro axes       →  event type     (WHICH effect)
  │    └─ gyro integration → orientation   →  forward-lock framing
  │
  └─ video stream
       └─ Phase 1: FFmpeg dfisheye → equirectangular proxy (approximate, fast)
       └─ Phase 2: OpenCV + Gyroflow profile → equirectangular proxy (accurate)
            └─ existing aVs analysis (audio scan, optical flow on equirectangular)

Combine step:
  equirectangular clip + gyro-selected effect → FFmpeg v360 → flat output segment
  → existing assembly pipeline unchanged
```

## Python implementation

No Rust required. No new app required.

| Piece | Tool | Notes |
|---|---|---|
| Phase 1 stitching | FFmpeg `v360=dfisheye:equirect` | One-liner, approximate |
| Gyro reading from .insv | ffprobe + telemetry track parsing | Medium effort; community prior art |
| Gyro integration + smoothing | `scipy.spatial.transform.Rotation` | Straightforward math |
| Phase 2 lens profiles | Gyroflow repo (MIT, JSON) | Data only, extract once |
| Phase 2 lens undistortion | `cv2.fisheye.undistortImage()`, `cv2.remap()` | OpenCV, CPU |
| Effects rendering | FFmpeg `v360` filter expressions | Already in use for flat output |

## Scope and phasing

**Phase 1**
- Detect `.insv` at ingest; mark clip as `source_format=360`
- Parse gyro telemetry track from `.insv` (or `.lrv` sidecar where applicable)
- Approximate stitch: FFmpeg `dfisheye` → equirectangular proxy
- Gyro magnitude as scoring signal in `peaks.py`
- Gyro axis analysis to select effect type per highlight clip
- Gyro integration for forward-lock framing
- Effect presets applied via FFmpeg `v360` at Combine step
- Settings: mount orientation offset (front/chest/top/side)

**Phase 2**
- Accurate stitch via Gyroflow lens profiles + OpenCV undistortion
- User-selectable POV direction (yaw/pitch) at review time
- Auto-reframe toward motion (optical flow on sphere regions)
- Support for `.gyro` sidecar files

**Not in scope**
- Full equirectangular output (VR/360 players)
- Multi-camera stitching
- Spatial audio

## Open questions

- Which Insta360 models write telemetry to `.lrv` vs main file? Needs real hardware testing.
- `.insv` telemetry parsing: coverage of community Python parsers varies by camera generation.
  Fallback: shell to `ffprobe` and parse the raw metadata stream.
- Gyroflow lens profile JSON schema is undocumented — needs reverse-engineering or a shim.
- Does FFmpeg's `dfisheye` mode handle the Insta360 dual-stream correctly, or does the `.insv`
  stream layout need special handling? Verify with real footage before committing to Phase 1.
