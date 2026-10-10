"""Детерминированный линтер промптов LTX-2.5 (без LLM).

Возвращает список замечаний (level: error | warn). Используется планировщиком
для самопроверки и командой `studio review`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .schema import MAX_FRAMES_HIGH_CONDITIONED, MIN_SHOT_SECONDS, Plan, Shot, is_conditioned, max_frames, max_seconds

CAMERA_WORDS = re.compile(
    r"\b(shot|close-up|closeup|wide|medium|camera|pan(s|ning)?|tilt(s)?|dolly|tracking|static|handheld|crane|"
    r"push(es)?[- ]in|pull(s)?[- ]back|zoom|aerial|drone|over-the-shoulder|pov|low[- ]angle|high[- ]angle|"
    r"bird'?s[- ]eye|macro|insert|two-shot|profile|framing)\b", re.I)
SOUND_WORDS = re.compile(
    r"\b(sound|sounds|audio|hear|heard|ambien(t|ce)|music|wind|rain|footsteps|voice|says|whisper(s|ed)?|"
    r"silence|silent|hum(s|ming)?|rumble|crackle|creak(s|ing)?|roar|murmur|echo|rustle|splash|thunder|"
    r"breath(ing|s)?|laugh(s|ter)?|shout(s)?|sings?|clink|tick(ing)?|buzz|birds?|traffic|engine|bass|beat|"
    r"speaks?|dialogue|tone|sfx)\b", re.I)
TEXT_WORDS = re.compile(r"\b(text reads|sign (that )?says|caption|subtitle|title card|lettering|the words|"
                        r"written on|logo|watermark)\b", re.I)
NEGATIVE = re.compile(r"\b(no|without|don't|do not|never|avoid)\b", re.I)
SLUGLINE = re.compile(r"(^|\n)\s*(shot|scene|cut|frame)\s*\d*\s*[:\-]|^\s*[-*•]\s", re.I | re.M)
MOOD_ONLY = re.compile(r"\b(tense|eerie|dread|ominous|magical|epic|beautiful|stunning|cinematic masterpiece)\b", re.I)
LIGHT_WORDS = re.compile(r"\b(light|lit|glow|shadow|sun|neon|lamp|lantern|dusk|dawn|overcast|golden hour|"
                         r"backlit|rim light|moonlight|fluorescent|candle|flicker)\b", re.I)
PRONOUN_START = re.compile(r"^\s*(he|she|they|it|his|her|their)\b", re.I)
CYRILLIC = re.compile(r"[А-Яа-яЁё]")
QUOTE = re.compile(r"[\"“”«»]")
VOICE_WORDS = re.compile(r"\b(voice|says|speaks|whispers|shouts|murmurs|tone|accent|replies|asks|in (russian|english|"
                         r"french|spanish|german|japanese|italian))\b", re.I)


@dataclass
class Issue:
    shot_id: str
    level: str      # error | warn
    code: str
    message: str

    def __str__(self) -> str:
        return f"[{self.level}] сцена {self.shot_id} / {self.code}: {self.message}"


def word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9'’\-]+", text))


def lint_shot(shot: Shot, high: bool, known_characters: list[str] | None = None,
              descriptors: list[str] | None = None) -> list[Issue]:
    p = shot.prompt
    out: list[Issue] = []
    add = lambda level, code, msg: out.append(Issue(shot.id, level, code, msg))  # noqa: E731

    if CYRILLIC.search(p):
        if _cyrillic_only_in_quotes(p):
            if not re.search(r"\bin russian\b", p, re.I):
                add("warn", "language", "реплика на русском в кавычках — укажите язык речи ('says in Russian')")
        else:
            add("error", "language", "промпт должен быть на английском (кириллица допустима только внутри кавычек реплики)")
    n = word_count(p)
    if n < 45:
        add("error", "too_short", f"{n} слов — слишком мало, модель даст общее движение; нужно 70-180")
    elif n < 65:
        add("warn", "short", f"{n} слов — лучше 70-180, добавьте детали внешности, света и звука")
    elif n > 230:
        add("error", "too_long", f"{n} слов — слишком длинно, модель потеряет детали; максимум ~200")
    elif n > 200:
        add("warn", "long", f"{n} слов — лучше сократить до 200")
    if not CAMERA_WORDS.search(p):
        add("error", "no_camera", "нет описания кадра/камеры (shot size, movement)")
    if not SOUND_WORDS.search(p):
        add("error", "no_sound", "нет описания звука — LTX-2.5 генерирует аудио и придумает его сама")
    if not LIGHT_WORDS.search(p):
        add("warn", "no_light", "нет описания света/цвета")
    if SLUGLINE.search(p) or "\n" in p.strip():
        add("error", "formatting", "промпт должен быть одним абзацем без списков и 'Shot 1:'")
    if TEXT_WORDS.search(p):
        add("warn", "on_screen_text", "просьба нарисовать текст/надпись — LTX пишет текст нестабильно, уберите")
    if NEGATIVE.search(p):
        add("warn", "negative", "отрицания ('no', 'without') не работают — опишите, что ЕСТЬ в кадре")
    if PRONOUN_START.match(p):
        add("warn", "pronoun_start", "промпт начинается с местоимения — назовите персонажа его постоянным описанием")
    if MOOD_ONLY.search(p) and not SOUND_WORDS.search(p):
        add("warn", "mood_only", "абстрактное настроение без конкретного источника звука/движения")
    if QUOTE.search(p) and not VOICE_WORDS.search(p):
        add("warn", "dialogue_voice", "есть реплика, но не описан голос говорящего")
    if known_characters:
        for name in known_characters:
            if re.search(rf"\b{re.escape(name)}\b", p) and len(p) < 400 and not re.search(
                    rf"\b{re.escape(name)}\b[^.]*\b(with|wearing|in a|in an|whose|aged|year-old|haired)\b", p, re.I):
                add("warn", "character_descriptor",
                    f"персонаж «{name}» назван по имени без визуального описания — модель не знает имён")
    if shot.seconds < MIN_SHOT_SECONDS - 0.01 or shot.frames > max_frames(high):
        add("error", "duration", f"длительность {shot.seconds} с вне диапазона {MIN_SHOT_SECONDS:.0f}..{max_seconds(high):.0f} с")
    if descriptors and re.search(r"\b(he|she|they|her|his)\b", p, re.I) and not any(d.lower() in p.lower() for d in descriptors):
        add("warn", "descriptor_missing", "в промпте есть местоимение, но нет ни одного постоянного описания персонажа "
            "(descriptor) — модель не удержит внешность между сценами")
    if shot.caption and len(shot.caption) > 60:
        add("warn", "caption_long", "субтитр длиннее 60 символов — на телефоне не прочитать")
    return out


def _cyrillic_only_in_quotes(p: str) -> bool:
    outside = re.sub(r"[\"“«][^\"”»]*[\"”»]", "", p)
    return not CYRILLIC.search(outside)


def lint_plan(plan: Plan, default_quality: str = "fast") -> list[Issue]:
    high = plan.is_high(default_quality)
    names = [c.get("name", "") for c in plan.characters if c.get("name")]
    descriptors = [c.get("descriptor", "") for c in plan.characters if c.get("descriptor")]
    issues: list[Issue] = []
    for i, s in enumerate(plan.shots):
        issues += lint_shot(s, high, names, descriptors)
        if high and is_conditioned(s, i, plan.loop and i == len(plan.shots) - 1) and s.frames > MAX_FRAMES_HIGH_CONDITIONED:
            issues.append(Issue(s.id, "warn", "dfr_conditioned_length",
                                f"сцена со стартовым кадром длиннее 5 с ({s.seconds} с): DFR на ней падает, рендер пойдёт "
                                "distilled-пайплайном; для полного качества разбейте на сцены-продолжения по 5 с"))
    if plan.kind == "short":
        first = plan.shots[0]
        if first.seconds > 6:
            issues.append(Issue(first.id, "warn", "hook", "первая сцена шортса длиннее 6 с — зритель уйдёт"))
        if plan.captions.enabled and sum(1 for s in plan.shots if s.caption) < len(plan.shots) // 2:
            issues.append(Issue("*", "warn", "captions", "в шортсе включены субтитры, но заданы меньше чем у половины сцен"))
    if plan.kind == "film" and len({s.prompt.split(".")[0][:30] for s in plan.shots}) < max(2, len(plan.shots) // 2):
        issues.append(Issue("*", "warn", "variety", "сцены начинаются одинаково — разнообразьте крупность и ракурсы"))
    return issues


def errors_only(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.level == "error"]


def issues_by_shot(issues: list[Issue]) -> dict[str, list[Issue]]:
    by: dict[str, list[Issue]] = {}
    for i in issues:
        by.setdefault(i.shot_id, []).append(i)
    return by
