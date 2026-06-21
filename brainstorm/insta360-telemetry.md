# Insta360 Telemetry — Research Notes

Researched 2026-06-20.

## Two distinct data sources

### 1. Camera-embedded telemetry (on SD card, in the .insv / .mp4 file)

Stored as a metadata track inside the video container. Available without the
app. Includes:

- GPS (latitude, longitude, altitude, speed, bearing)
- Accelerometer (X, Y, Z)
- Gyroscope (X, Y, Z)
- Shutter speed

Extractable with third-party tools. [Telemetry Extractor for Insta360](https://goprotelemetryextractor.com/tools-for-insta360)
exports to GPX, CSV, JSON, MGJSON, KML, GeoJSON. This is the practical target
for aVs telemetry support.

Note: some Insta360 models write the telemetry track to the LRV (low-res
proxy) file rather than the main video — in those cases the LRV must be
imported alongside the main file to get the data.

### 2. GPS Activity Stats (app-only, phone memory / Insta360 cloud)

A separate feature in the Insta360 mobile app. The user starts a "Stats"
recording session in the app before shooting; the app uses the phone's GPS
(not the camera's) and records a performance overlay.

**Key facts:**
- The app explicitly does NOT send this data to the camera. It never reaches
  the SD card.
- Data is stored locally on the phone, or synced to Insta360's cloud if the
  user has an Insta360+ subscription.
- Cannot be exported to Insta360 Studio (their own desktop app). No official
  export path exists.
- No community tools found for extracting it.

**Theoretical extraction (Android):**
- Rooted device: access `/data/data/com.insta360.*/databases/` directly and
  pull the SQLite file. No one has publicly documented the schema.
- Unrooted device with USB debugging: only possible if the app allows
  `adb backup` or is marked debuggable (production apps almost never are).

## Implications for aVs

- Camera-embedded telemetry is the right target. It travels with the file,
  requires no special device access, and has an extraction path.
- App GPS Activity Stats are effectively locked away for unrooted devices.
  Not worth pursuing unless Insta360 adds an export API.
- Insta360's telemetry format is distinct from GoPro GPMF and DJI SRT —
  a separate parser will be needed. Candidate library: Telemetry Extractor
  (commercial) or community Python tools.
