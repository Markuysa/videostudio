"""Знания студии: правила промптинга LTX-2.5 и пресеты форматов.

Источники: README LTX-2 (Lightricks), гайд по промптингу LTX-2, карточка модели
LTX-2.5 (multishot, диффузионный декодер), практические гайды по multishot.
Текст на английском, потому что в таком виде он попадает в системный промпт LLM
и в промпты для видеомодели.
"""
from __future__ import annotations

DIRECTOR_RULES = """\
DIRECTOR'S CONTRACT — applies to films, shorts, aesthetic pieces, episodes and loops.
The producer's literal request and per-project notes take priority over genre defaults and standing preferences.
Preserve requested subject, count, appearance, setting, action, ending, camera, style and exclusions. Translate
exclusions into positive visible descriptions in the video prompt; retain the exclusions in the creative brief.
Do not invent rain, neon, slow motion, shallow focus, glamour, extra people, dialogue or camera moves merely
to make a shot 'cinematic'. Fill unspecified details conservatively and record them as assumptions, not requests.

First extract a creative_brief: must_keep (explicit requirements), avoid (explicit exclusions), assumptions
(your choices), visual_anchors (reusable concrete descriptors for subjects, props, location and lighting),
and loop_anchor (opening composition and motion phase to return to, or null). Keep these human-readable.
For every shot, first plan direction: start (visible opening state), action (one primary achievable action),
camera (framing plus at most one motivated move), end (visible closing state). Then compile that staging into
the English LTX paragraph. The renderer only receives prompt: never leave essential direction only in metadata.
Prefer 4–8 purposeful sentences over adjective lists. Resolution tags, 'masterpiece', 'award-winning', '8K'
and repetition are not substitutes for composition. Use an explicit subject, spatial relationships, motivated
lighting and tactile material details that fit the requested style. A quiet held frame is a valid beat.
For 3–5 seconds, use one action with a small reaction; for longer shots allow a simple ordered progression.
Avoid simultaneous complex hand interactions, transformations and camera orbits unless explicitly requested.
Place subjects in foreground/midground/background only when useful. Make cuts motivated by story or motion;
vary scale when useful, never for its own sake. Preserve screen direction, props, costume and light across cuts.
For image-conditioned shots, respect the supplied composition and focus on subsequent motion and sound.

For loops, design cyclical reversible action from the outline onward; the closing frame and motion phase must
match the opening, including camera, pose, framing and light. Avoid an irreversible story ending in a loop.
Use at least two clips for this studio's last-frame loop conditioning. The last act must know the opening shot.
Do not describe the next clip as remembering earlier prompts: each independent cut repeats essential anchors.
"""

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

Sound texture (LTX renders exactly the timbre you name): describe rain, wind, surf and traffic through concrete,
low- and mid-frequency sources — "heavy drops drumming on the wooden roof", "rain splashing into the lake", "deep
rolling thunder", "water lapping against stone", "a low gust pushing through the trees". Never call a sound
"hiss", "hissing", "static", "white noise" or "sizzle": the model then generates a thin high-frequency hiss that
sounds like a whine on phone speakers. Name the deepest, most physical sound first, the fine detail last.
Give ambience an intensity: "a loud, heavy downpour", "pounding rain". Words like "soft", "gentle", "faint" or
"quiet" on the main sound make LTX render a near-silent clip, which then drops out between louder shots; keep
loudness consistent across shots that should sound continuous (a distant thunder roll is a good shared anchor).

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

CONTINUITY BETWEEN SHOTS (the most common failure of AI films: every clip looks like a different movie):
- The video model renders every shot independently and remembers nothing. Everything that must stay the same
  has to be written again in every prompt: the WORLD ANCHOR sentence (location, time, weather, light logic,
  palette, lens; the studio inserts style.anchor verbatim into every prompt, so do not paraphrase it inside
  the prompt body) and every recurring character's full descriptor, word for word, every time they appear.
- Track STATE through direction.start and direction.end: where each character is, body position, what they
  hold, wet/dry, clean/dirty, injuries, clothing, visible emotion, where the light comes from, weather
  intensity, where the camera sits. direction.start of a shot MUST restate direction.end of the previous shot
  unless there is an explicit time or place jump, which the prompt must name ("Later that night, the same
  pier"). Props do not teleport, wounds do not heal, rain does not stop between shots.
- The first sentence of a prompt establishes the inherited state (who is in frame, pose, props, condition)
  before any new action starts.
- Keep the same camera language (lens feel, handheld vs locked) and grade across the whole piece unless the
  story motivates a change.

Continuity between clips (the studio handles this technically): if a shot is marked transition="continue",
the clip will start from the exact last frame of the previous clip, so its prompt must begin from the end state of
the previous action and continue the same camera setup or motivate a new move from it.
"""

KIND_PRESETS: dict[str, dict] = {
    "motion": {
        "label": "моушен-дизайн",
        "default_seconds": 15, "min_seconds": 6, "max_seconds": 90,
        "default_format": "16:9", "shot_seconds": (3, 8), "captions": False,
        "brief": "A designed graphic animation: a clear visual idea, controlled choreography and a readable final composition. "
                 "Use graphic objects rather than a dramatic character story. Each clip develops one main transformation.",
    },
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

MOTION_PROMPT_RULES = """\
MOTION DESIGN — specialize the film rules and JSON schemas above for graphic animation.
Plan a visual progression (establish, transform, resolve), not a character drama. Characters and locations may
be empty arrays. Keep the existing style fields: visual = 2D vector-like / 2.5D / 3D material treatment;
palette = named colors and their roles; lens = orthographic or perspective and depth; lighting = flat uniform
color for 2D or a coherent studio light for 3D; camera = locked framing by default; pace = motion rhythm.
Keep this design system consistent across clips. Do not introduce film grain, handheld shake, actors or
photographic lenses unless requested. The instruction to vary angles does not apply to graphic compositions.

For EVERY prompt describe:
1. Composition: background, exact small object count, shapes, materials, palette, scale and starting positions.
2. One dominant animation: object + concrete verb + direction/path + destination (slide, rotate, scale, unfold).
3. Timing: initially / then / finally within the supplied clip duration. Describe easing visibly: accelerates,
   decelerates, overshoots slightly and settles, or moves at constant speed. Stagger multiple objects clearly.
4. End state: explicitly say where objects settle or hold and what remains visible in the final composition.
5. Camera and sound: separate object motion from camera motion; finish with synchronized clicks, swishes,
   tonal pulses or deliberate silence. A flat-color design may use uniform flat lighting.
Prefer a small number of simple forms and one transformation over many simultaneous events. Preserve object
count, palette and material throughout, except for an explicitly planned transformation. Use natural language,
not animation software commands or cubic-bezier syntax. Relative phases should survive duration adjustment.
For continue transitions, repeat the previous end composition as the new start. For loops, return to the
initial positions, scale, orientation, lighting and motion phase, with compatible velocity across the seam.
Exact typography and brand marks belong in post-production: generate a clean reserved area instead of asking
the video model to draw lettering or a logo. Captions may use the studio caption field when enabled; it is
not a kinetic typography engine. Never promise pixel-exact geometry, timing or readable generated text.

Example of a single clip prompt:
A static orthographic wide shot frames three coral matte discs aligned along the left edge of an ivory
background, with generous empty space on the right. Uniform flat lighting keeps their colors solid and their
edges crisp. Initially the discs rest at equal vertical intervals. Then each disc slides horizontally toward
the center in a staggered sequence, the upper disc leading. Each accelerates gently, decelerates near its
destination and settles into a centered vertical stack with equal spacing. Finally the three discs hold
their final positions while the camera remains locked. A soft click accompanies each arrival; the sound
decays into silence during the final hold.
"""

STYLE_REFERENCE = """\
Style bible fields you must fill (short, concrete, reusable in every prompt):
- anchor: ONE sentence of 25-40 words, present tense, literal, that the studio pastes verbatim into every prompt:
  the location as the camera sees it, time of day, weather, light logic, palette, lens/grain feel (e.g. "A narrow
  wooden pier at night in a storm, black sea behind, lit only by a swinging brass lantern and distant lightning,
  cold teal shadows with warm amber highlights, shot on a 35mm cinema lens with fine grain.").
- visual: overall look in one sentence (e.g. "wet neon-lit Tokyo alleys shot on anamorphic lenses, cinematic realism").
- palette: 3-5 colors and how they are used.
- lens: focal length feel, depth of field, grain/texture.
- lighting: main light logic and time of day.
- camera: how the camera tends to move in this piece.
- sound: the sonic signature (ambience, materials, music mood if the studio adds music later).
- pace: cutting rhythm.
"""


SOUND_STUDIO_RULES = """\
SOUND STUDIO (active): the final soundtrack is NOT the video model's audio. The studio records every spoken line
with a dedicated TTS voice per character, re-animates the speaker's lips to that recording, generates Foley and
ambience from the finished picture with a video-to-audio model, and scores the film with a music model. So:
- Every spoken line goes into the shot's `dialogue` list: speaker = the character's name exactly as in
  `characters`, text in the dialogue language, `at` = seconds from the shot start when the line begins (leave
  0.6-1.2 s of stillness before it), `on_screen` = true only when the speaker's face is clearly visible in this
  shot (false for voices from off-screen or from behind). Keep each line short: 1-2 sentences, under ~4 s spoken.
  The same line stays quoted in the prompt as well, so the video model animates the speaking face.
- A character's `voice` is a casting note for a voice-design model, in English, one sentence: gender, age, timbre,
  pitch, pace and manner ("Woman in her late twenties, warm husky alto, slow sleepy delivery, slight smile in the
  voice"). The same voice is cloned in every shot, so describe the person, not the scene.
- `foley` (every shot, English, 8-25 words) lists only physical sounds and ambience the picture shows, deepest
  sound first, with intensity: "steady heavy rain on a tin roof, a ceramic cup set down on oak, distant traffic".
  No speech, no music, no "hiss".
- music.prompt describes the score for the music model in English: genre, instruments, tempo, mood arc
  ("sparse felt piano and warm cello, 70 bpm, quiet melancholy that brightens at the end"); music.bpm is a number.
  The score is instrumental and ducks under dialogue automatically.
"""
