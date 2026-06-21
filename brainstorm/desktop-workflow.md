# aVs: Desktop App — Workflow & UX Design

## Scope Decision

**v1: Desktop app, SD card as file source.**

No camera WiFi. No mobile. No cloud. No MCP server. Just:

> Insert SD card → app processes footage → user reviews and approves → export → upload

This strips out all the integration complexity and focuses on getting the core editing UX right. Camera integrations (GoPro WiFi, DJI, Insta360 cloud) come later, as additions to a working foundation.

**Context:** This is the *end-of-day* session. The user is home. The activity is done. They want to turn today's raw footage into something shareable before they go to sleep. Speed matters. Cognitive load matters. They don't want to become a video editor.

---

## The 3-Pass Workflow Insight

Experienced action video editors — whether they know it or not — work in three passes:

### Pass 1: The Overview
*"What did I actually shoot today?"*

Watch the whole session quickly (4–8x speed) to build a mental map of the footage: where the good bits are, how long things run, what's usable. This is reconnaissance, not editing. The output is a rough mental model, not any actual selection.

**The problem:** With 45 minutes of raw footage, even at 8x that's 5+ minutes of scrubbing. With multiple clips from multiple cameras, it's disorienting.

### Pass 2: Mark the Moments
*"Which bits do I actually want?"*

Go back through with intent — pause, set in/out points, save regions of interest. This is where real judgement is applied: "this jump is good, that pedalling section is boring, this crash is gold."

**The problem:** Requires watching footage twice (at minimum), and the marking interface in most tools is friction-heavy — keyboard shortcuts, precise frame navigation, clip naming.

### Pass 3: Assemble and Finish
*"Make it look like a real video."*

Take the marked clips, arrange them, add color grade, music, transitions, captions, telemetry overlays, intro/outro. Export in the right formats. Upload.

**The problem:** Most tools present this as an open-ended creative canvas (timeline, effects panel, etc.) which is overwhelming if you just want "a good video, not a masterpiece."

---

## How aVs Reimagines Each Pass

The goal is not to eliminate the three passes — they reflect real cognitive work that needs to happen. The goal is to **compress and assist each pass** so the total session takes 15–20 minutes, not 2 hours.

### Pass 1 → The Footage Map (automated)

Instead of scrubbing video, the user sees a **visual map** of the session generated automatically when the SD card is inserted:

- **Thumbnail strip:** one frame per N seconds across all clips, laid out as a scrollable timeline
- **Telemetry graph:** speed/altitude/G-force plotted under the thumbnail strip — action peaks are immediately visible as spikes
- **Scene markers:** automatic scene-change boundaries detected by OpenCV/PySceneDetect shown as dividers
- **Clip boundaries:** where one recording session ends and another begins, clearly marked
- **Auto-rough-cut preview (optional):** a 90-second "everything interesting" preview assembled from telemetry peaks and motion analysis, so the user can watch one short video instead of scanning the map

The user spends 2–3 minutes reviewing the map rather than watching 45 minutes of footage. They arrive at Pass 2 with a complete picture of what they have.

### Pass 2 → Assisted Marking (AI pre-selection + user confirmation)

The system arrives at Pass 2 with **pre-marked candidates** based on:

- **Telemetry peaks:** moments where speed, altitude change, or G-force exceed a threshold → likely action moments
- **Motion intensity:** high optical flow in the frame → camera or subject moving fast
- **Audio spikes:** impact sounds, cheering, engine revs → contextually interesting moments
- **Scene length heuristics:** very short scenes (< 3 sec) are likely transitions; very long scenes (> 2 min) probably contain filler

These candidates are shown as highlighted regions on the footage map. The user's job is:
- Accept pre-marked regions (tap/click to confirm)
- Reject boring pre-marks (remove)
- Adjust in/out points on any region
- Add their own marks the system missed

**The brief enters here.** If the user types or says:
> "third clip has the best twisties, and the crash at the end is worth including"

...the system:
1. Locates "third clip" by index and pre-selects its highest-intensity region
2. Searches for a sudden stop/tumble event (telemetry drop + motion spike) near the end and pre-selects it
3. Surfaces these as priority candidates at the top of the review queue

The brief doesn't replace the marking pass — it gives the system context to prioritize and explain its pre-selections. Without a brief, the system still works; it just uses telemetry and motion alone.

**Output of Pass 2:** an ordered list of approved clip regions with in/out points. No timeline yet — just a selection.

### Pass 3 → Preset-Driven Assembly (AI applies, user approves)

The system assembles the approved clips into a finished video automatically, applying the user's sport profile:

- **Order:** by default, chronological. User can drag to reorder if needed.
- **Color grade:** from sport profile (punchy MTB, warm surf, cool ski, etc.)
- **Music:** selected by energy level and genre from the sport profile; auto-synced to cuts
- **Cut rhythm:** fast cuts on high-telemetry sections, longer holds on scenic/calm sections
- **Transitions:** simple cuts by default; dissolves on scene-type changes
- **Telemetry overlays:** automatically placed if telemetry data is present; style from sport profile
- **Captions/title:** drafted from the session brief if one was provided, or a simple date+sport default

The user sees the assembled video in a **review player** — not an editing timeline. Controls are coarse:

- "This clip needs to be shorter / longer"
- "Swap this clip for a different one"
- "Remove this clip"
- "Try a different music track"
- "Change the color to more cinematic"
- "Remove the speed overlay"

These are text or voice instructions. The system re-renders the affected section. No timeline scrubbing.

**Output of Pass 3:** a finished video ready for export.

---

## Where OpenCV Fits vs. Where LLM Fits

These two tools are complementary, not competing.

| Task | OpenCV / Signal Analysis | LLM |
|---|---|---|
| Find scene boundaries | ✓ | |
| Detect motion intensity | ✓ | |
| Find telemetry peaks | ✓ | |
| Detect audio spikes | ✓ | |
| Understand "third clip" | | ✓ |
| Understand "the crash at the end" | | ✓ |
| Apply "my usual preferences" | | ✓ |
| Draft title/description | | ✓ |
| Resolve contradictory instructions | | ✓ |
| Beat-sync cuts to music | ✓ | |

**Minimum viable v1 (no LLM at all):** OpenCV + telemetry analysis handles Passes 1 and 2 automatically. Sport presets handle Pass 3. No brief required. This is essentially a smarter Antix — but desktop, cross-brand, and with a review step.

**Enhanced v2 (with LLM):** Brief input added to Pass 2. The LLM interprets the brief and adjusts the pre-selection and assembly. Still uses OpenCV/telemetry for the base analysis; LLM only for contextual override.

**This suggests a clean build order:** Build the OpenCV/telemetry pipeline first. Ship it. Add the brief/LLM layer as an enhancement.

---

## The Desktop UX — Screen by Screen

### Screen 1: Session Import
- App detects SD card insertion, scans for video files
- Shows: camera brand detected (from file format/metadata), clip count, total duration, date
- One button: "Process Session"
- Background: thumbnail generation, telemetry parsing, scene detection (progress shown)

### Screen 2: Footage Map (Pass 1)
- Full-width scrollable thumbnail strip with telemetry graph below
- Color-coded scene markers (green = high action, grey = calm)
- Clip boundaries clearly marked
- Play button on any thumbnail for quick preview
- Optional: "Show me the quick preview" → 90-second auto-rough-cut plays in a panel
- When ready: "Mark moments →"

### Screen 3: Clip Review (Pass 2)
- AI pre-marked regions shown as cards: thumbnail + duration + telemetry summary ("peak speed: 47 km/h")
- Each card: Accept / Reject / Adjust
- Brief input box at the top: optional, but surfaces here where it's most useful
- Unranked — system puts highest-confidence picks first
- User can drag to reorder the approved set
- When done: "Assemble →"

### Screen 4: Review Player (Pass 3)
- Full-screen video player
- Sport preset applied, music added, overlays placed
- Below the player: a simple text/voice input for refinement ("shorter", "different music", "remove the overlay")
- Side panel (collapsed by default): export settings (duration, aspect ratios, platforms)
- "Looks good → Export & Upload"

### Screen 5: Export & Upload
- Aspect ratio selection: 16:9 (YouTube), 9:16 (Reels/TikTok/Shorts), 1:1 (Instagram)
- Platform selection: YouTube, Instagram, TikTok, Strava (configured in settings)
- Per-platform: title (pre-filled from brief or session date), description, visibility
- "Upload all" — fires off in background
- Done

---

## What This Deliberately Excludes (for now)

- Frame-precise trimming
- Multi-track timeline
- Manual keyframing
- Per-clip effects control
- Camera WiFi / Bluetooth import
- Mobile version
- Cloud processing
- 360 footage

These are all real features. They belong in later versions, not the thing that validates whether the core 3-pass workflow is worth building.
