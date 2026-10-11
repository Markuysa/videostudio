"""Схема плана фильма, валидация и арифметика кадров LTX-2.5.

План — обычный JSON. Версия 1 (как plans/storm.json) читается и автоматически
приводится к версии 2.
"""
from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass, field, asdict
from typing import Any

FPS = 24
# Быстрый режим (distilled): стороны кратны 32. Высокий (DFR): кратны 64.
SIZES_FAST = {"16:9": (1280, 704), "9:16": (704, 1280), "1:1": (960, 960), "4:5": (896, 1120), "21:9": (1536, 640)}
SIZES_HIGH = {"16:9": (1920, 1088), "9:16": (1088, 1920), "1:1": (1088, 1088), "4:5": (1024, 1280), "21:9": (1920, 832)}
FORMATS = tuple(SIZES_FAST)
KINDS = ("short", "aesthetic", "film", "episode", "motion")
TRANSITIONS = ("cut", "continue", "dissolve")
QUALITIES = ("fast", "high")

MIN_SHOT_SECONDS = 3.0
MAX_FRAMES_HIGH = 241          # DFR: одно окно (10 с)
# DFR с входным кадром (continue / image) падает в keyframe-декодере на 193+ кадрах
# (проверено 2026-10-10 на RTX PRO 6000: 121 кадр — ок при силе 0.8 и 1.0, 193 — CUBLAS/illegal memory access).
MAX_FRAMES_HIGH_CONDITIONED = 121
MAX_FRAMES_FAST = 481          # distilled: окна по 97 кадров (--chunked), 20 с
MAX_SINGLE_WINDOW_FRAMES = 241


def frames_for(seconds: float) -> int:
    """LTX: число кадров вида 8k+1. Округляем к ближайшему допустимому, минимум 9."""
    n = int(round(float(seconds) * FPS))
    k = max(1, int(round((n - 1) / 8)))
    return 8 * k + 1


def seconds_for(frames: int) -> float:
    return round(frames / FPS, 3)


def snap_seconds(seconds: float) -> float:
    return seconds_for(frames_for(seconds))


def max_frames(high: bool) -> int:
    return MAX_FRAMES_HIGH if high else MAX_FRAMES_FAST


def max_seconds(high: bool) -> float:
    return seconds_for(max_frames(high))


MAX_SHOT_SECONDS_HIGH = seconds_for(MAX_FRAMES_HIGH)   # 10.042
MAX_SHOT_SECONDS_FAST = seconds_for(MAX_FRAMES_FAST)   # 20.042


def clamp_seconds(seconds: float, high: bool, conditioned: bool = False) -> float:
    """Снап к сетке 8k+1 так, чтобы остаться в пределах [MIN_SHOT_SECONDS, max для режима].

    conditioned=True — сцена со стартовым кадром (continue/image): в high ограничена 121 кадром.
    """
    cap = min(max_frames(high), MAX_FRAMES_HIGH_CONDITIONED) if (high and conditioned) else max_frames(high)
    frames = max(frames_for(MIN_SHOT_SECONDS), min(cap, frames_for(seconds)))
    return seconds_for(frames)


def is_conditioned(shot: "Shot", index: int, loop_last: bool = False) -> bool:
    """Сцена со стартовым (или, для лупа, финальным) кадром-условием."""
    return bool(shot.image) or (index > 0 and shot.transition == "continue") or loop_last


def slugify(text: str, fallback: str = "film") -> str:
    tr = str.maketrans("абвгдеёжзийклмнопрстуфхцчшщъыьэюя", "abvgdeejzijklmnoprstufhccss_y_eua")
    s = text.lower().translate(tr)
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s[:40] or fallback


class PlanError(ValueError):
    pass


@dataclass
class Sfx:
    file: str
    offset: float = 0.0        # секунды от начала сцены
    volume: float = 0.8

    @staticmethod
    def from_dict(d: dict) -> "Sfx":
        return Sfx(file=str(d["file"]), offset=float(d.get("offset", 0)), volume=float(d.get("volume", 0.8)))


@dataclass
class Shot:
    id: str
    seconds: float
    prompt: str
    transition: str = "cut"            # как сцена соединяется с ПРЕДЫДУЩЕЙ: cut | continue | dissolve
    transition_seconds: float = 0.5    # длина наплыва для dissolve
    image: str | None = None           # свой стартовый кадр (путь)
    image_strength: float = 1.0
    caption: str | None = None         # субтитр/плашка на экране (для шортсов)
    narration: str | None = None       # закадровый текст (озвучка TTS, если настроена)
    sfx: list[Sfx] = field(default_factory=list)
    beat: str | None = None            # короткое описание смысла сцены (для людей и LLM)
    notes: str | None = None
    direction: dict = field(default_factory=dict)  # постановка: start/action/camera/end, не текст для рендера

    @property
    def frames(self) -> int:
        return frames_for(self.seconds)

    @staticmethod
    def from_dict(d: dict, index: int) -> "Shot":
        if "prompt" not in d or not str(d["prompt"]).strip():
            raise PlanError(f"сцена #{index + 1}: пустой prompt")
        transition = str(d.get("transition") or ("continue" if d.get("continue") else "cut")).lower()
        if transition not in TRANSITIONS:
            raise PlanError(f"сцена #{index + 1}: transition должен быть одним из {TRANSITIONS}, а не {transition!r}")
        return Shot(
            id=str(d.get("id") or f"{index + 1:03d}"),
            seconds=float(d.get("seconds", 8)),
            prompt=str(d["prompt"]).strip(),
            transition=transition,
            transition_seconds=float(d.get("transition_seconds", 0.5)),
            image=d.get("image") or None,
            image_strength=float(d.get("image_strength", 1.0)),
            caption=(str(d["caption"]).strip() or None) if d.get("caption") else None,
            narration=(str(d["narration"]).strip() or None) if d.get("narration") else None,
            sfx=[Sfx.from_dict(x) for x in (d.get("sfx") or [])],
            beat=d.get("beat") or None,
            notes=d.get("notes") or None,
            direction=dict(d.get("direction") or {}),
        )


@dataclass
class Music:
    file: str | None = None
    volume: float = 0.25
    duck: bool = True              # приглушать под речь
    fade_in: float = 1.0
    fade_out: float = 2.5
    mood: str | None = None

    @staticmethod
    def from_dict(d: Any) -> "Music | None":
        if not d:
            return None
        if isinstance(d, str):
            return Music(file=d)
        return Music(file=d.get("file") or None, volume=float(d.get("volume", 0.25)), duck=bool(d.get("duck", True)),
                     fade_in=float(d.get("fade_in", 1.0)), fade_out=float(d.get("fade_out", 2.5)), mood=d.get("mood"))


@dataclass
class Captions:
    enabled: bool = False
    position: str = "bottom"   # bottom | center
    font_size: int = 0         # 0 = авто от высоты кадра

    @staticmethod
    def from_dict(d: Any) -> "Captions":
        if d is None:
            return Captions()
        if isinstance(d, bool):
            return Captions(enabled=d)
        return Captions(enabled=bool(d.get("enabled", True)), position=str(d.get("position", "bottom")),
                        font_size=int(d.get("font_size", 0)))


@dataclass
class Plan:
    title: str
    shots: list[Shot]
    slug: str = ""
    kind: str = "film"
    format: str = "16:9"
    quality: str | None = None
    seed: int = 1234
    language: str = "ru"
    logline: str | None = None
    synopsis: str | None = None
    style: dict = field(default_factory=dict)
    characters: list[dict] = field(default_factory=list)
    locations: list[dict] = field(default_factory=list)
    series: str | None = None
    episode: int | None = None
    music: Music | None = None
    captions: Captions = field(default_factory=Captions)
    fade_in: float = 0.5
    fade_out: float = 1.5
    loop: bool = False               # бесшовный луп: последняя сцена заканчивается первым кадром фильма
    audio: str = "raw"               # raw — звук модели как есть; leveled — выравнивание сцен и громкости (-14 LUFS)
    request: str | None = None
    version: int = 2
    source_path: str | None = None
    creative_brief: dict = field(default_factory=dict)
    review_notes: list[str] = field(default_factory=list)

    # ---------- производные ----------
    @property
    def total_seconds(self) -> float:
        total = 0.0
        for i, s in enumerate(self.shots):
            total += snap_seconds(s.seconds)
            if i > 0 and s.transition == "dissolve":
                total -= s.transition_seconds
            if i > 0 and s.transition == "continue":
                total -= 1 / FPS
        return round(total, 2)

    def is_high(self, default_quality: str = "fast") -> bool:
        return str(self.quality or default_quality).lower() == "high"

    def size(self, high: bool) -> tuple[int, int]:
        return (SIZES_HIGH if high else SIZES_FAST)[self.format]

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("source_path", None)
        if not d.get("loop"):
            d.pop("loop", None)
        if d.get("audio") == "raw":
            d.pop("audio", None)
        d["shots"] = [{k: v for k, v in asdict(s).items() if v not in (None, [], "")} | {"seconds": s.seconds}
                      for s in self.shots]
        for s in d["shots"]:
            if s.get("transition") == "cut":
                s.pop("transition_seconds", None)
            if s.get("image_strength") == 1.0:
                s.pop("image_strength", None)
        d["music"] = asdict(self.music) if self.music else None
        d["captions"] = asdict(self.captions)
        return {k: v for k, v in d.items() if v is not None}

    def save(self, path: pathlib.Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
        self.source_path = str(path)

    @staticmethod
    def from_dict(d: dict, source_path: str | None = None) -> "Plan":
        if not isinstance(d, dict):
            raise PlanError("план должен быть JSON-объектом")
        shots_raw = d.get("shots")
        if not shots_raw or not isinstance(shots_raw, list):
            raise PlanError("в плане нет сцен (shots)")
        shots = [Shot.from_dict(s, i) for i, s in enumerate(shots_raw)]
        fmt = str(d.get("format", "16:9"))
        if fmt not in FORMATS:
            raise PlanError(f"формат {fmt!r} не поддерживается, доступны: {', '.join(FORMATS)}")
        kind = str(d.get("kind", "film"))
        if kind not in KINDS:
            raise PlanError(f"kind {kind!r} не поддерживается, доступны: {', '.join(KINDS)}")
        quality = d.get("quality")
        if quality is not None and str(quality).lower() not in QUALITIES:
            raise PlanError(f"quality должен быть fast или high, а не {quality!r}")
        title = str(d.get("title") or (pathlib.Path(source_path).stem if source_path else "film"))
        plan = Plan(
            title=title, shots=shots,
            slug=str(d.get("slug") or slugify(pathlib.Path(source_path).stem if source_path else title)),
            kind=kind, format=fmt,
            quality=str(quality).lower() if quality else None, seed=int(d.get("seed", 1234)),
            language=str(d.get("language", "ru")), logline=d.get("logline"), synopsis=d.get("synopsis"),
            style=dict(d.get("style") or {}), characters=list(d.get("characters") or []),
            locations=list(d.get("locations") or []), series=d.get("series"), episode=d.get("episode"),
            music=Music.from_dict(d.get("music")), captions=Captions.from_dict(d.get("captions")),
            fade_in=float(d.get("fade_in", 0.5)), fade_out=float(d.get("fade_out", 1.5)),
            loop=bool(d.get("loop", False)), audio=str(d.get("audio") or "raw").lower(), request=d.get("request"), version=int(d.get("version", 1)), source_path=source_path,
            creative_brief=dict(d.get("creative_brief") or {}), review_notes=list(d.get("review_notes") or []),
        )
        if plan.music and d.get("music_volume") is not None:   # совместимость с версией 1
            plan.music.volume = float(d["music_volume"])
        plan.version = 2
        return plan


def load_plan(path: str | pathlib.Path) -> Plan:
    p = pathlib.Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise PlanError(f"{p.name}: невалидный JSON ({e})") from e
    return Plan.from_dict(data, source_path=str(p))


def validate(plan: Plan, default_quality: str = "fast") -> list[str]:
    """Жёсткие проблемы, с которыми рендерить нельзя (или бессмысленно)."""
    problems: list[str] = []
    high = plan.is_high(default_quality)
    if plan.audio not in ("raw", "leveled"):
        problems.append(f"audio должен быть raw или leveled, а не {plan.audio!r}")
    if plan.loop and len(plan.shots) < 2:
        problems.append("для замыкания лупа нужны минимум две сцены")
    ids = [s.id for s in plan.shots]
    if len(set(ids)) != len(ids):
        problems.append("id сцен повторяются")
    for s in plan.shots:
        if s.seconds < MIN_SHOT_SECONDS - 0.01:
            problems.append(f"сцена {s.id}: {s.seconds} с — короче {MIN_SHOT_SECONDS} с")
        if s.frames > max_frames(high):
            problems.append(f"сцена {s.id}: {s.seconds} с — длиннее {max_seconds(high):.0f} с для режима {'high' if high else 'fast'}")
        if s.transition == "dissolve" and not (0.2 <= s.transition_seconds <= min(2.0, s.seconds / 2)):
            problems.append(f"сцена {s.id}: transition_seconds={s.transition_seconds} вне диапазона 0.2..2.0")
        if len(s.prompt) < 20:
            problems.append(f"сцена {s.id}: промпт слишком короткий")
    if plan.shots and plan.shots[0].transition != "cut":
        plan.shots[0].transition = "cut"
    return problems


def normalize_durations(plan: Plan) -> None:
    """Приводит длительности сцен к сетке кадров LTX (8k+1)."""
    for s in plan.shots:
        s.seconds = snap_seconds(s.seconds)
