# AI Film Studio on LTX-2.5

One command: your request in plain words → screenplay and shot list with optimized prompts →
scene rendering on a RunPod GPU (LTX-2.5, video + audio) → seamless assembly with music, sound
effects, captions and loudness normalization → a finished `film.mp4` on your disk.

```bash
python studio.py make "Aesthetic short: rainy evening in Tokyo, a girl with a red umbrella, lo-fi mood" \
    --kind aesthetic --duration 40
```

Formats: `short` (vertical short with a hook and captions), `aesthetic` (mood piece under music),
`film` (short film with dramatic structure), `episode` (series episode driven by a character bible).
Add `--loop` for a seamless loop: the last shot is conditioned on the first frame of the film.

## Installation

```bash
cd film_studio
python3 -m venv .venv && .venv/bin/pip install anthropic pytest
cp film_config.example.json film_config.json      # fill in runpod_api_key and network_volume_id
export ANTHROPIC_API_KEY=sk-ant-...                # the studio's "brain"; without a key a local Ollama is used
brew install ffmpeg                                # only for local re-assembly (studio assemble)
.venv/bin/python studio.py doctor                  # environment check
```

Rendering needs a RunPod account with a Network Volume (100+ GB) and accepted licenses for
huggingface.co/Lightricks/LTX-2.5 and LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler (`hf_token` in the
config for the first install). Models are downloaded to the volume once (~70 GB); after that every
render starts within a minute.

## Web interface

```bash
.venv/bin/python studio.py ui          # opens http://127.0.0.1:8765 in the browser
```

Home: a "what are we shooting?" form (type, duration, and under "More settings": format, quality,
language, music, captions, series, loop) with "Shoot" (plan + render) and "Script only" buttons. Jobs
run as separate processes with a live log and per-shot progress; closing the browser or the server does
not stop a render. Sections: Plans (shots, lint check, JSON editing, render, prompt fixing by the model),
Films (player, shot timeline with the pipeline used for each shot, re-assembly with different
music/captions, download), Series (bibles, episodes, continuity notes), Sound (music and SFX upload),
Settings (diagnostics, planner preferences).

## Commands

| Command | What it does |
|---|---|
| `studio.py plan "request" [--kind] [--duration] [--format] [--quality] [--music] [--captions] [--loop]` | build a plan: story, style bible, characters, shots with prompts |
| `studio.py make "request" ...` | plan + render + download in one command |
| `studio.py render plans/x.json [--keep-pod]` | render an existing plan on RunPod |
| `studio.py review plans/x.json [--fix]` | lint the prompts; with `--fix` let the model repair them |
| `studio.py estimate plans/x.json` | running time, render time and cost estimate |
| `studio.py assemble films/<slug> [--music track] [--captions]` | re-assemble a downloaded film locally without a GPU |
| `studio.py series new "description" --name tokyo --episodes 6` | create a series bible |
| `studio.py plan "what happens in the episode" --series tokyo` | an episode driven by the bible (character descriptors verbatim) |
| `studio.py series show/list/note` | view a bible, add a continuity note |
| `studio.py assets` | re-index the music and SFX library |
| `studio.py prefs "fewer close-ups"` | standing preferences applied to all future plans |
| `studio.py fetch <slug>` / `cleanup` | fetch a film from the volume / delete all studio Pods |
| `studio.py ui [--port 8765]` | web interface |

`python make_film.py plans/x.json` still works (a wrapper around `render`).

## Plan format

`plans/<slug>.json` is plain JSON and can be edited by hand before rendering:

```json
{
 "title": "I'll Wait", "kind": "film", "format": "9:16", "quality": "high", "seed": 2026,
 "style": {"visual": "...", "palette": "...", "lighting": "...", "sound": "..."},
 "characters": [{"name": "Old man", "descriptor": "an old fisherman with a wet grey beard and a brass lantern"}],
 "music": {"file": "assets/music/sea_ambient.mp3", "volume": 0.25, "duck": true},
 "captions": {"enabled": false},
 "loop": false,
 "shots": [
  {"id": "001", "seconds": 8, "transition": "cut", "prompt": "Extreme close-up ... Sound: ..."},
  {"id": "002", "seconds": 8, "transition": "continue", "prompt": "..."},
  {"id": "003", "seconds": 5, "transition": "dissolve", "transition_seconds": 0.6, "prompt": "...",
   "caption": "He waited all night", "sfx": [{"file": "assets/sfx/thunder.wav", "offset": 1.2, "volume": 0.7}]}
 ]
}
```

- `transition`: `cut` — hard cut; `continue` — the clip starts from the last frame of the previous one
  (a single continuous take longer than 10 s); `dissolve` — video and audio crossfade.
- Durations snap to the LTX grid (8k+1 frames at 24 fps). In `high` mode a shot is ≤ 10 s, in `fast`
  ≤ 20 s (long clips are generated in windows). Shots conditioned on a frame (`continue`, the final
  shot of a loop) are ≤ 5 s in `high` mode.
- `loop: true` — the last shot ends on the first frame of the film; no fades, the duplicate seam frame
  is dropped.
- Version 1 plans (`"continue": true`) are read unchanged.

## How the studio writes prompts

The planner (Claude Opus 5.5 by default, or a local Ollama) works in three passes: story and style
bible → shots per act → linter + targeted fixes. The LTX-2.5 prompting rules live in
`studio/knowledge.py`: one paragraph of 70–180 words in present tense, framing → character (a
persistent descriptor instead of a name) → action → camera move → light → sound and quoted dialogue,
no on-screen text, no negations. The linter (`studio/lint.py`) checks every prompt deterministically:
language, length, camera, sound, light, list formatting, pronouns without a descriptor, requests to
render text.

Your standing preferences (`studio prefs`), the series bible and the sound library go into the system
prompt, so prompts are optimized for your requests and your material.

## Seamless assembly

`studio/assemble.py` builds the film in a single ffmpeg pass: clip normalization, micro audio fades at
cuts (no clicks), removal of the duplicated frame on `continue`, `xfade`/`acrossfade` for dissolves,
looped music with fades and ducking under speech (sidechain), SFX and voice-over placed on the
timeline, ASS captions with a safe zone for 9:16, EBU R128 loudness normalization (−14 LUFS).

Clips are downloaded with the film into `films/<slug>/clips`, so changing the music or adding captions
needs no GPU: `studio.py assemble films/<slug> --music assets/music/other.mp3`.

## Rendering on RunPod

`studio/render_remote.py` starts a Pod (searches for free GPUs from the list; if no 80–96 GB card is
available within an hour it switches to `fast`), uploads the studio package and the plan, installs
LTX-2.5 (`remote/ltx_studio.sh`), launches `remote/film_night.sh` in the background and waits. The Pod
is deleted automatically even if the laptop goes to sleep (`max_hours`). Results always stay on the
volume: `studio.py fetch <slug>`.

`remote/film.py` renders every shot with a fallback chain: DFR (1080p, detailing) → distilled at the
same resolution with the same start frame → DFR without a frame → fast mode. This fixed the originally
failing shot 002 (CUBLAS / illegal memory access in the DFR keyframe decoder with an input image at
193+ frames; 121 frames pass at any conditioning strength, so the planner keeps `continue` shots in
`high` mode at 5 s or less, and long shots with a start frame go straight to distilled 1080p). DFR also
fails with a condition on the last frame, so the final shot of a loop is always rendered distilled.
Finished clips are cached by prompt content; a restart resumes where it stopped. `report.json` shows
which pipeline produced each shot.

## Voice and sound

- LTX-2.5 generates speech and ambience itself from the prompt (quoted lines, described voice).
- Music and SFX come from your library in `assets/music` and `assets/sfx` (see `assets/README.md`).
  Without tracks the plan still stores `music.mood`; a track can be added later and the film re-assembled.
- Voice-over: the `narration` field of a shot + ElevenLabs (`elevenlabs_api_key`, `elevenlabs_voice_id`).
  Files are generated before the render and travel to the Pod with the plan.

## Tests

```bash
.venv/bin/python -m pytest -q tests
```

They cover the plan schema and frame grid, the linter, the ffmpeg filter graph and a real assembly of
synthetic clips, the planner with a fake LLM, a full run of `remote/film.py` with a simulated LTX
(including the fallback after a CUDA error, the cache and loop closing), the CLI and the web API.

## Layout

```
studio.py            CLI
studio/              package (travels to the Pod together with the plan)
  schema.py          plan, validation, frame grid
  knowledge.py       LTX-2.5 prompting rules, format presets
  planner.py         LLM planner (outline -> shots -> lint -> revise)
  lint.py            deterministic prompt linter
  llm.py             providers: Anthropic SDK, Ollama, Fake for tests
  bible.py           series bible
  audio.py           music/SFX library, TTS
  assemble.py        ffmpeg assembly
  render_remote.py   RunPod: Pod, upload, waiting, download
  ui.py, jobs.py     web interface (HTTP API + background jobs), web/ — the page
remote/              Pod side: ltx_studio.sh (install + web UI), film.py, film_night.sh
plans/ films/ series/ assets/
```
