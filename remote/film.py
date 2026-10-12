#!/usr/bin/env python3
"""Pod-сторона: план -> клипы LTX-2.5 -> бесшовная сборка -> film.mp4.

Запускается через film_night.sh. Перезапуск безопасен: готовые клипы берутся из кэша.
Структура на томе: /workspace/film/<slug>/{clips,norm,assets}, render.log, report.json.

Переменные окружения:
  FILM_QUALITY=high|fast   режим (по умолчанию из плана, иначе fast)
  FILM_RETRIES=2           попыток на сцену внутри одного пайплайна
  FILM_DIR=...             папка проекта (по умолчанию /workspace/film/<slug>)
  LTX_TEST_CMD=...         тестовая команда вместо LTX (генерирует файл по последнему аргументу)
"""
from __future__ import annotations

import json
import hashlib
import os
import pathlib
import shlex
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))   # /workspace/studio
from studio.assemble import AssembleError, AssembleOptions, ClipSpec, assemble, probe  # noqa: E402
from studio.schema import FPS, MAX_FRAMES_HIGH_CONDITIONED, Plan, load_plan, normalize_durations, validate  # noqa: E402

MODELS = os.environ.get("LTX_MODELS", "/workspace/models/ltx-2.5")
REPO = os.environ.get("LTX_REPO", "/workspace/LTX-2")
LTX_PY = os.environ.get("LTX_PY", f"{REPO}/.venv/bin/python")
EXTRA = shlex.split(os.environ.get("LTX_EXTRA_ARGS", ""))
TEST_CMD = os.environ.get("LTX_TEST_CMD")
DETAIL_LORA = f"{MODELS}/loras/ltx-2.5-22b-ic-lora-pixel-spatial-upscaler-x2-1.0.safetensors"
RETRIES = int(os.environ.get("FILM_RETRIES", "2"))
CUDA_ERRORS = ("CUBLAS_STATUS", "illegal memory access", "CUDA error", "out of memory", "OutOfMemoryError",
               "cudaErrorIllegalAddress", "device-side assert")


def log(msg: str) -> None:
    print(time.strftime("[%H:%M:%S] ") + msg, flush=True)


def run(cmd: list[str], logf) -> tuple[int, str]:
    """Запускает команду, пишет вывод в лог и возвращает (код, хвост вывода)."""
    logf.write("\n$ " + " ".join(shlex.quote(c) for c in cmd) + "\n")
    logf.flush()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
                            cwd=REPO if os.path.isdir(REPO) else None)
    tail: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        logf.write(line)
        tail.append(line)
        if len(tail) > 80:
            tail.pop(0)
    proc.wait()
    logf.flush()
    return proc.returncode, "".join(tail)


def ltx_cmd(pipeline: str, prompt: str, w: int, h: int, frames: int, seed: int, out: pathlib.Path,
            image: str | None, image_strength: float, end_image: str | None = None) -> list[str]:
    """pipeline: dfr | distilled. image — первый кадр, end_image — последний (луп)."""
    high = pipeline == "dfr"
    if TEST_CMD:
        test = shlex.split(TEST_CMD) + ["--width", str(w), "--height", str(h), "--num-frames", str(frames),
                                        "--seed", str(seed), "--pipeline", pipeline]
        if image:
            test += ["--image", str(image), "0", f"{image_strength:g}"]
        if end_image:
            test += ["--image", str(end_image), str(frames - 1), "1.0"]
        return test + [str(out)]
    vae = "ltx-2.5-video-vae-bf16.safetensors" if high else "ltx-2.5-video-vae-conv-bf16.safetensors"
    cmd = [
        LTX_PY, "-m", "ltx_pipelines.dfr_pipeline" if high else "ltx_pipelines.distilled",
        "--transformer-path", f"{MODELS}/diffusion_models/ltx-2.5-22b-distilled-transformer-bf16.safetensors",
        "--text-encoder-path", f"{MODELS}/text_encoders/gemma4-12b-with-proj-ltx-2.5-bf16.safetensors",
        "--video-vae-path", f"{MODELS}/vae/{vae}",
        "--audio-vae-path", f"{MODELS}/vae/ltx-2.5-audio-vae-bf16.safetensors",
        "--spatial-upsampler-path", f"{MODELS}/latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors",
        "--width", str(w), "--height", str(h), "--num-frames", str(frames), "--frame-rate", str(FPS),
        "--seed", str(seed), "--output-path", str(out), "--prompt", prompt,
    ]
    if image:
        cmd += ["--image", str(image), "0", f"{image_strength:g}"]
    if end_image:
        cmd += ["--image", str(end_image), str(frames - 1), "1.0"]
    if high:
        cmd += ["--detailing-lora", DETAIL_LORA]
    elif frames > 241:
        cmd += ["--chunked"]
    return cmd + EXTRA


def last_frame(video: pathlib.Path, png: pathlib.Path, logf) -> bool:
    code, _ = run(["ffmpeg", "-y", "-loglevel", "error", "-sseof", "-0.05", "-i", str(video), "-update", "1",
                   "-frames:v", "1", str(png)], logf)
    return code == 0 and png.exists()


def first_frame(video: pathlib.Path, png: pathlib.Path, logf) -> bool:
    code, _ = run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-frames:v", "1", str(png)], logf)
    return code == 0 and png.exists()


def attempts_for(high: bool, image: str | None, w_fast: tuple[int, int], frames: int = 121,
                 extra_conditioned: bool = False) -> list[dict]:
    """Цепочка откатов: что пробовать, если пайплайн падает.

    DFR с кадром-условием падает в keyframe-декодере на 193+ кадрах (CUBLAS/illegal memory access;
    проверено: 121 кадр проходит при любой силе условия). Поэтому для длинных сцен с условием DFR не
    пробуем вовсе, а идём сразу в distilled того же разрешения, затем быстрый режим.
    Все попытки сохраняют опорные кадры: отказ сцены лучше незаметной потери замысла.
    """
    if not high:
        return [{"pipeline": "distilled", "image": image, "size": None}]
    conditioned = bool(image) or extra_conditioned
    chain = []
    # DFR с условием на ПОСЛЕДНИЙ кадр (луп) падает даже на 121 кадре (проверено 2026-10-10), поэтому
    # финальную сцену лупа сразу рендерим distilled в том же разрешении
    if not (conditioned and frames > MAX_FRAMES_HIGH_CONDITIONED) and not extra_conditioned:
        chain.append({"pipeline": "dfr", "image": image, "size": None})
    chain.append({"pipeline": "distilled", "image": image, "size": None})
    chain.append({"pipeline": "distilled", "image": image, "size": w_fast})
    return chain


def render_shots(plan: Plan, proj: pathlib.Path, high: bool, w: int, h: int, logf) -> tuple[list[dict], list[str]]:
    from studio.schema import SIZES_FAST
    clips_dir = proj / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    plan_dir = pathlib.Path(plan.source_path).parent if plan.source_path else proj
    done: list[dict] = []
    failed: list[str] = []
    prev_clip: pathlib.Path | None = None
    prev_key = ""
    first_clip: pathlib.Path | None = None
    first_key = ""
    t_all = time.time()
    for i, s in enumerate(plan.shots):
        frames = s.frames
        if high and frames > 241:
            log(f"  сцена {s.id}: в режиме high максимум 10 с, обрезаю")
            frames = 241
        image = s.image
        if image and not os.path.isabs(image):
            image = str((plan_dir / image).resolve())
        if image and not os.path.exists(image):
            log(f"  сцена {s.id}: опорный кадр {image} не найден; сцена пропущена вместо потери композиции")
            failed.append(s.id)
            prev_clip = None
            continue
        cont = s.transition == "continue" and i > 0 and not image
        loop_last = plan.loop and i == len(plan.shots) - 1 and len(plan.shots) > 1
        if loop_last and high and frames > MAX_FRAMES_HIGH_CONDITIONED:
            log(f"  сцена {s.id}: финальная сцена лупа в режиме high — максимум 5 с, обрезаю")
            frames = MAX_FRAMES_HIGH_CONDITIONED
        # ключ кэша: формат для обычных сцен не меняем (иначе все клипы на томе перерендерятся);
        # элемент для лупа добавляем только финальной сцене лупа
        key_parts = [s.prompt, frames, high, w, h, plan.seed, image, s.image_strength, prev_key if cont else ""]
        if image:
            key_parts.append(hashlib.sha256(pathlib.Path(image).read_bytes()).hexdigest())
        if image or cont or loop_last:
            key_parts.append("preserve-conditioning-v1")
        if loop_last:
            key_parts.append(first_key)
        key = hashlib.sha1(json.dumps(key_parts, ensure_ascii=False).encode()).hexdigest()[:10]
        out = clips_dir / f"shot_{s.id}_{key}.mp4"
        meta_path = out.with_suffix(".json")
        if out.exists():
            log(f"[{i + 1}/{len(plan.shots)}] сцена {s.id} уже готова, пропускаю")
            meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
            done.append({"id": s.id, "clip": str(out), "pipeline": meta.get("pipeline", "?"), "cached": True,
                         "continuity": meta.get("continuity", cont), "loop_closed": meta.get("loop_closed", False)})
            prev_clip, prev_key = out, key
            if i == 0:
                first_clip, first_key = out, key
            continue
        if cont:
            if prev_clip is None:
                log(f"  сцена {s.id}: предыдущая сцена не получилась; продолжение пропущено")
                failed.append(s.id)
                continue
            else:
                png = clips_dir / f"shot_{s.id}_{key}_start.png"
                if last_frame(prev_clip, png, logf):
                    image = str(png)
                else:
                    log(f"  сцена {s.id}: не смог вытащить последний кадр предыдущей сцены")
                    failed.append(s.id)
                    prev_clip = None
                    continue
        end_image = None
        if loop_last and image:
            # distilled с условием и на первый, и на последний кадр мерцает (проверено 2026-10-12:
            # целые кадры прыгают в другую композицию) — луп со своим первым кадром закрывается склейкой
            log(f"  сцена {s.id}: у финальной сцены лупа свой первый кадр — луп закроется склейкой, без условия на последний кадр")
            loop_last = False
        if loop_last:
            if first_clip is None:
                log(f"  сцена {s.id}: первая сцена не получилась, луп замкнуть нечем")
                failed.append(s.id)
                prev_clip = None
                continue
            else:
                png = clips_dir / f"shot_{s.id}_{key}_loop_end.png"
                if first_frame(first_clip, png, logf):
                    end_image = str(png)
                    log(f"  сцена {s.id}: замыкаю луп — последний кадр = первый кадр сцены {plan.shots[0].id}")
                else:
                    log(f"  сцена {s.id}: не смог вытащить первый кадр фильма, луп не замкнётся")
                    failed.append(s.id)
                    prev_clip = None
                    continue
        if high and ((image and frames > MAX_FRAMES_HIGH_CONDITIONED) or end_image):
            log(f"  сцена {s.id}: {'условие на последний кадр' if end_image else f'{frames} кадров с кадром-условием'} — "
                "DFR на этом падает, сразу distilled 1080p")
        chain = attempts_for(high, image, SIZES_FAST[plan.format], frames, extra_conditioned=bool(end_image))
        ok_meta = None
        attempt_no = 0
        for step in chain:
            pw, ph = step["size"] or (w, h)
            for attempt in range(1, RETRIES + 2):
                attempt_no += 1
                seed = plan.seed + i * 101 + attempt_no - 1
                t0 = time.time()
                tag = step["pipeline"] + (" +image" if step["image"] else "") + (f" {pw}x{ph}" if step["size"] else "")
                log(f"[{i + 1}/{len(plan.shots)}] сцена {s.id}: {frames} кадров, {tag}, попытка {attempt}")
                tmp = clips_dir / f"shot_{s.id}_{key}.tmp.mp4"
                step_end = None if step.get("no_cond") else end_image
                code, tail = run(ltx_cmd(step["pipeline"], s.prompt, pw, ph, frames, seed, tmp, step["image"],
                                         s.image_strength, step_end), logf)
                if code == 0 and tmp.exists() and tmp.stat().st_size > 0:
                    tmp.replace(out)
                    ok_meta = {"pipeline": step["pipeline"], "size": f"{pw}x{ph}", "seed": seed,
                               "continuity": bool(step["image"]) and cont, "seconds_render": round(time.time() - t0),
                               "loop_closed": bool(step_end)}
                    log(f"    готово за {time.time() - t0:.0f} с")
                    break
                tmp.unlink(missing_ok=True)
                cuda = any(e in tail for e in CUDA_ERRORS)
                log(f"    ошибка (код {code}{', CUDA' if cuda else ''}), подробности в render.log")
                if cuda:
                    break   # повтор того же пайплайна с тем же входом почти наверняка упадёт так же
            if ok_meta:
                break
            log(f"    пайплайн {step['pipeline']} не справился, пробую следующий вариант")
        if ok_meta:
            meta_path.write_text(json.dumps(ok_meta))
            done.append({"id": s.id, "clip": str(out), **ok_meta})
            prev_clip, prev_key = out, key
            if i == 0:
                first_clip, first_key = out, key
        else:
            failed.append(s.id)
            prev_clip, prev_key = None, ""
    log(f"Генерация закончена за {(time.time() - t_all) / 60:.0f} мин: {len(done)} готово, {len(failed)} с ошибкой")
    return done, failed


def main() -> int:
    plan_path = pathlib.Path(sys.argv[1]).resolve()
    plan = load_plan(plan_path)
    normalize_durations(plan)
    quality_env = os.environ.get("FILM_QUALITY")
    high = (quality_env or plan.quality or "fast").lower() == "high"
    if high and not TEST_CMD and not os.path.exists(DETAIL_LORA):
        log("Нет LoRA детализации для режима high, перехожу на быстрый режим")
        high = False
    plan.quality = "high" if high else "fast"
    problems = validate(plan, plan.quality)
    if problems:
        log("План с проблемами: " + "; ".join(problems))
    w, h = plan.size(high)
    proj = pathlib.Path(os.environ.get("FILM_DIR", f"/workspace/film/{plan.slug or plan_path.stem}"))
    proj.mkdir(parents=True, exist_ok=True)
    logf = open(proj / "render.log", "a", encoding="utf-8")
    log(f"Фильм «{plan.title}»: {len(plan.shots)} сцен, ~{plan.total_seconds / 60:.1f} мин, {plan.format} {w}x{h}, "
        f"качество {'high (DFR)' if high else 'fast'}")
    log(f"Папка проекта: {proj}")
    t_all = time.time()
    done, failed = render_shots(plan, proj, high, w, h, logf)
    if not done:
        log("Ни одной сцены не получилось, склеивать нечего")
        return 1

    log("Собираю фильм (переходы, музыка, звуки, субтитры, громкость)...")
    assets_dir = plan_path.parent / f"{plan_path.stem}_assets"
    root = plan_path.parent

    def asset(file: str | None) -> str | None:
        if not file:
            return None
        for base in (assets_dir, root, pathlib.Path("/workspace/studio"), pathlib.Path("/workspace")):
            p = base / file
            if p.exists():
                return str(p)
        log(f"  аудиофайл {file} не найден, пропускаю")
        return None

    ok_ids = {d["id"] for d in done}
    clips: list[ClipSpec] = []
    first = True
    for s in plan.shots:
        if s.id not in ok_ids:
            continue
        d = next(x for x in done if x["id"] == s.id)
        transition = "cut" if first else s.transition
        if transition == "continue" and not d.get("continuity"):
            transition = "cut"      # непрерывность не удалась (откат без картинки) — честная склейка
        narration = asset(f"narration_{s.id}.mp3") if s.narration else None
        sfx = [(asset(x.file), x.offset, x.volume) for x in s.sfx]
        clips.append(ClipSpec(path=d["clip"], shot_id=s.id, transition=transition,
                              transition_seconds=s.transition_seconds, caption=s.caption,
                              sfx=[x for x in sfx if x[0]], narration=narration,
                              trim_end=(1 / FPS) if (plan.loop and d.get("loop_closed")) else 0.0))
        first = False
    loop_closed = bool(plan.loop and clips and done and done[-1].get("loop_closed"))
    if plan.loop and not loop_closed:
        log("Луп не замкнут (финальная сцена без условия на первый кадр) — стык будет обычной склейкой")
    music_path = asset(plan.music.file) if plan.music and plan.music.file else None
    opts = AssembleOptions(width=w, height=h, fps=FPS, music_path=music_path,
                           music_volume=plan.music.volume if plan.music else 0.25,
                           music_duck=plan.music.duck if plan.music else True,
                           music_fade_in=plan.music.fade_in if plan.music else 1.0,
                           music_fade_out=plan.music.fade_out if plan.music else 2.5,
                           captions=plan.captions.enabled, caption_position=plan.captions.position,
                           caption_font_size=plan.captions.font_size,
                           fade_in=0.0 if plan.loop else plan.fade_in, fade_out=0.0 if plan.loop else plan.fade_out,
                           leveling=plan.audio == "leveled", loudnorm=plan.audio == "leveled")
    final = proj / "film.mp4"
    try:
        rep = assemble(clips, final, opts, proj, logf=logf, log=log)
    except AssembleError as e:
        log(f"Сборка не удалась: {e}. Клипы лежат в {proj / 'clips'}")
        return 1
    report = {"film": str(final), "title": plan.title, "quality": "high (DFR)" if high else "fast",
              "resolution": f"{w}x{h}", "seconds": rep["seconds"], "shots_ok": len(done), "shots_failed": failed,
              "shots": done, "music": bool(music_path), "captions": rep["captions"], "timeline": rep["timeline"],
              "loop": plan.loop, "loop_closed": loop_closed, "audio": plan.audio,
              "minutes": round((time.time() - t_all) / 60)}
    (proj / "manifest.json").write_text(json.dumps({"plan": plan.to_dict(), "shots": done}, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
    (proj / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    if rep.get("quiet_shots"):
        log(f"Внимание: в сценах {', '.join(rep['quiet_shots'])} звук почти пропадает (модель сгенерировала тихий клип); "
            "задайте в промпте интенсивность звука или включите audio: leveled")
    report["quiet_shots"] = rep.get("quiet_shots", [])
    report["clip_lufs"] = rep.get("clip_lufs", {})
    (proj / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"ФИЛЬМ ГОТОВ: {final} ({rep['seconds']} с)" + (f" (без сцен: {', '.join(failed)})" if failed else ""))
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
