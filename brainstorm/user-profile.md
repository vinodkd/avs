# aVs: User Profile & Preferences Model

## The Cold-Start Problem, Solved

First-time users have no history. Rather than showing a configuration screen, aVs asks **one question**:

> "What sport do you film?"

The answer bootstraps a complete default profile. The user gets a reasonable video immediately, without having to think about edit preferences. Every subsequent tweak — "make it shorter," "less punchy color," "skip the speed overlay" — is recorded against their profile. Over time, "my usual" genuinely reflects *their* style, not the sport default.

---

## Sport Default Profiles

Each sport has well-established video conventions that the community immediately recognizes and expects. These are the defaults:

### Mountain Biking
- **Duration:** 3–5 min (YouTube), 45–60 sec (Reels/TikTok/Shorts)
- **Color grade:** Punchy, saturated, slightly warm — high contrast
- **Music:** Rock, metal, hip-hop — high energy, strong beat
- **Cut rhythm:** Fast cuts on drops/jumps, hold on features, slow on pedaling
- **Overlays:** Speed (km/h), elevation profile, GPS trail map
- **Upload default:** YouTube public + Instagram Reel

### Surfing
- **Duration:** 2–4 min (YouTube), 30–45 sec (Reels)
- **Color grade:** Warm, golden, saturated — ocean blues pop
- **Music:** Reggae, indie surf, chill electronic
- **Cut rhythm:** Medium pacing — let rides play out, don't over-cut
- **Overlays:** Minimal — mostly clean. Wave count if available.
- **Upload default:** YouTube public + Instagram Reel

### Skiing / Snowboarding
- **Duration:** 3–5 min (YouTube), 45–60 sec (Reels)
- **Color grade:** Cool/blue tones, bright whites, high contrast
- **Music:** Electronic, trap, anthemic — fast and driving
- **Cut rhythm:** Fast cuts on runs, breathe on scenic/lift shots
- **Overlays:** Speed (km/h) and altitude — key bragging rights in ski content
- **Upload default:** YouTube public + Instagram Reel

### Skydiving / BASE
- **Duration:** 2–3 min (YouTube), 60 sec (Reels)
- **Color grade:** Vibrant — sky blue, earth contrast
- **Music:** Epic electronic, cinematic build → drop
- **Cut rhythm:** Build slow (aircraft, door), explode fast (freefall), calm (canopy)
- **Overlays:** Altitude is mandatory for context; freefall speed
- **Upload default:** YouTube public + Instagram Reel

### Motorcycling / Moto
- **Duration:** 5–10 min (YouTube), 60 sec (Reels)
- **Color grade:** Cinematic, slightly desaturated, road-warm tones
- **Music:** Rock, classic rock, driving electronic
- **Cut rhythm:** Medium — let road shots breathe; cut on corners
- **Overlays:** Speed (very important in moto content), GPS route
- **Upload default:** YouTube public + Instagram Reel

### Trail Running / Hiking
- **Duration:** 2–4 min (YouTube), 30–45 sec (Reels)
- **Color grade:** Natural, earthy, slightly warm
- **Music:** Upbeat indie, folk, light electronic
- **Cut rhythm:** Slower, contemplative — nature content holds longer
- **Overlays:** Pace (min/km), elevation gain, heart rate if available
- **Upload default:** YouTube public + Strava activity

### Road / Gravel Cycling
- **Duration:** 3–8 min (YouTube), 45–60 sec (Reels)
- **Color grade:** Natural to slightly warm — road scenery
- **Music:** Varied — upbeat but not aggressive
- **Cut rhythm:** Medium — let scenery breathe
- **Overlays:** Speed, elevation, heart rate, Strava segment times
- **Upload default:** YouTube public + Strava activity

### Kayaking / Whitewater
- **Duration:** 2–4 min (YouTube), 45 sec (Reels)
- **Color grade:** Cool blues/greens, high contrast, water clarity
- **Music:** High energy — rock, electronic
- **Cut rhythm:** Fast cuts on rapids, slower on flat water
- **Overlays:** Speed through rapids, GPS route
- **Upload default:** YouTube public + Instagram Reel

---

## The Preference Data Model

A user profile is a structured set of preferences with a sport default as the baseline. Each field can be at one of three states:

- **default** — sport preset value, never explicitly set by the user
- **set** — user has explicitly changed this value once
- **learned** — user has confirmed or tweaked this value across multiple sessions

```
UserProfile {
  sport: string                      // "mtb", "surf", "ski", etc.
  
  edit: {
    youtube_duration_min: int        // seconds
    youtube_duration_max: int
    shorts_duration: int             // seconds
    reels_duration: int              // seconds
    color_grade: string              // "punchy" | "cinematic" | "natural" | "warm" | "cool"
    music_energy: string             // "high" | "medium" | "chill"
    music_genre: string[]            // ["rock", "electronic", ...]
    cut_rhythm: string               // "fast" | "medium" | "slow"
    overlays: string[]               // ["speed", "altitude", "gps_map", "heart_rate"]
  }
  
  publish: {
    default_platforms: string[]      // ["youtube", "instagram", "strava"]
    default_visibility: string       // "public" | "unlisted" | "private"
    youtube_channel_id: string
    instagram_account: string
    strava_athlete_id: string
    tiktok_account: string
  }
  
  credentials: {
    // OAuth tokens per platform, stored securely
  }
  
  history: [
    {
      session_id: string
      brief: string                  // what the user said
      tweaks: string[]               // ["made shorter", "removed speed overlay", ...]
      accepted: bool
    }
  ]
}
```

---

## How Preferences Evolve

The system tracks tweaks from the conversational refinement loop and uses them to update the profile. Over time, the profile drifts from the sport default toward the user's actual preferences.

**Example evolution for an MTB rider:**

| Session | Tweak | Profile update |
|---|---|---|
| 1 | "Make it shorter" | youtube_duration_max: 4min → 3min |
| 2 | "Remove the GPS map overlay" | overlays: remove "gps_map" |
| 3 | (no tweak — accepted as-is) | all current values reinforced |
| 4 | "Less punchy color, more cinematic" | color_grade: "punchy" → "cinematic" |
| 5 | (no tweak — accepted as-is) | color_grade "cinematic" state: learned |

By session 5, "my usual" means: 3-min YouTube video, cinematic color grade, speed + altitude overlays (no map), high-energy rock music.

---

## Multi-Sport Users

Action sports enthusiasts often do multiple sports. Profile supports multiple sport contexts:

> "I shoot MTB in summer and skiing in winter"

The system maintains separate preference profiles per sport context, and detects which to apply either from the session brief or by asking once when context is ambiguous.

The user can also explicitly switch: "use my ski settings for this one even though it's a bike ride" — useful when shooting in snow, for example.

---

## The "My Usual" Reference in a Brief

When a user says "my usual preferences," the system resolves it against the current sport context in the user profile. The LLM receives the resolved preferences as structured context alongside the brief — it doesn't need to "know" the user, it just receives their profile as input.

This also means the preferences are portable across AI services. If the user switches from Claude to ChatGPT, their profile travels with the aVs daemon, not with the AI service.
