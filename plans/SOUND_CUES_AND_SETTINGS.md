# Scripted sound cues and Settings — backend 28

Voice Studio accepts speech interleaved with local sound descriptions:

```text
{gentle rain} Oh, LOOK! a car!! <car honking> That was loud. {stop}
```

- `<description>` inserts an action sound between spoken sections. Descriptions are never narrated.
- `{description}` starts a background bed at that point, underneath subsequent speech/actions. A new background replaces it; `{stop}` stops it. Otherwise it ends with the clip.
- Optional duration/gain: `<car horn | 2s | -6dB>` or `{rain | 8s | -20dB}`. Durations describe generated sound segments; backgrounds loop with crossfades as needed.
- `<pause: 1s>` inserts silence. Escape literal delimiters with a backslash.
- Maximum 12 sound cues, 240 characters per description; effect duration 0.5–10 seconds, gain -40–0 dB, pauses up to 30 seconds.
- Preview cue layout validates the script without inference. Voice design audition text remains plain text.

AudioLDM2 (`cvssp/audioldm2`, revision `c8e7e189d324425c05c4c2f81214041ef4107983`) is installed locally: 4,480,957,927 bytes. Its CC-BY-NC-SA-4.0 license is displayed in Settings; it is not a commercial-use model. Speech and effects run sequentially under the existing GPU reservation, then mix on CPU. Repeated sound descriptions reuse cached WAVs. Generation is approximate and adds latency; it is not a curated effects library.

The shared runtime uses Transformers 5. A project-local AudioLDM2 adapter uses GPT2 forward/cache APIs rather than removed private generation helpers. A deterministic CPU reference check compares cached hidden states with full-prefix recomputation. No video/image library downgrade was required.

Settings now occupies the workspace independently, with Back to work preserving the mounted work item and unsent drafts. Categories are General, Video, Images, Audio, Chat, and Activity & logs. Models are dropdown choices within engine roles, not separate sections for every model. Search covers categories, roles and models. Existing download/import/remove controls, behavior editors and diagnostics remain available.

Validation: 74 Python tests and 16 JavaScript tests passed. Native Electron checks passed category/search/no-results behavior, separate Settings display, draft restoration and sound-script preview, without browser errors. Screenshot: `maintenance/settings-audio-view.png`. Real GPU sound-only generation produced a non-silent 5-second action/background mix in 48 seconds. Full speech integration completed in 44 seconds with cached effects, producing 5.2 seconds of non-silent 24 kHz audio. Timeline: speech 0–1.92s, horn 1.92–3.92s, next speech and rain 3.92–5.2s. Evidence: `maintenance/tagged-audio-live-check.json`, `maintenance/tagged-audio-plan.json` and `maintenance/tagged-audio-demo.wav`.
