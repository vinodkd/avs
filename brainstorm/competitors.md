# AxEdUp: Existing Solutions & Competitive Landscape

## The Gap

No existing tool does all of:
- Cross-brand (GoPro + DJI + Insta360 in one workflow)
- Telemetry-aware clip selection (speed, altitude, G-force overlays from actual camera data)
- Sport-specific defaults and presets
- Conversational or context-aware brief input
- Multi-platform upload in one step

Each existing tool does some of these. None does all.

---

## Existing Tools

### GoPro Quik
- **What it does:** Auto-edit highlight reels from GoPro footage; beat-sync music; basic trim
- **Platforms:** iOS, Android, Mac
- **Gap:** GoPro-only; full features require GoPro Plus subscription (~$50/yr); limited telemetry overlay control; no multi-platform upload
- **Relevance:** The dominant incumbent for GoPro users; the UX benchmark to beat for simplicity

### DJI LightCut
- **What it does:** AI auto-edit from DJI footage; templates; scene-based assembly
- **Platforms:** iOS, Android
- **Gap:** DJI-only; no telemetry overlays; no multi-platform upload; less polished than Quik
- **Relevance:** DJI's answer to Quik; shows the category direction

### Insta360 App
- **What it does:** AI Editor, Deep Track subject tracking, 360 reframing, templates
- **Platforms:** iOS, Android
- **Gap:** Insta360-only; AI Editor uploads to Insta360 servers (privacy/bandwidth concern); flat camera support is secondary
- **Relevance:** Most technically ambitious of the three native apps; 360 reframing is a genuine differentiator

### CapCut
- **What it does:** General-purpose AI video editor; auto captions, templates, beat sync, AI effects
- **Platforms:** iOS, Android, Desktop, Web
- **Gap:** Not action-camera-specific; no telemetry support; no camera import (manual file selection only); TikTok-owned (data privacy concerns for some users)
- **Relevance:** The "good enough" competitor for social clip editing; fast-growing, free

### Antix (2014 — defunct as major player)
- **What it does:** Connected to GoPro over WiFi while shooting; used phone accelerometer to tag "exciting" moments in real-time; assembled highlight from tags
- **Platforms:** iOS, Android
- **Gap:** GoPro-only; required phone to be active during activity; motion-only detection had no contextual awareness; no longer actively developed
- **Relevance:** Closest prior art to the OpenCV/motion-analysis approach. Proved the concept; also showed the limits — motion ≠ interesting without context. Available on Product Hunt for reference.
- **Lesson:** Automated moment detection needs context (what sport, what kind of moment matters) to be useful, not just motion intensity.

### AidVid
- **What it does:** Fully cloud-based; upload footage → AI auto-edits → download finished video; no software to install; selectable duration (short/long)
- **Platforms:** Web (browser-only)
- **Gap:** Vacation video focus, not action sports; no telemetry; no sport-specific presets; upload pain for large 4K files; no multi-platform upload; low-res is free, higher quality paid
- **Relevance:** Closest to the "fully hosted" form factor option. Shows it's viable; also shows the bandwidth/cost constraint of cloud processing for large files.
- **Interesting detail:** Offers proxy-quality preview for free — suggests a proxy-first approach to reduce upload size.

### Gyroflow
- **What it does:** Advanced gyroscope-based video stabilization using camera IMU data; supports GoPro, DJI, Insta360, and many others
- **Platforms:** Mac, Windows, Linux
- **Gap:** Stabilization only — not an editor or publisher
- **Relevance:** Cross-brand telemetry/IMU parsing is a solved problem here; their sensor data support list is a useful reference for AxEdUp's ingest layer.

### Descript
- **What it does:** Transcript-based video editing — edit the transcript to edit the video; AI scene detection, filler word removal
- **Platforms:** Mac, Windows, Web
- **Gap:** Optimized for talking-head / podcast / interview content; poor fit for action footage with no speech
- **Relevance:** Shows that "review text, not timeline" paradigms work for a specific content type

### ReelMind / Revid.ai / Opus Clip
- **What they do:** AI highlight extractors and repurposing tools — take long-form content, extract short clips for social
- **Gap:** General-purpose content (YouTube videos, podcasts, livestreams); not action-sports specific; no camera import; no telemetry
- **Relevance:** The "long video → short social clips" AI workflow is proven and growing

---

## Summary Table

| Tool | Cross-brand | Telemetry | Sport presets | Auto-edit | Multi-upload | Local processing |
|---|---|---|---|---|---|---|
| GoPro Quik | No | Partial | No | Yes | No | Yes |
| DJI LightCut | No | No | No | Yes | No | Yes |
| Insta360 App | No | Partial | No | Yes | No | Partial |
| CapCut | Yes* | No | No | Partial | No | Yes |
| Antix | No | No | No | Yes | No | Yes |
| AidVid | Yes* | No | No | Yes | No | No (cloud) |
| Gyroflow | Yes | Yes | No | No | No | Yes |
| AxEdUp (target) | **Yes** | **Yes** | **Yes** | **Yes** | **Yes** | **Yes** |

*Accepts any video file but not camera-aware
