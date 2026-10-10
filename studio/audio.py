"""Звуковая библиотека (музыка, SFX) и закадровая озвучка.

Библиотека — папки assets/music и assets/sfx. Индекс assets/index.json с тегами
строится автоматически из имён файлов, его можно править руками: теги попадают
в промпт планировщику, и он выбирает трек/эффекты по настроению.
"""
from __future__ import annotations

import json
import pathlib
import re
import urllib.error
import urllib.request

from .schema import Plan

AUDIO_EXT = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".aiff", ".aif"}
STOP = {"the", "and", "of", "a", "an", "mix", "master", "final", "v1", "v2", "track", "audio", "sound", "sfx", "music",
        "loop", "free", "royalty"}


def _tags_from_name(name: str) -> list[str]:
    toks = re.split(r"[^a-zA-Zа-яА-Я0-9]+", pathlib.Path(name).stem.lower())
    return [t for t in toks if t and t not in STOP and not t.isdigit()][:12]


def _duration(path: pathlib.Path) -> float | None:
    try:
        from .assemble import probe
        return round(probe(path)["duration"], 1)
    except Exception:  # noqa: BLE001 — нет ffprobe или файл битый: индекс без длительности
        return None


def index_assets(assets_dir: pathlib.Path, with_duration: bool = True) -> dict:
    """Сканирует music/ и sfx/, сохраняет и возвращает индекс. Ручные теги сохраняются."""
    index_path = assets_dir / "index.json"
    old: dict = {}
    if index_path.exists():
        try:
            old = json.loads(index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            old = {}
    old_by_file = {e["file"]: e for kind in ("music", "sfx") for e in old.get(kind, [])}
    index: dict = {"music": [], "sfx": []}
    for kind in ("music", "sfx"):
        d = assets_dir / kind
        if not d.exists():
            continue
        for p in sorted(d.rglob("*")):
            if p.suffix.lower() not in AUDIO_EXT:
                continue
            rel = str(p.relative_to(assets_dir.parent)) if assets_dir.parent in p.parents else str(p)
            prev = old_by_file.get(rel, {})
            entry = {"file": rel, "tags": prev.get("tags") or _tags_from_name(p.name),
                     "mood": prev.get("mood", ""), "seconds": prev.get("seconds")}
            if with_duration and entry["seconds"] is None:
                entry["seconds"] = _duration(p)
            index[kind].append(entry)
    assets_dir.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    return index


def load_index(assets_dir: pathlib.Path) -> dict:
    p = assets_dir / "index.json"
    if not p.exists():
        return index_assets(assets_dir, with_duration=False) if assets_dir.exists() else {"music": [], "sfx": []}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"music": [], "sfx": []}


def library_summary(index: dict, limit: int = 60) -> str:
    """Короткое описание библиотеки для промпта планировщика."""
    parts = []
    for kind, title in (("music", "MUSIC TRACKS"), ("sfx", "SOUND EFFECTS")):
        items = index.get(kind) or []
        if not items:
            continue
        rows = []
        for e in items[:limit]:
            dur = f", {e['seconds']}s" if e.get("seconds") else ""
            mood = f" — {e['mood']}" if e.get("mood") else ""
            rows.append(f"- {e['file']} [{', '.join(e.get('tags') or [])}{dur}]{mood}")
        parts.append(title + ":\n" + "\n".join(rows))
    return "\n\n".join(parts) if parts else "(library is empty)"


def resolve_asset(file: str | None, root: pathlib.Path) -> pathlib.Path | None:
    if not file:
        return None
    p = pathlib.Path(file)
    if not p.is_absolute():
        p = root / p
    return p if p.exists() else None


# ---------- озвучка ----------
class TTSError(RuntimeError):
    pass


def tts_elevenlabs(text: str, out_path: pathlib.Path, api_key: str, voice_id: str,
                   model_id: str = "eleven_multilingual_v2") -> pathlib.Path:
    """Text-to-speech через ElevenLabs REST API. Возвращает путь к mp3."""
    if not api_key or not voice_id:
        raise TTSError("не заданы elevenlabs_api_key / elevenlabs_voice_id в film_config.json")
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128"
    body = json.dumps({"text": text, "model_id": model_id}).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "xi-api-key": api_key, "Content-Type": "application/json", "Accept": "audio/mpeg"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
    except urllib.error.HTTPError as e:
        raise TTSError(f"ElevenLabs вернул {e.code}: {e.read().decode(errors='replace')[:300]}") from e
    except urllib.error.URLError as e:
        raise TTSError(f"нет связи с ElevenLabs: {e}") from e
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    return out_path


def prepare_narration(plan: Plan, cfg: dict, out_dir: pathlib.Path, log=print) -> dict[str, str]:
    """Генерирует озвучку для сцен с `narration`. Возвращает {shot_id: путь}. Без ключа — пропускает."""
    shots = [s for s in plan.shots if s.narration]
    if not shots:
        return {}
    key, voice = cfg.get("elevenlabs_api_key"), cfg.get("elevenlabs_voice_id")
    if not key or not voice:
        log(f"Озвучка: {len(shots)} сцен с narration, но ElevenLabs не настроен — текст останется только в плане")
        return {}
    result: dict[str, str] = {}
    for s in shots:
        out = out_dir / f"narration_{s.id}.mp3"
        if not out.exists():
            log(f"Озвучка сцены {s.id}: {s.narration[:60]}…")
            tts_elevenlabs(s.narration, out, key, voice, cfg.get("elevenlabs_model", "eleven_multilingual_v2"))
        result[s.id] = str(out)
    return result
