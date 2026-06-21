# aVs: Action Camera Editing & Upload — Brainstorm Overview

## The Problem

Action camera enthusiasts shoot a lot of footage across GoPro, DJI, and Insta360 devices. The current workflow is painful:

- Files come off cameras in proprietary or non-standard formats
- Each brand has its own app with its own UX quirks
- Desktop editing tools (Premiere, DaVinci, Final Cut) are overkill for quick social clips
- The native apps are siloed — no cross-brand workflow
- Uploading to multiple platforms (YouTube, Instagram, TikTok, Strava, etc.) requires repetitive manual steps
- Telemetry overlays (speed, GPS, G-force, altitude) require separate tools or subscriptions

## The User

Action sports enthusiasts — mountain bikers, surfers, skiers, skydivers, motorcyclists, divers, runners. Their behavior:

- Shoot in bursts or full sessions (10 min–2 hr of raw footage)
- Want a shareable clip within an hour of finishing the activity
- Often edit on a phone while still at the location
- Care about telemetry overlays as social proof ("look how fast I was going")
- Post to Instagram Reels, TikTok, YouTube Shorts, and Strava simultaneously
- Don't want to learn video editing — they want presets, auto-cut, and music sync
- Are often mid-activity with sweaty/gloved hands — UI must be low-friction

## Right Form Factor

**Mobile-first, not mobile-only.** The phone is the editing device at the trailhead or beach. Desktop is for the serious 10-minute recap video, not the Instagram clip.

Key form factor principles:
- Onboarding in under 2 minutes
- Import from camera (WiFi direct, USB-C, SD card via dongle) or cloud sync
- One-tap templates: "30-second highlight", "1-minute recap", "full run with telemetry"
- Preset packs per sport (MTB, surf, skydive, ski) — color grade + music + overlay style
- Telemetry displayed automatically if GPS/sensor data is present
- Batch export to multiple aspect ratios (9:16, 1:1, 16:9) in one tap
- Direct publish to 3–4 platforms in one step
- Works offline — not everyone has cell service at the location

## Cross-Platform Gaps aVs Could Fill

| Feature | GoPro Quik | DJI LightCut | Insta360 App |
|---|---|---|---|
| Cross-brand footage | No | No | No |
| Multi-platform upload | Limited | Limited | Limited |
| Sport-specific presets | Some | No | Some |
| Telemetry overlays | GoPro only | DJI only | Insta360 only |
| Desktop + mobile sync | Yes (Quik) | Partial | Yes (Studio) |
| 360 reframing | No | No | Yes |
| Offline editing | Partial | Partial | Partial |

A unified tool that ingests from all three, normalizes telemetry data, and exports to all major social platforms is the gap.

## Related Files

- [gopro.md](gopro.md) — GoPro ecosystem: formats, editing, upload paths
- [dji.md](dji.md) — DJI ecosystem: formats, editing, upload paths  
- [insta360.md](insta360.md) — Insta360 ecosystem: formats, editing, upload paths
