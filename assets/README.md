# Sound library

- `music/` — background tracks (mp3/wav/m4a/flac/ogg). The planner picks a track by tags and mood.
- `sfx/` — sound effects; the planner places them per shot (`sfx: [{file, offset, volume}]`).
- `index.json` — the tag index. Created by `python studio.py assets`; tags and the `mood` field can be
  edited by hand and survive re-indexing.

Use descriptive file names: `lofi_rain_calm_80bpm.mp3`, `thunder_distant.wav` — tags are derived from
them. Only use music you have the rights to.
