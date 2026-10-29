"""Звуковая студия: голоса, фоли и музыка отдельными моделями и сведение по стемам.

LTX-2.5 рисует звук вместе с картинкой, и это его слабое место: речь неразборчива, голоса
персонажей меняются от сцены к сцене, шумы и эмбиент плоские. Поэтому:

1. Реплики (`shot.dialogue`) озвучиваются заранее: Qwen3-TTS на Pod (голос персонажа создаётся
   по описанию `characters[].voice` и потом клонируется во всех сценах) или ElevenLabs локально.
   Если реплика длиннее сцены, сцена удлиняется до рендера.
2. Видео рендерится как обычно; затем для говорящих в кадре LTX перерисовывает окно с репликой
   при замороженной дорожке голоса — губы двигаются под записанный текст.
3. Фоли и эмбиент генерирует видео-в-звук модель по готовому клипу (синхронно с картинкой).
4. Музыка — одна партитура в длину фильма, если в плане нет трека из библиотеки.
5. Сборка сводит стемы: голос, фоли, звук LTX (по умолчанию заглушён), музыка с ducking под речь.

Модуль без сторонних зависимостей: работает и локально, и на Pod.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re

from .schema import Line, Plan, Shot, clamp_seconds, is_conditioned

LINE_PAD = 0.35            # с: воздух после последней реплики до конца сцены
LIPSYNC_MARGIN = 0.3       # с: окно перерисовки губ шире реплик с обеих сторон
SOUND_DIR = "sound"
MANIFEST = "sound.json"

# Текст пробы голоса: VoiceDesign читает его выбранным голосом, проба потом клонируется.
REF_TEXT = {
    "ru": "Знаешь, я давно хотел тебе это сказать. Просто всё не было подходящего момента, а сейчас, кажется, он наступил.",
    "en": "You know, I've wanted to tell you this for a long time. There just never seemed to be the right moment, until now.",
}
DEFAULT_VOICE = "Adult speaker, natural clear voice, medium pitch, calm and expressive, close-miked, no background noise"


def _h(*parts) -> str:
    return hashlib.sha1(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()[:10]


def character(plan: Plan, name: str) -> dict:
    low = name.strip().lower()
    return next((c for c in plan.characters if str(c.get("name") or "").strip().lower() == low), {})


def voice_spec(plan: Plan, name: str) -> dict:
    """Описание голоса персонажа: строка `voice` или словарь {description, sample, elevenlabs_voice_id}."""
    v = character(plan, name).get("voice")
    if isinstance(v, dict):
        return {"description": str(v.get("description") or DEFAULT_VOICE), "sample": v.get("sample") or None,
                "elevenlabs_voice_id": v.get("elevenlabs_voice_id") or None}
    return {"description": str(v or DEFAULT_VOICE), "sample": None, "elevenlabs_voice_id": None}


def voice_key(plan: Plan, name: str) -> str:
    """Ключ голоса: одинаковое описание -> одна и та же проба (в сериале — во всех эпизодах)."""
    spec = voice_spec(plan, name)
    return f"{re.sub(r'[^a-z0-9]+', '_', name.lower()) or 'voice'}_{_h(spec['description'], spec['sample'], plan.language)}"


def line_name(plan: Plan, shot: Shot, index: int, engine: str) -> str:
    ln = shot.dialogue[index]
    spec = voice_spec(plan, ln.speaker)
    return f"line_{shot.id}_{index + 1}_{_h(engine, spec, ln.text, plan.language)}.wav"


def lines(plan: Plan) -> list[tuple[Shot, int, Line]]:
    return [(s, i, ln) for s in plan.shots for i, ln in enumerate(s.dialogue)]


def tts_job(plan: Plan, lines_dir: pathlib.Path, voices_dir: pathlib.Path, root: pathlib.Path | None = None) -> dict:
    """Задание для remote/audio/tts_worker.py (движок qwen)."""
    voices, items = {}, []
    lang = plan.language if plan.language in REF_TEXT else "en"
    for s, i, ln in lines(plan):
        spec = voice_spec(plan, ln.speaker)
        if ln.speaker not in voices:
            sample = spec["sample"]
            if sample and root is not None and not pathlib.Path(sample).is_absolute():
                sample = str(root / sample)
            voices[ln.speaker] = {"instruct": spec["description"], "ref_text": REF_TEXT[lang], "language": plan.language,
                                  "sample": sample, "cache": str(voices_dir / f"{voice_key(plan, ln.speaker)}.wav")}
        items.append({"voice": ln.speaker, "text": ln.text, "language": plan.language,
                      "out": str(lines_dir / line_name(plan, s, i, "qwen"))})
    return {"voices": voices, "lines": items}


def fit_dialogue(plan: Plan, durations: dict[tuple[str, int], float], high: bool) -> list[str]:
    """Двигает реплики, чтобы не накладывались, и удлиняет сцену под речь. Возвращает предупреждения."""
    notes = []
    for idx, s in enumerate(plan.shots):
        if not s.dialogue:
            continue
        cursor = 0.0
        for i, ln in enumerate(s.dialogue):
            dur = durations.get((s.id, i))
            if dur is None:
                continue
            ln.at = round(max(ln.at, cursor), 2)
            cursor = ln.at + dur + 0.15
        need = max((ln.at + durations[(s.id, i)] for i, ln in enumerate(s.dialogue) if (s.id, i) in durations),
                   default=0.0) + LINE_PAD
        if need > s.seconds:
            cap = clamp_seconds(need + 0.5, high, conditioned=is_conditioned(s, idx, plan.loop and idx == len(plan.shots) - 1))
            if cap < need:
                notes.append(f"сцена {s.id}: речь {need:.1f} с не помещается в максимум {cap:.1f} с — хвост реплики обрежется")
            notes.append(f"сцена {s.id}: удлинена {s.seconds:.2f} → {cap:.2f} с под реплики")
            s.seconds = cap
    return notes


def lipsync_window(shot: Shot, durations: dict[tuple[str, int], float]) -> tuple[float, float] | None:
    spans = [(ln.at, ln.at + durations[(shot.id, i)]) for i, ln in enumerate(shot.dialogue)
             if ln.on_screen and (shot.id, i) in durations]
    if not spans:
        return None
    return (round(max(0.0, min(a for a, _ in spans) - LIPSYNC_MARGIN), 3),
            round(min(shot.seconds, max(b for _, b in spans) + LIPSYNC_MARGIN), 3))


_QUOTED = re.compile(r"[\"“«][^\"”»]*[\"”»]")
_SPEECH = re.compile(r"\b(says?|said|whispers?|asks?|shouts?|murmurs?|replies|speaks?|voice|dialogue|in Russian|in English)\b", re.I)


def foley_prompt(shot: Shot) -> str:
    """Описание шумов для модели фоли: поле `foley` или звуковая часть промпта без речи."""
    if shot.foley:
        return shot.foley
    text = shot.prompt
    m = re.search(r"\bSound[s]?:\s*(.+)$", text, re.S)
    part = m.group(1) if m else " ".join(re.split(r"(?<=[.!?])\s+", text)[-2:])
    part = _QUOTED.sub("", part)
    pieces = [p.strip(" ,.;") for p in re.split(r"[,;]|\bthen\b|\band\b", part) if p.strip(" ,.;")]
    pieces = [p for p in pieces if not _SPEECH.search(p)]
    return (", ".join(pieces) or "subtle room tone matching the scene")[:300]


def score_caption(plan: Plan) -> str:
    s = plan.sound
    if s and s.score_prompt:
        return s.score_prompt
    mood = (plan.music.mood if plan.music and plan.music.mood else "") or (plan.style or {}).get("sound", "")
    return f"cinematic instrumental film score, {mood}".strip(", ")[:400]


def score_name(plan: Plan, seconds: float) -> str:
    s = plan.sound
    return f"score_{_h(score_caption(plan), round(seconds, 1), s.bpm if s else None, plan.seed)}.wav"


def foley_name(shot: Shot, clip: str) -> str:
    return f"foley_{shot.id}_{_h(foley_prompt(shot), pathlib.Path(clip).name)}.wav"


# ---------- манифест стемов (лежит в <film>/sound/sound.json, едет обратно с Pod) ----------
def load_manifest(sound_dir: pathlib.Path) -> dict:
    p = sound_dir / MANIFEST
    if not p.exists():
        return {"shots": {}, "score": None}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"shots": {}, "score": None}


def save_manifest(sound_dir: pathlib.Path, manifest: dict) -> None:
    sound_dir.mkdir(parents=True, exist_ok=True)
    (sound_dir / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")


def stems_for(plan: Plan, shot_id: str, sound_dir: pathlib.Path, manifest: dict,
              levels: dict | None = None) -> dict:
    """Стемы сцены для сборки: {'voices': [(файл, смещение, громкость)], 'foley': [...], 'model': громкость}."""
    snd = plan.sound
    if not snd:
        return {"voices": [], "foley": [], "model": 1.0}
    lv = {**snd.levels, **(levels or {})}
    entry = (manifest.get("shots") or {}).get(shot_id) or {}
    voices = [(str(sound_dir / x["file"]), float(x["at"]), float(lv.get("dialogue", 1.0)))
              for x in entry.get("lines") or [] if (sound_dir / x["file"]).exists()]
    foley = []
    if entry.get("foley") and (sound_dir / entry["foley"]).exists():
        foley = [(str(sound_dir / entry["foley"]), 0.0, float(lv.get("foley", 0.7)))]
    # без фоли звук LTX остаётся (иначе сцена онемеет); с репликами — без чужой «речи» модели
    model = float(lv.get("model", 0.0)) if foley else (0.15 if voices else 1.0)
    return {"voices": voices, "foley": foley, "model": model}
