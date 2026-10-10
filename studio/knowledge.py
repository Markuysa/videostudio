"""Знания студии: правила промптинга LTX-2.5 и пресеты форматов.

Источники: README LTX-2 (Lightricks), гайд по промптингу LTX-2, карточка модели
LTX-2.5 (multishot, диффузионный декодер), практические гайды по multishot.
Текст на английском, потому что в таком виде он попадает в системный промпт LLM
и в промпты для видеомодели.
"""
from __future__ import annotations

LTX_PROMPT_RULES = """\
# How to write a prompt for LTX-2.5 (one prompt = one generated clip, 3-10 s)

Write ONE flowing paragraph in English, present tense, 70-180 words, chronological: what the viewer sees and
hears from the first frame to the last. No bullet points, no "Shot 1:" sluglines, no headings, no line breaks.
Start directly with the framing and the action, never with "In this scene" or "The video shows".

Cover these elements, in roughly this order:
1. SHOT & FRAMING: shot size and angle ("Extreme close-up", "Wide shot from behind", "Low-angle medium shot"),
   lens feel ("shallow depth of field", "anamorphic", "35mm handheld").
2. SUBJECT & APPEARANCE: who/what is in frame with concrete physical details (age, hair, clothing, distinguishing
   features, materials, colors). Reuse the exact same descriptor for a recurring character in every prompt
   ("the old fisherman with a wet grey beard and a brass lantern"), never a bare pronoun at the start.
3. ACTION: a natural sequence of 2-4 concrete movements and gestures, each leading to the next. Express emotion
   through visible physical cues ("his jaw tightens and he looks away"), not labels ("he is sad").
4. CAMERA MOVEMENT: name the move and WHEN it happens ("the camera slowly pushes in as she lifts the cup",
   "static camera", "slow crane up and away"). Describe how the frame looks after the move.
5. LIGHT & COLOR: one coherent light logic per shot (source, direction, quality, color temperature) and the
   palette/grade ("cold blue overcast light, desaturated teal shadows, warm lantern glow on the face").
6. SOUND (mandatory, last sentences): describe the audio chronologically: ambience, specific sound effects with a
   visible or locatable source, music only if it is diegetic or you want the model to score it, and dialogue.
   Dialogue goes in double quotes with the speaker's voice described ("he whispers in a hoarse voice: \\"I'll wait.\\"").
   You may state the language of speech ("she says in Russian: ..."). Give the model a moment of stillness before
   a line so lip-sync has something to lock onto; keep lines short (one sentence).

Hard rules:
- Describe exactly what the camera sees in these seconds. One location, one continuous time span per clip,
  unless you deliberately write a native multishot clip (below).
- Never request on-screen text, signs with specific words, logos, subtitles or captions: text rendering is unreliable.
- Never use negative phrasing ("no people", "without rain"): say what IS there instead.
- Avoid abstract mood words alone ("tense atmosphere", "eerie"); replace with a moving object plus its sound.
- Keep the whole prompt literal and precise, like a cinematographer describing a shot to the crew.

Native multishot (optional, for 8-10 s clips): LTX-2.5 can cut between 2-3 connected shots inside one clip while
holding identity, lighting and voice. Write it as one chronological paragraph: at each cut, name the edit
("A hard cut to ...", "A match cut connects ..."), re-establish the framing completely, re-identify the
character with the same descriptor, and say what the sound does across the cut. Use at most 3 shots per clip.

Continuity between clips (the studio handles this technically): if a shot is marked transition="continue",
the clip will start from the exact last frame of the previous clip, so its prompt must begin from the end state of
the previous action and continue the same camera setup or motivate a new move from it.
"""

KIND_PRESETS: dict[str, dict] = {
    "short": {
        "label": "вертикальный шортс (TikTok / Reels / Shorts)",
        "default_seconds": 45, "min_seconds": 12, "max_seconds": 90,
        "default_format": "9:16", "shot_seconds": (3, 8), "captions": True,
        "brief": (
            "A vertical short for TikTok/Reels/Shorts. The first 2 seconds must be a visual hook: strong motion, a "
            "face, a question or a surprising image, no slow establishing shot. Fast pace: 3-6 s shots, mostly hard "
            "cuts, one continuous idea, satisfying payoff or loop-friendly ending in the last shot. Compose for a "
            "phone screen: subjects centered, important action in the middle 60% of the frame, big close-ups, "
            "avoid tiny details. Each shot gets a short on-screen caption (2-7 words, in the requested language) "
            "that advances the story or hook; captions are rendered by the studio, never ask the model for text."
        ),
    },
    "aesthetic": {
        "label": "эстетичное атмосферное видео",
        "default_seconds": 40, "min_seconds": 15, "max_seconds": 180,
        "default_format": "9:16", "shot_seconds": (5, 10), "captions": False,
        "brief": (
            "An aesthetic mood piece: slow, sensory, music-led. Long takes 6-10 s, gentle or static camera, "
            "dissolves and 'continue' transitions, consistent palette and light logic across all shots, textures "
            "and small motions (steam, rain, fabric, light flicker). Rich ambience in the sound description, no "
            "dialogue unless requested. Every shot should look like a frame from the same photographer's series."
        ),
    },
    "film": {
        "label": "короткометражный фильм",
        "default_seconds": 180, "min_seconds": 40, "max_seconds": 900,
        "default_format": "16:9", "shot_seconds": (4, 10), "captions": False,
        "brief": (
            "A short film with a clear dramatic structure: setup, escalation, turning point, resolution. Vary shot "
            "sizes and angles like a real DP (wide / medium / close-up / insert / reaction), keep 180-degree logic "
            "and eyelines consistent, use mostly hard cuts, 'continue' for actions that must flow across clips, "
            "dissolves only for time jumps. Short dialogue lines are allowed (one sentence per shot, voice "
            "described). Visual motifs should recur. The ending must land emotionally."
        ),
    },
    "episode": {
        "label": "эпизод мини-сериала",
        "default_seconds": 150, "min_seconds": 40, "max_seconds": 600,
        "default_format": "16:9", "shot_seconds": (4, 10), "captions": False,
        "brief": (
            "An episode of an ongoing short series. Follow the series bible strictly: the same character "
            "descriptors word for word, the same locations, the same palette and sound signature. Start with a "
            "cold open that hooks within 5 seconds, advance the season arc by one meaningful step, and end on a "
            "cliffhanger or an emotional button that makes the next episode necessary."
        ),
    },
}

STYLE_REFERENCE = """\
Style bible fields you must fill (short, concrete, reusable in every prompt):
- visual: overall look in one sentence (e.g. "wet neon-lit Tokyo alleys shot on anamorphic lenses, cinematic realism").
- palette: 3-5 colors and how they are used.
- lens: focal length feel, depth of field, grain/texture.
- lighting: main light logic and time of day.
- camera: how the camera tends to move in this piece.
- sound: the sonic signature (ambience, materials, music mood if the studio adds music later).
- pace: cutting rhythm.
"""
