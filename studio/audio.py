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
                   model_id: str = "eleven_multilingual_v2", wav: bool = False,
                   language: str | None = None) -> pathlib.Path:
    """Text-to-speech через ElevenLabs REST API. Возвращает путь к mp3 (или WAV при wav=True)."""
    if not api_key or not voice_id:
        raise TTSError("не заданы elevenlabs_api_key / elevenlabs_voice_id в film_config.json")
    # PCM доступен только с тарифа Pro, поэтому всегда берём MP3, а WAV при необходимости делаем ffmpeg
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128"
    body = json.dumps({"text": text, "model_id": model_id} | ({"language_code": language} if language else {})).encode()
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
    if wav:
        import subprocess
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "mp3", "-i", "pipe:0", "-ar", "48000",
                            str(out_path)], input=data, capture_output=True)
        if r.returncode != 0:
            raise TTSError(f"не удалось перекодировать ответ ElevenLabs: {r.stderr.decode(errors='replace')[:200]}")
    else:
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


ELEVEN_MODEL = "eleven_v4"          # самая эмоциональная модель ElevenLabs (2026-10), русский поддерживается
ELEVEN_DESIGN_MODEL = "eleven_ttv_v3"


def _eleven(path: str, key: str, body: dict, timeout: int = 180) -> dict:
    req = urllib.request.Request("https://api.elevenlabs.io" + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"xi-api-key": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise TTSError(f"ElevenLabs вернул {e.code}: {e.read().decode(errors='replace')[:300]}") from e
    except urllib.error.URLError as e:
        raise TTSError(f"нет связи с ElevenLabs: {e}") from e


def elevenlabs_design_voice(key: str, name: str, description: str, sample_text: str) -> str:
    """Голос по текстовому описанию (Voice Design): первая проба сохраняется в аккаунт, возвращается voice_id.
    Занимает один слот собственных голосов аккаунта."""
    res = _eleven("/v1/text-to-voice/design", key, {"voice_description": description[:1000], "text": sample_text,
                                                    "model_id": ELEVEN_DESIGN_MODEL})
    previews = res.get("previews") or []
    if not previews:
        raise TTSError("ElevenLabs не вернул ни одной пробы голоса")
    saved = _eleven("/v1/text-to-voice", key, {"voice_name": name[:40], "voice_description": description[:1000],
                                               "generated_voice_id": previews[0]["generated_voice_id"]})
    return saved["voice_id"]


def elevenlabs_voice(plan: Plan, speaker: str, cfg: dict, cache_path: pathlib.Path, log=print) -> str | None:
    """voice_id персонажа: явно заданный, ранее созданный по тому же описанию (кэш) или новый из Voice Design."""
    from . import sound
    spec = sound.voice_spec(plan, speaker)
    if spec["elevenlabs_voice_id"]:
        return spec["elevenlabs_voice_id"]
    key = sound.voice_key(plan, speaker)
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    if key in cache:
        return cache[key]
    lang = plan.language if plan.language in sound.REF_TEXT else "en"
    try:
        log(f"Голоса: создаю голос ElevenLabs для «{speaker}» — {spec['description'][:70]}")
        voice = elevenlabs_design_voice(cfg["elevenlabs_api_key"], f"{plan.series or plan.slug} {speaker}",
                                        spec["description"], sound.REF_TEXT[lang])
    except TTSError as e:
        log(f"Голоса: не удалось создать голос для «{speaker}» ({e})")
        return cfg.get("elevenlabs_voice_id")
    cache[key] = voice
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    return voice


def eleven_text(text: str, delivery: str | None, model: str) -> str:
    """v3/v4 понимают теги подачи в квадратных скобках: «[warmly, teasing] Ну и я с тобой подожду.»"""
    return f"[{delivery}] {text}" if delivery and model.startswith(("eleven_v3", "eleven_v4")) else text


def prepare_dialogue(plan: Plan, cfg: dict, out_dir: pathlib.Path, log=print,
                     cache_path: pathlib.Path | None = None) -> int:
    """Реплики звуковой студии через ElevenLabs (если выбран этот движок) — локально, до загрузки на Pod.

    Голос персонажа: `characters[].voice.elevenlabs_voice_id`, иначе созданный по описанию `voice` (Voice Design,
    один раз — дальше из кэша), иначе общий `elevenlabs_voice_id` из конфига. Чего не удалось озвучить здесь,
    Pod озвучит Qwen3-TTS. Возвращает число готовых реплик.
    """
    from . import sound
    if not plan.sound or plan.sound.voices != "elevenlabs" or not sound.lines(plan):
        return 0
    key = cfg.get("elevenlabs_api_key")
    if not key:
        log("Голоса: выбран ElevenLabs, но нет elevenlabs_api_key — реплики озвучит Qwen3-TTS на Pod")
        return 0
    cache_path = cache_path or pathlib.Path(cfg.get("_root", ".")) / ".studio" / "elevenlabs_voices.json"
    model = cfg.get("elevenlabs_model", ELEVEN_MODEL)
    voices: dict[str, str | None] = {}
    ready = 0
    for s, i, ln in sound.lines(plan):
        if ln.speaker not in voices:
            voices[ln.speaker] = elevenlabs_voice(plan, ln.speaker, cfg, cache_path, log)
        voice = voices[ln.speaker]
        if not voice:
            log(f"Голоса: для «{ln.speaker}» нет голоса ElevenLabs — реплику озвучит Qwen3-TTS")
            continue
        out = out_dir / sound.line_name(plan, s, i, "elevenlabs")
        if not out.exists():
            log(f"Голоса: {ln.speaker} — «{ln.text[:50]}»" + (f" [{ln.delivery}]" if ln.delivery else ""))
            try:
                tts_elevenlabs(eleven_text(ln.text, ln.delivery, model), out, key, voice, model, wav=True,
                               language=plan.language)
            except TTSError as e:
                log(f"Голоса: реплику не озвучить через ElevenLabs ({e}) — её озвучит Qwen3-TTS")
                continue
        ready += 1
    return ready
