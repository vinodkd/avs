# Audio & Music — Research Notes

## Design decision

AxEdUp does not bundle music. Redistribution of audio tracks requires per-track
licensing that is incompatible with an open-source or freely distributed app.
Instead:

- **v1:** user provides their own track via `--music /path/to/track.mp3`
- **Phase 2:** in-app browser to search CC0 sources and point to a track URL

---

## Content ID and upload compliance

### The problem

"Royalty free" and "Creative Commons" do not mean "safe to upload."
YouTube Content ID allows any rights holder to register audio fingerprints.
If someone registered a CC-licensed track with Content ID, your video gets
claimed even if your use was legally permitted. The claim doesn't take the
video down but can redirect monetisation to the claimant or block the video
in certain territories.

Instagram/Meta has a separate rights management system with similar behaviour.

### What actually works

| Source | YT safe | IG safe | Redistributable | Notes |
|---|---|---|---|---|
| YouTube Audio Library | ✓ | Partial | No (video use only) | Best for YT; not for bundling |
| CC0 (public domain) | ✓ | ✓ | ✓ | Safest legally; limited selection |
| CC-BY from FMA/ccMixter | Usually | Usually | ✓ with attribution | Can still be Content ID claimed |
| Artlist / Epidemic Sound | ✓ | ✓ | No (per-user license) | Paid; handles claims; can't bundle |
| Incompetech (Kevin MacLeod) | Usually | Usually | CC-BY | Widely used; some tracks claimed |

### Practical guidance for users

- For YouTube: use YouTube Audio Library tracks — explicitly pre-cleared, no claims
- For Instagram: use CC0 or a paid library (Artlist/Epidemic)
- For both: a paid library subscription (Artlist ~$200/yr) is the only reliable
  guarantee across platforms with no manual verification needed
- There is no public API to pre-check Content ID status before uploading

### Why we can't pre-check programmatically

YouTube's Content ID database is private. There is no API endpoint to query
whether a given audio fingerprint is registered. The only signal is a claim
notification after upload, which is too late. Some third-party tools claim to
check this but they are unreliable.

---

## CC0 music sources worth evaluating for the browser feature

- **Free Music Archive** (freemusicarchive.org) — large catalogue, filter by CC0
- **ccMixter** (ccmixter.org) — community remixes, CC licensing, filter by CC0
- **Pixabay Music** (pixabay.com/music) — explicitly royalty-free, no Content ID
- **Musopen** (musopen.org) — classical music, public domain recordings
- **Internet Archive** (archive.org/details/audio) — public domain audio

### For the Phase 2 browser

The browser feature should:
1. Query one or more of the above sources (most have APIs or RSS feeds)
2. Filter to CC0 only to avoid attribution complexity
3. Let the user preview a track in-app before committing
4. Download the selected track to a local cache and pass it as the music path
5. Store the track URL and licence info in the session record for provenance

---

## Titles

Separate from music but related to the output polish question.
ffmpeg `drawtext` filter supports:

- **Intro card:** black frame with fading sport/date/location text at start
- **Lower thirds:** text overlay at a timestamp during footage
- **Outro card:** end screen with text

Data available in the pipeline for auto-generation:
- Sport name (from session.sport)
- Date (from session.created_at or clip filename)
- Location (from first TelemetryPoint with lat/lon → reverse geocode to place name)

Reverse geocoding: `geopy` with Nominatim (OpenStreetMap, free, no API key needed).
Add to backlog as a Phase 1.5 polish feature.
