# AxEdUp: Form Factor Brainstorm (Flat Video Scope)

## Scope Assumption

Flat video only — standard MP4 from GoPro, DJI Osmo, and Insta360 flat cameras.
AxEdUp360 covers 360 footage later.

This document is a brainstorm — all options are live. Nothing is decided yet.

---

## File Transfer Options

### Option A: Cloud-to-Cloud
Camera brand cloud (GoPro Plus, DJI cloud, Insta360 cloud) auto-uploads footage. AxEdUp connects via OAuth and pulls from there.
- **Pro:** Fully automatic — footage appears without user action
- **Con:** Requires user to have the camera brand's cloud subscription; requires AxEdUp to negotiate API partnerships with each brand
- **When to do it:** Phase 2+ once the core works

### Option B: Share Extension
User selects clips in any app (Files, GoPro Quik, camera roll) and shares to AxEdUp.
- **Pro:** Works with any file source; no API dependencies
- **Con:** Requires a manual "share" gesture per session; footage must already be in another app
- **When to do it:** Easy to implement, good fallback

### Option C: Camera WiFi Direct Pull
Camera creates a WiFi hotspot; AxEdUp pulls new files automatically when connected.
- **Pro:** Zero cloud subscriptions; works at the trailhead; feels automatic
- **Con:** Only works cleanly for GoPro (Open GoPro API); DJI/Insta360 don't expose WiFi file access to third parties easily
- **When to do it:** Phase 1 for GoPro; deferred for DJI/Insta360

### Option D: USB-C / SD Card Dongle
User inserts SD card via a USB-C dongle. AxEdUp reads it as a file system.
- **Pro:** Universal — works for all three brands, no API, no WiFi; most action sports enthusiasts already carry a dongle
- **Con:** Requires the dongle and a deliberate physical action; not at-the-trailhead if user doesn't carry it
- **When to do it:** Phase 1 — simplest universal option

**Phase 1 recommendation: Start with C (GoPro WiFi) + D (SD card) — zero external dependencies, works today.**

---

## User Input Model

The brief is not just "what do I want." It has three layers:

### Layer 1: Session Context — what the footage *is about*
> "today's run through X canyon. first few clips are short, the third one has the best ride through the twisties"

- The subject, setting, story
- Clip-level annotation without touching a timeline ("the third one")
- Quality signal ("best ride") that telemetry alone can't infer

### Layer 2: Persistent Preferences — "my usual"
> "make it good for YT upload using my usual preferences"

The system needs a user profile: preferred YT video length, color grade style, music genre, overlay style, channel name. Set once, recalled every time. Refined over time from feedback.

### Layer 3: Publishing Instructions
> "upload to my channel but don't make it public"

Platform, account, visibility (private / unlisted / public), timing, suggested title/description/tags (LLM-drafted from session context).

---

## Form Factor Options

### Option 1: Standalone Mobile App (iOS-first)

The trailhead use case — edit while still at the location.

- Ingest: SD card dongle or GoPro WiFi
- Brief: text input → cloud LLM or on-device model → structured edit plan
- Assembly: on-device ffmpeg / GPU encoding
- Review: in-app video player, conversational refinement
- Upload: direct from app

**Pro:** Always with the user; direct share to social from the phone; iOS GPU handles 4K H.265 well  
**Con:** Screen real estate tight for review; thermal limits on long sessions (20+ min); GoPro + DJI SDKs are stronger on iOS but Insta360 is shakier  
**Best for:** 30-second Reels, same-day quick shares

---

### Option 2: Standalone Desktop App (Mac-first)

Evening-after-the-session editing for longer-form content.

- Ingest: SD card reader, USB-C direct, or camera WiFi on home network
- Brief: text input → local or cloud LLM
- Assembly: full CPU/GPU, no thermal constraints
- Review: desktop video player with conversational refinement
- Upload: scheduled or immediate

**Pro:** Better hardware for long sessions; larger screen for review; no thermal limits  
**Con:** Not at the location; competing against DaVinci Resolve (free); higher install friction  
**Best for:** 5–10 min YouTube recaps, race edits, travel videos

---

### Option 3: Standalone App with Local LLM (Mobile or Desktop)

Same as Option 1 or 2, but the LLM runs **entirely on-device** — no API cost, no data sent externally, works offline.

The key insight: converting a user's plain-language brief into a structured edit plan (JSON with clip selections, timecodes, overlay choices, pacing) is a **structured reasoning task** — not a frontier-model problem. A 7B–13B quantized model handles this well.

**On Mac (Apple Silicon):**
- Ollama or MLX-LM can run Llama 3, Phi-3, Mistral locally
- M2/M3/M4 Macs run 7B models at 60+ tokens/sec — fast enough for real-time use
- Zero ongoing API cost; footage and brief never leave the machine

**On iPhone (Apple Intelligence / Core ML):**
- Apple Intelligence (iOS 18+) includes on-device reasoning models
- Core ML can run quantized models for specific tasks
- More constrained than desktop but viable for simple brief → edit plan conversion

**Pro:** No API cost ever; full privacy; works offline until upload step; no vendor dependency  
**Con:** Local model quality is lower than GPT-4 / Claude for creative tasks; model management is a new user problem ("which model do I use?"); quantized models can miss nuance in complex briefs  
**Mitigation:** The brief→plan task is constrained enough (structured output, known schema) that a well-prompted smaller model does fine. Creative quality comes from the presets and ffmpeg pipeline, not the LLM.

**This option deserves serious consideration.** It makes the entire app free to run, which changes the business model question significantly.

---

### Option 4: AI Service Extension (Plugin / MCP)

AxEdUp lives *inside* an existing AI assistant — no separate app.

**How it works:**
- User has Claude Desktop (or ChatGPT, Gemini) already open
- AxEdUp is installed as an MCP server (Claude) or plugin (ChatGPT/Gemini)
- User talks to their AI assistant naturally: "edit today's canyon footage, third clip is best, YouTube private"
- The assistant calls AxEdUp tools: `ingest_session`, `analyze_clips`, `create_edit_plan`, `assemble_video`, `preview_video`, `publish_video`
- Review happens via a Claude Artifact (inline video player in the chat) or a local browser URL
- Refinement is just the next message in the conversation — no custom chat UI to build

**Pro:**
- No app UI to build for the conversational layer — the AI provides it
- "My usual preferences" is already how people talk to AI assistants — memory is native
- Voice input comes for free (AI assistants already have it)
- Distribution through AI marketplace instead of app store
- Multi-turn refinement, context retention — all handled by the host AI

**Con:**
- User must already use an AI assistant and be comfortable with MCP/plugins
- Platform dependency — tied to Claude/ChatGPT ecosystem decisions
- Still requires a locally-running AxEdUp daemon for file access and processing
- Preview/review UX inside a chat interface is less polished than a dedicated player
- Less discoverable than an app store listing

**Best implementation path:** Claude MCP server first — MCP is local (no public endpoint needed), Claude Desktop is growing fast, and the ecosystem is the most developer-friendly right now.

---

## Comparing the Options

| | Mobile App | Desktop App | Local LLM App | AI Extension |
|---|---|---|---|---|
| File transfer | WiFi + dongle | WiFi + SD card | WiFi + SD card | WiFi + SD card |
| LLM cost | Cloud API cost | Cloud or local | Free (local) | User's AI subscription |
| Privacy | Footage stays local | Footage stays local | Fully local | Footage stays local |
| Works offline | Until upload | Until upload | Until upload | No (AI is cloud) |
| Build effort (UI) | High (full app) | High (full app) | High (full app) | Low (tools only) |
| Build effort (backend) | Medium | Medium | Medium | Medium |
| Conversational refinement | Build it | Build it | Build it | Free from host |
| Voice input | Build it | Build it | Build it | Free from host |
| User memory/preferences | Build it | Build it | Build it | Partially free |
| Discoverability | App store | App store | App store | AI marketplace |
| Business model | App purchase / sub | App purchase / sub | App purchase / sub | Usage fees or free |

---

## Key Observation: The Backend Is the Same for All Options

Regardless of form factor, the processing pipeline is identical:

```
Ingest (SD card / WiFi)
  → Scene detection + telemetry parsing
    → Brief interpretation (local or cloud LLM)
      → Edit plan (structured JSON)
        → Assembly (ffmpeg)
          → Review output (video file / local URL)
            → Upload (platform APIs)
```

The form factor decision only affects:
1. How the user interacts with steps 1 (ingest trigger) and 3 (brief input)
2. Where the review UI lives
3. Whether the LLM is local or cloud

**This means the backend can be built once and the UI layer is swappable.** A good first move: build the backend pipeline as a CLI or local daemon, then add UI options on top. This also makes Option 3 (local LLM) and Option 4 (AI extension) natural companions — the daemon is the backend for both.

---

## Open Questions for Further Brainstorming

1. Which form factor fits the target user's daily habits best — are they Claude/ChatGPT users already?
2. For local LLM: is brief→edit-plan quality good enough with a 7B model, or do we need 13B+?
3. Business model: if the app is free to run (local LLM, local processing), how does AxEdUp make money?
4. Can a single brief handle a multi-day trip (50+ clips across 3 cameras)?
5. ~~What does "my usual preferences" look like as a data model — and how is it first established?~~ **Resolved:** One onboarding question — "what sport?" — bootstraps a complete sport default profile. Tweaks from each session accumulate into a personal profile over time. See [user-profile.md](user-profile.md).
