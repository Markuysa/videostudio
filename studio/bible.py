"""Библия сериала: персонажи, локации, стиль, арка сезона, журнал эпизодов.

Хранится в series/<slug>/bible.json. Планировщик эпизодов читает её и обязан
повторять описания персонажей слово в слово — так LTX держит идентичность.
"""
from __future__ import annotations

import json
import pathlib
import time

from .knowledge import STYLE_REFERENCE
from .llm import LLM
from .schema import slugify

BIBLE_SYSTEM = """\
You are the showrunner and head of story of an AI-generated short-form series. The series will be rendered by the
LTX-2.5 video model shot by shot, so every character and location needs a compact VISUAL DESCRIPTOR: one phrase
(8-20 words) that will be pasted verbatim into every prompt where they appear ("a wiry 60-year-old fisherman with a
wet grey beard, yellow oilskin coat and a brass lantern"). Descriptors must be concrete (age, build, hair, clothing,
colors, props) and distinctive, never names alone: the video model does not know names.

Return JSON:
{
 "title": str, "premise": str (2-3 sentences), "tone": str, "genre": str,
 "style": {"visual": str, "palette": str, "lens": str, "lighting": str, "camera": str, "sound": str, "pace": str},
 "characters": [{"name": str, "descriptor": str, "description": str, "voice": str, "arc": str}],
 "locations": [{"name": str, "descriptor": str}],
 "sound_signature": str,
 "season_arc": [str, ...]   // one line per planned episode, escalating, with a finale
}
""" + "\n" + STYLE_REFERENCE


def series_dir(root: pathlib.Path, slug: str) -> pathlib.Path:
    return root / slug


def load_bible(root: pathlib.Path, slug: str) -> dict:
    p = series_dir(root, slug) / "bible.json"
    if not p.exists():
        raise FileNotFoundError(f"нет библии сериала {slug}: {p}. Создайте: studio series new \"описание\" --name {slug}")
    return json.loads(p.read_text(encoding="utf-8"))


def save_bible(root: pathlib.Path, bible: dict) -> pathlib.Path:
    d = series_dir(root, bible["slug"])
    d.mkdir(parents=True, exist_ok=True)
    p = d / "bible.json"
    p.write_text(json.dumps(bible, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def create_bible(llm: LLM, description: str, slug: str | None, episodes: int, language: str, prefs: str = "") -> dict:
    user = (f"Series concept from the producer (may be in Russian): {description}\n\n"
            f"Plan {episodes} episodes. Dialogue language: {language}. "
            f"Write title/premise/tone/arc in the producer's language, but descriptors, style and sound in English "
            f"(they go into video prompts).\n")
    if prefs:
        user += f"\nProducer's standing preferences:\n{prefs}\n"
    data = llm.complete_json(BIBLE_SYSTEM, user)
    data["slug"] = slug or slugify(data.get("title", "series"))
    data.setdefault("episodes", [])
    data.setdefault("notes", [])
    data["created"] = time.strftime("%Y-%m-%d")
    data["language"] = language
    return data


def bible_summary(bible: dict) -> str:
    """Текст библии для системного промпта планировщика."""
    lines = [f"SERIES: {bible.get('title')} — {bible.get('premise')}", f"Tone/genre: {bible.get('tone')} / {bible.get('genre')}",
             "STYLE: " + json.dumps(bible.get("style", {}), ensure_ascii=False),
             f"SOUND SIGNATURE: {bible.get('sound_signature')}", "CHARACTERS (use descriptor verbatim):"]
    for c in bible.get("characters", []):
        lines.append(f"- {c.get('name')}: \"{c.get('descriptor')}\" — {c.get('description')} Voice: {c.get('voice')}. Arc: {c.get('arc')}")
    lines.append("LOCATIONS:")
    for loc in bible.get("locations", []):
        lines.append(f"- {loc.get('name')}: \"{loc.get('descriptor')}\"")
    if bible.get("season_arc"):
        lines.append("SEASON ARC:")
        lines += [f"  {i + 1}. {a}" for i, a in enumerate(bible["season_arc"])]
    if bible.get("episodes"):
        lines.append("EPISODES ALREADY MADE (continuity!):")
        lines += [f"  Ep {e.get('episode')}: {e.get('title')} — {e.get('summary') or e.get('logline')}" for e in bible["episodes"]]
    if bible.get("notes"):
        lines.append("CONTINUITY NOTES: " + " | ".join(bible["notes"]))
    return "\n".join(lines)


def log_episode(bible: dict, plan_dict: dict) -> None:
    n = plan_dict.get("episode") or len(bible.get("episodes", [])) + 1
    bible.setdefault("episodes", [])
    bible["episodes"] = [e for e in bible["episodes"] if e.get("episode") != n]
    bible["episodes"].append({"episode": n, "slug": plan_dict.get("slug"), "title": plan_dict.get("title"),
                              "logline": plan_dict.get("logline"), "summary": plan_dict.get("synopsis"),
                              "date": time.strftime("%Y-%m-%d")})
    bible["episodes"].sort(key=lambda e: e["episode"])
