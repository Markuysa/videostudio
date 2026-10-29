"""Pod-сторона звуковой студии: реплики -> (рендер видео) -> липсинк -> фоли -> музыка.

Каждая модель живёт в своём окружении (remote/audio/install.sh) и запускается отдельным процессом,
поэтому видеокарта целиком достаётся то LTX, то звуковой модели. Всё кэшируется в <film>/sound:
повторный запуск не пересчитывает готовые стемы.

Переменные окружения для проверки без GPU:
  TTS_TEST_CMD / FOLEY_TEST_CMD / MUSIC_TEST_CMD — команда вместо воркера (получает путь к job.json)
"""
from __future__ import annotations

import json
import os
import pathlib
import shlex
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from studio import sound as S  # noqa: E402
from studio.assemble import measure_loudness  # noqa: E402
from studio.schema import FPS, Plan  # noqa: E402

AUDIO = os.environ.get("AUDIO_ROOT", "/workspace/audio")
HERE = pathlib.Path(__file__).resolve().parent / "audio"
WORKERS = {
    "tts": (f"{AUDIO}/tts/venv/bin/python", HERE / "tts_worker.py", "TTS_TEST_CMD"),
    "foley": (f"{AUDIO}/foley/venv/bin/python", HERE / "foley_worker.py", "FOLEY_TEST_CMD"),
    "music": (f"{AUDIO}/music/ACE-Step-1.5/.venv/bin/python", HERE / "music_worker.py", "MUSIC_TEST_CMD"),
}
VOICES_DIR = pathlib.Path(os.environ.get("VOICES_DIR", "/workspace/film/voices"))
# Целевая громкость стемов до сведения. Модели отдают от −43 (фоли тихой сцены) до −17 LUFS (музыка),
# поэтому каждый стем приводится к своей цели постоянным усилением с true-peak лимитером.
TARGETS = {"dialogue": (-20.0, 15.0), "foley": (-24.0, 20.0), "music": (-20.0, 10.0)}   # (LUFS, макс. подъём дБ)


def log(msg: str) -> None:
    print(time.strftime("[%H:%M:%S] ") + msg, flush=True)


def _run(cmd: list[str], logf, env: dict | None = None) -> int:
    logf.write("\n$ " + " ".join(shlex.quote(c) for c in cmd) + "\n")
    logf.flush()
    return subprocess.call(cmd, stdout=logf, stderr=subprocess.STDOUT, env={**os.environ, **(env or {})})


def ensure_installed(kinds: list[str], logf) -> list[str]:
    """Ставит недостающие окружения. Возвращает список доступных."""
    missing = [k for k in kinds if not os.environ.get(WORKERS[k][2]) and not os.path.exists(WORKERS[k][0])]
    if missing:
        log(f"Звуковая студия: ставлю {', '.join(missing)} (первый раз 10-20 минут)")
        _run(["bash", str(HERE / "install.sh"), *missing], logf)
    return [k for k in kinds if os.environ.get(WORKERS[k][2]) or os.path.exists(WORKERS[k][0])]


def worker(kind: str, job: dict, job_path: pathlib.Path, logf) -> bool:
    job_path.parent.mkdir(parents=True, exist_ok=True)
    job_path.write_text(json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8")
    py, script, test_env = WORKERS[kind]
    cmd = shlex.split(os.environ[test_env]) + [str(job_path)] if os.environ.get(test_env) else [py, str(script), str(job_path)]
    return _run(cmd, logf, env={"HF_HOME": "/workspace/hf-home"}) == 0


def level_stem(path: pathlib.Path, kind: str, logf) -> None:
    """Приводит свежесгенерированный стем к целевой громкости (на месте, один раз)."""
    target, max_boost = TARGETS[kind]
    lufs = measure_loudness(path)
    if lufs is None:
        return
    gain = max(-20.0, min(max_boost, target - lufs))
    if abs(gain) < 0.5:
        return
    tmp = path.with_name(path.stem + ".lvl.wav")
    code = _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(path), "-af",
                 f"volume={gain:+.2f}dB,alimiter=limit=0.891:attack=5:release=80:level=false", "-ar", "48000",
                 str(tmp)], logf)
    if code == 0 and tmp.exists():
        tmp.replace(path)
        logf.write(f"# {kind} {path.name}: {lufs:.1f} LUFS -> {gain:+.1f} dB\n")


def duration(path: pathlib.Path) -> float | None:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None


def prepare_dialogue(plan: Plan, proj: pathlib.Path, assets_dir: pathlib.Path, high: bool, logf) -> dict:
    """Озвучивает реплики до рендера видео и подгоняет длину сцен. Возвращает {(shot, i): секунды}."""
    if not plan.sound or not S.lines(plan):
        return {}
    sound_dir = proj / S.SOUND_DIR
    lines_dir = sound_dir / "lines"
    lines_dir.mkdir(parents=True, exist_ok=True)
    engine = plan.sound.voices
    if engine == "elevenlabs":
        # реплики ElevenLabs озвучены локально до загрузки (ключ API на Pod не едет)
        for s, i, _ in S.lines(plan):
            src = assets_dir / S.line_name(plan, s, i, "elevenlabs")
            dst = lines_dir / S.line_name(plan, s, i, "qwen")
            if src.exists() and not dst.exists():
                subprocess.call(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-ar", "48000", str(dst)])
        missing = [(s, i) for s, i, _ in S.lines(plan) if not (lines_dir / S.line_name(plan, s, i, "qwen")).exists()]
        if missing:
            log(f"Голоса: {len(missing)} реплик ElevenLabs не пришли с компьютера — озвучиваю их Qwen3-TTS")
            engine = "qwen"
    if engine == "qwen" and ensure_installed(["tts"], logf):
        voices_dir = VOICES_DIR / (plan.series or plan.slug)
        job = S.tts_job(plan, lines_dir, voices_dir, root=assets_dir.parent)
        todo = [pathlib.Path(x["out"]) for x in job["lines"] if not pathlib.Path(x["out"]).exists()]
        if todo:
            log(f"Голоса: озвучиваю {len(todo)} реплик ({len(job['voices'])} персонажей), Qwen3-TTS")
            t0 = time.time()
            if not worker("tts", job, sound_dir / "jobs" / "tts.json", logf):
                log("  часть реплик не озвучилась, подробности в render.log")
            for p in todo:
                if p.exists():
                    level_stem(p, "dialogue", logf)
            log(f"  готово за {time.time() - t0:.0f} с")
    durations = {}
    for s, i, _ in S.lines(plan):
        p = lines_dir / S.line_name(plan, s, i, "qwen")
        if p.exists() and (d := duration(p)):
            durations[(s.id, i)] = d
    for note in S.fit_dialogue(plan, durations, high):
        log("  " + note)
    return durations


def lipsync(plan: Plan, done: list[dict], proj: pathlib.Path, durations: dict, ltx_args: list[str], logf,
            run_ltx) -> None:
    """Перерисовывает губы говорящих в кадре под озвученные реплики (LTX retake, звук заморожен)."""
    if not plan.sound or not plan.sound.lipsync or not durations:
        return
    lines_dir = proj / S.SOUND_DIR / "lines"
    by_id = {d["id"]: d for d in done}
    for s in plan.shots:
        d = by_id.get(s.id)
        win = S.lipsync_window(s, durations)
        if not d or not win:
            continue
        clip = pathlib.Path(d["clip"])
        key = S._h(clip.name, win, [(ln.text, ln.at) for ln in s.dialogue])
        out = clip.with_name(f"{clip.stem}_lips_{key}.mp4")
        if not out.exists():
            canvas = proj / S.SOUND_DIR / "canvas" / f"{s.id}_{key}.mp4"
            canvas.parent.mkdir(parents=True, exist_ok=True)
            if not dialogue_canvas(plan, s, clip, lines_dir, canvas, logf):
                log(f"  сцена {s.id}: не собрался холст для липсинка, остаётся исходный клип")
                continue
            log(f"Липсинк сцены {s.id}: окно {win[0]:.2f}–{win[1]:.2f} с")
            t0 = time.time()
            tmp = out.with_suffix(".tmp.mp4")
            code = run_ltx(ltx_args + ["--video-path", str(canvas), "--start-time", f"{win[0]:.3f}",
                                       "--end-time", f"{win[1]:.3f}", "--seed", str(plan.seed),
                                       "--prompt", s.prompt, "--output-path", str(tmp)])
            if code != 0 or not tmp.exists():
                tmp.unlink(missing_ok=True)
                log(f"  липсинк не удался (код {code}), остаётся исходный клип")
                continue
            tmp.replace(out)
            log(f"  готово за {time.time() - t0:.0f} с")
        d["clip_original"] = d.get("clip_original") or d["clip"]
        d["clip"] = str(out)
        d["lipsync"] = list(win)


def dialogue_canvas(plan: Plan, shot, clip: pathlib.Path, lines_dir: pathlib.Path, out: pathlib.Path, logf) -> bool:
    """Клип сцены с дорожкой реплик вместо звука LTX: по ней retake двигает губы."""
    frames = int(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
                                 "stream=nb_read_packets", "-of", "csv=p=0", str(clip)],
                                capture_output=True, text=True).stdout.strip() or 0)
    if not frames:
        return False
    total = frames / FPS
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(clip)]
    parts, labels = [], []
    for i, ln in enumerate(shot.dialogue):
        f = lines_dir / S.line_name(plan, shot, i, "qwen")
        if not f.exists():
            continue
        cmd += ["-i", str(f)]
        ms = int(ln.at * 1000)
        parts.append(f"[{len(labels) + 1}:a]aresample=48000,aformat=channel_layouts=mono,adelay={ms}|{ms}[l{i}]")
        labels.append(f"[l{i}]")
    if not labels:
        return False
    graph = ";".join(parts) + f";{''.join(labels)}amix=inputs={len(labels)}:normalize=0,apad=whole_dur={total:.4f}," \
                              f"atrim=end={total:.4f},pan=stereo|c0=c0|c1=c0[a]"
    cmd += ["-filter_complex", graph, "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            str(out)]
    return _run(cmd, logf) == 0 and out.exists()


def foley(plan: Plan, done: list[dict], proj: pathlib.Path, logf) -> None:
    if not plan.sound or not plan.sound.foley or not done or not ensure_installed(["foley"], logf):
        return
    sound_dir = proj / S.SOUND_DIR
    by_id = {s.id: s for s in plan.shots}
    items = []
    for d in done:
        s = by_id[d["id"]]
        out = sound_dir / "foley" / S.foley_name(s, d["clip"])
        d["foley"] = str(out)
        items.append({"video": d["clip"], "prompt": S.foley_prompt(s), "out": str(out), "seed": plan.seed})
    todo = [x for x in items if not pathlib.Path(x["out"]).exists()]
    if todo:
        log(f"Фоли и эмбиент: {len(todo)} сцен, HunyuanVideo-Foley")
        t0 = time.time()
        if not worker("foley", {"items": items}, sound_dir / "jobs" / "foley.json", logf):
            log("  часть сцен без фоли (в них останется звук LTX), подробности в render.log")
        for x in todo:
            if pathlib.Path(x["out"]).exists():
                level_stem(pathlib.Path(x["out"]), "foley", logf)
        log(f"  готово за {time.time() - t0:.0f} с")
    for d in done:
        if not pathlib.Path(d["foley"]).exists():
            d.pop("foley")


def score(plan: Plan, proj: pathlib.Path, seconds: float, logf) -> str | None:
    """Музыка в длину фильма, если в плане нет трека из библиотеки."""
    if not plan.sound or not plan.sound.score or (plan.music and plan.music.file) or not ensure_installed(["music"], logf):
        return None
    sound_dir = proj / S.SOUND_DIR
    out = sound_dir / S.score_name(plan, seconds)
    if not out.exists():
        log(f"Музыка: {seconds:.0f} с, ACE-Step — «{S.score_caption(plan)[:80]}»")
        t0 = time.time()
        item = {"caption": S.score_caption(plan), "duration": round(seconds + 1.0, 1), "bpm": plan.sound.bpm,
                "seed": plan.seed, "out": str(out)}
        if not worker("music", {"items": [item]}, sound_dir / "jobs" / "music.json", logf) or not out.exists():
            log("  музыка не сгенерировалась, фильм будет без неё")
            return None
        level_stem(out, "music", logf)
        log(f"  готово за {time.time() - t0:.0f} с")
    return str(out)


def write_manifest(plan: Plan, done: list[dict], proj: pathlib.Path, durations: dict, score_path: str | None) -> dict:
    """sound/sound.json: какие стемы у каких сцен (пути относительно sound/) — для пересборки без GPU."""
    sound_dir = proj / S.SOUND_DIR
    shots = {}
    by_id = {d["id"]: d for d in done}
    for s in plan.shots:
        d = by_id.get(s.id)
        if not d:
            continue
        entry = {"lines": [], "foley": None, "lipsync": d.get("lipsync")}
        for i, ln in enumerate(s.dialogue):
            f = sound_dir / "lines" / S.line_name(plan, s, i, "qwen")
            if f.exists():
                entry["lines"].append({"file": str(f.relative_to(sound_dir)), "at": ln.at, "speaker": ln.speaker,
                                       "text": ln.text, "seconds": durations.get((s.id, i))})
        if d.get("foley"):
            entry["foley"] = str(pathlib.Path(d["foley"]).relative_to(sound_dir))
        shots[s.id] = entry
    manifest = {"shots": shots, "score": str(pathlib.Path(score_path).relative_to(sound_dir)) if score_path else None,
                "levels": plan.sound.levels if plan.sound else {}}
    S.save_manifest(sound_dir, manifest)
    return manifest
