"""Командная строка студии. Точка входа: python studio.py <команда> ..."""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

from . import __version__
from .config import ConfigError, load_config, path_in_root
from .schema import FORMATS, KINDS, PlanError, load_plan, validate


def _log(msg: str) -> None:
    print(time.strftime("[%H:%M:%S] ") + msg, flush=True)


def _die(msg: str, code: int = 1) -> None:
    print("\nОШИБКА: " + msg, file=sys.stderr, flush=True)
    sys.exit(code)


def _llm(cfg: dict):
    from .llm import LLMError, make_llm
    try:
        llm = make_llm(cfg)
    except LLMError as e:
        _die(str(e))
    tag = f"{llm.name}" + (f" / {getattr(llm, 'model', '')}" if getattr(llm, "model", "") else "")
    _log(f"LLM: {tag}")
    if llm.name == "ollama":
        _log("Подсказка: для заметно лучших сценариев задайте ANTHROPIC_API_KEY (провайдер anthropic выберется сам)")
    return llm


def _prefs(cfg: dict) -> str:
    """Текст предпочтений без строк-комментариев (#)."""
    p = path_in_root(cfg, "prefs_file")
    if not p.exists():
        return ""
    return "\n".join(l for l in p.read_text(encoding="utf-8").splitlines() if l.strip() and not l.lstrip().startswith("#"))


def _refs(args, cfg: dict) -> list[dict]:
    """--ref path[:style|frame|opening] -> копии в assets/refs (UI видит их и после рендера)."""
    from .references import ReferenceError, normalize_refs, parse_ref_arg, store_reference
    out = []
    for raw in getattr(args, "ref", None) or []:
        r = parse_ref_arg(raw)
        try:
            stored = store_reference(r["file"], path_in_root(cfg, "assets_dir"))
        except ReferenceError as e:
            _die(str(e))
        out.append({"file": str(stored), "role": r["role"]})
    try:
        return normalize_refs(out)
    except ReferenceError as e:
        _die(str(e))


def _plan_request(args, cfg: dict):
    from .audio import load_index
    from .planner import PlanRequest
    bible = None
    if args.series:
        from .bible import load_bible
        try:
            bible = load_bible(path_in_root(cfg, "series_dir"), args.series)
        except FileNotFoundError as e:
            _die(str(e))
        if args.kind == "film":
            args.kind = "episode"
    library = load_index(path_in_root(cfg, "assets_dir"))
    captions = None
    if args.captions:
        captions = True
    elif args.no_captions:
        captions = False
    return PlanRequest(request=args.request, kind=args.kind, seconds=args.duration, format=args.format,
                       quality=args.quality or cfg.get("quality", "high"), language=args.language, name=args.name,
                       series_bible=bible, episode=args.episode, music=args.music, captions=captions,
                       prefs=_prefs(cfg), library=library, seed=args.seed, notes=args.notes or "", loop=bool(args.loop),
                       refs=_refs(args, cfg))


def _save_plan(plan, cfg: dict, name: str | None) -> pathlib.Path:
    plans_dir = path_in_root(cfg, "plans_dir")
    path = plans_dir / f"{name or plan.slug}.json"
    if path.exists() and not name:
        path = plans_dir / f"{plan.slug}_{time.strftime('%m%d_%H%M')}.json"
    plan.save(path)
    return path


# ---------- команды ----------
def cmd_plan(args, cfg):
    from .planner import Planner, plan_summary
    llm = _llm(cfg)
    req = _plan_request(args, cfg)
    planner = Planner(llm, log=_log)
    plan = planner.plan(req)
    plan.audio = args.audio
    if req.series_bible:
        from .bible import log_episode, save_bible
        plan.episode = req.episode or len(req.series_bible.get("episodes", [])) + 1
        log_episode(req.series_bible, plan.to_dict())
        save_bible(path_in_root(cfg, "series_dir"), req.series_bible)
    path = _save_plan(plan, cfg, args.name)
    print()
    print(plan_summary(plan, cfg))
    print(f"\nПлан сохранён: {path}")
    print(f"Рендер: python studio.py render {path}")
    if getattr(args, "render", False):
        _render(path, cfg, keep=args.keep_pod)
    return path


def cmd_review(args, cfg):
    from .lint import lint_plan
    from .planner import Planner, plan_summary
    path = pathlib.Path(args.plan)
    try:
        plan = load_plan(path)
    except (PlanError, FileNotFoundError) as e:
        _die(str(e))
    issues = lint_plan(plan, plan.quality or cfg.get("quality", "fast"))
    problems = validate(plan, plan.quality or cfg.get("quality", "fast"))
    print(plan_summary(plan, cfg))
    print()
    for p in problems:
        print(f"[error] {p}")
    for i in issues:
        print(str(i))
    if not issues and not problems:
        print("Замечаний нет.")
    if args.fix:
        llm = _llm(cfg)
        planner = Planner(llm, log=_log)
        planner.director_review(plan)
        plan = planner.refine(plan, rounds=2)
        plan.save(path)
        print(f"\nИсправленный план сохранён: {path}")


def _render(path: pathlib.Path, cfg: dict, keep: bool = False):
    from .render_remote import RenderError, render
    try:
        cfg = load_config(require_runpod=True) | {"_root": cfg["_root"]}
        return render(path, cfg, keep=keep)
    except (ConfigError, RenderError, PlanError) as e:
        _die(str(e))


def cmd_render(args, cfg):
    _render(pathlib.Path(args.plan), cfg, keep=args.keep_pod)


def cmd_make(args, cfg):
    args.render = True
    cmd_plan(args, cfg)


def cmd_fetch(args, cfg):
    from .render_remote import RenderError, fetch
    try:
        fetch(args.name, load_config(require_runpod=True))
    except (ConfigError, RenderError) as e:
        _die(str(e))


def cmd_cleanup(args, cfg):
    from .render_remote import RenderError, cleanup
    try:
        cleanup(load_config(require_runpod=True))
    except (ConfigError, RenderError) as e:
        _die(str(e))


def cmd_estimate(args, cfg):
    from .planner import plan_summary
    try:
        plan = load_plan(args.plan)
    except (PlanError, FileNotFoundError) as e:
        _die(str(e))
    print(plan_summary(plan, cfg))


def cmd_assemble(args, cfg):
    """Пересобрать фильм локально из скачанных клипов (нужен ffmpeg)."""
    from .assemble import AssembleError, AssembleOptions, ClipSpec, assemble
    from .audio import resolve_asset
    from .schema import FPS, Plan
    film_dir = pathlib.Path(args.film_dir)
    manifest = film_dir / "manifest.json"
    if not manifest.exists():
        _die(f"нет {manifest}: скачайте фильм командой render/fetch")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    plan = Plan.from_dict(data["plan"])
    if args.plan:
        plan = load_plan(args.plan)   # обновлённый план (новая музыка, субтитры, переходы)
    clips_dir = film_dir / "clips"
    rendered = {d["id"]: d for d in data["shots"]}
    root = pathlib.Path(cfg["_root"])
    clips = []
    first = True
    for s in plan.shots:
        d = rendered.get(s.id)
        if not d:
            continue
        clip = clips_dir / (pathlib.Path(d["clip"]).stem + ".mp4")
        if not clip.exists():
            _log(f"нет клипа для сцены {s.id}, пропускаю")
            continue
        tr = "cut" if first else s.transition
        if tr == "continue" and not d.get("continuity"):
            tr = "cut"
        sfx = [(str(resolve_asset(x.file, root)), x.offset, x.volume) for x in s.sfx if resolve_asset(x.file, root)]
        nar = film_dir / f"narration_{s.id}.mp3"
        clips.append(ClipSpec(path=str(clip), shot_id=s.id, transition=tr, transition_seconds=s.transition_seconds,
                              caption=s.caption, sfx=sfx, narration=str(nar) if nar.exists() else None))
        first = False
    high = (data["plan"].get("quality") or "fast") == "high"
    w, h = plan.size(high)
    music = args.music if args.music else (plan.music.file if plan.music else None)
    music_path = resolve_asset(music, root) if music and music != "none" else None
    opts = AssembleOptions(width=w, height=h, fps=FPS, music_path=str(music_path) if music_path else None,
                           music_volume=args.music_volume if args.music_volume is not None else (plan.music.volume if plan.music else 0.25),
                           music_duck=plan.music.duck if plan.music else True, captions=plan.captions.enabled or args.captions,
                           caption_position=plan.captions.position, fade_in=plan.fade_in, fade_out=plan.fade_out,
                           leveling=(args.audio or plan.audio) == "leveled", loudnorm=(args.audio or plan.audio) == "leveled")
    out = pathlib.Path(args.out) if args.out else film_dir / f"film_recut_{time.strftime('%m%d_%H%M')}.mp4"
    try:
        with open(film_dir / "assemble.log", "a", encoding="utf-8") as lf:
            rep = assemble(clips, out, opts, film_dir / "work", logf=lf, log=_log)
    except AssembleError as e:
        _die(str(e))
    _log(f"Готово: {out} ({rep['seconds']} с, {rep['shots']} сцен)")


def cmd_series(args, cfg):
    from .bible import bible_summary, create_bible, load_bible, save_bible
    root = path_in_root(cfg, "series_dir")
    if args.action == "new":
        llm = _llm(cfg)
        bible = create_bible(llm, args.description, args.name, args.episodes, args.language, _prefs(cfg))
        path = save_bible(root, bible)
        print(bible_summary(bible))
        print(f"\nБиблия сохранена: {path}")
        print(f"Эпизод: python studio.py plan \"что происходит в серии\" --series {bible['slug']}")
    elif args.action == "show":
        try:
            print(bible_summary(load_bible(root, args.name)))
        except FileNotFoundError as e:
            _die(str(e))
    elif args.action == "list":
        found = sorted(p.parent.name for p in root.glob("*/bible.json")) if root.exists() else []
        print("\n".join(found) if found else "Сериалов пока нет")
    elif args.action == "note":
        try:
            bible = load_bible(root, args.name)
        except FileNotFoundError as e:
            _die(str(e))
        bible.setdefault("notes", []).append(args.description)
        save_bible(root, bible)
        print("Заметка добавлена в библию")


def cmd_assets(args, cfg):
    from .audio import index_assets, library_summary
    idx = index_assets(path_in_root(cfg, "assets_dir"))
    print(library_summary(idx))
    print(f"\nИндекс: {path_in_root(cfg, 'assets_dir') / 'index.json'} (теги и mood можно править руками)")


def cmd_prefs(args, cfg):
    p = path_in_root(cfg, "prefs_file")
    if args.text:
        with open(p, "a", encoding="utf-8") as f:
            f.write(("" if not p.exists() or p.stat().st_size == 0 else "\n") + "- " + args.text.strip() + "\n")
        print(f"Записано в {p.name}")
    print(p.read_text(encoding="utf-8") if p.exists() else "Предпочтений пока нет. Добавить: studio prefs \"меньше крупных планов\"")


def cmd_doctor(args, cfg):
    import shutil
    from .assemble import ffmpeg_has_filter, ffmpeg_major
    print(f"studio {__version__}")
    print(f"ffmpeg: {'v' + str(ffmpeg_major()) if shutil.which('ffmpeg') else 'нет (brew install ffmpeg) — нужен только для studio assemble'}"
          + (", libass: " + ("да" if ffmpeg_has_filter("ass") else "нет") if shutil.which("ffmpeg") else ""))
    llm = cfg.get("llm", {})
    import os
    key = bool(os.environ.get("ANTHROPIC_API_KEY") or cfg.get("anthropic_api_key"))
    print(f"LLM: provider={llm.get('provider')} anthropic_key={'да' if key else 'нет'} ollama={llm.get('ollama_url')} ({llm.get('ollama_model')})")
    print(f"RunPod: key={'да' if cfg.get('runpod_api_key') else 'нет'} volume={cfg.get('network_volume_id') or 'нет'} quality={cfg.get('quality')}")
    print(f"ElevenLabs (озвучка): {'да' if cfg.get('elevenlabs_api_key') else 'нет'}")
    assets = path_in_root(cfg, "assets_dir")
    n_music = len(list((assets / "music").glob("*"))) if (assets / "music").exists() else 0
    n_sfx = len(list((assets / "sfx").glob("*"))) if (assets / "sfx").exists() else 0
    print(f"Библиотека: музыка {n_music}, sfx {n_sfx} ({assets})")


def cmd_frame(args, cfg):
    """Задать / убрать первый кадр сцены в готовом плане; по умолчанию Claude переписывает сцену под кадр."""
    from .references import ReferenceError, adapt_shot_to_image, store_reference
    from .schema import clamp_seconds, MAX_FRAMES_HIGH_CONDITIONED
    path = pathlib.Path(args.plan)
    try:
        plan = load_plan(path)
    except (PlanError, FileNotFoundError) as e:
        _die(str(e))
    idx = next((i for i, s in enumerate(plan.shots) if s.id == args.shot), None)
    if idx is None:
        _die(f"в плане нет сцены {args.shot}")
    shot = plan.shots[idx]
    if args.clear:
        shot.image = None
        plan.references = [r for r in plan.references if r.get("shot") != shot.id or r.get("role") == "style"]
        plan.save(path)
        _log(f"Первый кадр у сцены {shot.id} убран")
        print(f"Сохранено: {path}")
        return
    if not args.image:
        _die("укажите --image путь или --clear")
    try:
        stored = store_reference(args.image, path_in_root(cfg, "assets_dir"))
    except ReferenceError as e:
        _die(str(e))
    shot.image = str(stored)
    shot.transition = "cut"
    if args.strength is not None:
        shot.image_strength = max(0.1, min(1.0, args.strength))
    high = plan.is_high(cfg.get("quality", "fast"))
    if high and shot.frames > MAX_FRAMES_HIGH_CONDITIONED:
        shot.seconds = clamp_seconds(shot.seconds, True, conditioned=True)
        _log(f"Сцена {shot.id}: с первым кадром в high максимум 5 с — длительность {shot.seconds} с")
    plan.references = [r for r in plan.references if r.get("shot") != shot.id or r.get("role") == "style"]
    plan.references.append({"file": str(stored), "role": "frame", "description": "", "shot": shot.id})
    if not args.no_adapt:
        llm = _llm(cfg)
        _log(f"Подгоняю сцену {shot.id} под кадр: Claude смотрит на фото и переписывает промпт")
        res = adapt_shot_to_image(llm, plan, idx, stored)
        shot.prompt = res["prompt"]
        if res["direction"]:
            shot.direction = res["direction"]
        from .planner import ensure_anchor
        ensure_anchor(plan)
        if res["conflict"]:
            plan.review_notes = list(plan.review_notes or []) + [f"{shot.id}: {res['conflict']}"]
            _log("Замечание: " + res["conflict"])
        print(f"\nНовый промпт сцены {shot.id}:\n{shot.prompt}")
    plan.save(path)
    print(f"\nПлан сохранён: {path}")


def cmd_ui(args, cfg):
    from .ui import serve
    serve(port=args.port, open_browser=not args.no_browser)


# ---------- парсер ----------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="studio", description="AI-киностудия: запрос -> план -> рендер LTX-2.5 -> фильм")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_plan_args(sp):
        sp.add_argument("request", help="что снимаем, своими словами (на любом языке)")
        sp.add_argument("--kind", choices=KINDS, default="film", help="short | aesthetic | film | episode | motion")
        sp.add_argument("--duration", type=int, help="целевой хронометраж, секунд")
        sp.add_argument("--format", choices=FORMATS, help="соотношение сторон (по умолчанию из пресета)")
        sp.add_argument("--quality", choices=("fast", "high"), help="качество рендера (по умолчанию из конфига)")
        sp.add_argument("--language", default="ru", help="язык реплик и субтитров (ru)")
        sp.add_argument("--name", help="имя файла плана / slug")
        sp.add_argument("--series", help="slug сериала: план станет эпизодом по его библии")
        sp.add_argument("--episode", type=int, help="номер эпизода (по умолчанию следующий)")
        sp.add_argument("--music", default="auto", help="auto | none | путь к треку")
        sp.add_argument("--captions", action="store_true", help="включить субтитры")
        sp.add_argument("--no-captions", action="store_true", help="выключить субтитры")
        sp.add_argument("--seed", type=int)
        sp.add_argument("--notes", help="дополнительные указания планировщику")
        sp.add_argument("--loop", action="store_true", help="бесшовный луп: конец переходит в начало")
        sp.add_argument("--ref", action="append", metavar="PATH[:ROLE]",
                        help="фото-референс; роль style (эстетика, по умолчанию), frame (первый кадр одной из сцен) "
                             "или opening (первый кадр фильма). Можно повторять")
        sp.add_argument("--audio", choices=("raw", "leveled"), default="raw",
                        help="raw — звук модели как есть (по умолчанию); leveled — выравнивание сцен и -14 LUFS")
        sp.add_argument("--keep-pod", action="store_true", help="(с рендером) не удалять Pod после рендера")

    sp = sub.add_parser("plan", help="составить план с оптимизированными промптами")
    add_plan_args(sp)
    sp.add_argument("--render", action="store_true", help="сразу отрендерить")
    sp.set_defaults(fn=cmd_plan)

    sp = sub.add_parser("make", help="план + рендер одной командой")
    add_plan_args(sp)
    sp.set_defaults(fn=cmd_make)

    sp = sub.add_parser("review", help="проверить план и (с --fix) исправить промпты моделью")
    sp.add_argument("plan")
    sp.add_argument("--fix", action="store_true")
    sp.set_defaults(fn=cmd_review)

    sp = sub.add_parser("render", help="отрендерить план на RunPod и скачать фильм")
    sp.add_argument("plan")
    sp.add_argument("--keep-pod", action="store_true")
    sp.set_defaults(fn=cmd_render)

    sp = sub.add_parser("estimate", help="оценка длительности и стоимости рендера")
    sp.add_argument("plan")
    sp.set_defaults(fn=cmd_estimate)

    sp = sub.add_parser("assemble", help="пересобрать скачанный фильм локально (другая музыка/субтитры)")
    sp.add_argument("film_dir", help="папка films/<slug>")
    sp.add_argument("--plan", help="обновлённый план вместо сохранённого в manifest")
    sp.add_argument("--music", help="трек или none")
    sp.add_argument("--music-volume", type=float)
    sp.add_argument("--captions", action="store_true")
    sp.add_argument("--audio", choices=("raw", "leveled"), help="raw — как у модели, leveled — выровнять (по умолчанию из плана)")
    sp.add_argument("--out")
    sp.set_defaults(fn=cmd_assemble)

    sp = sub.add_parser("fetch", help="забрать готовый фильм с тома (если ноутбук спал)")
    sp.add_argument("name", help="slug фильма")
    sp.set_defaults(fn=cmd_fetch)

    sp = sub.add_parser("cleanup", help="удалить все Pod'ы, созданные студией")
    sp.set_defaults(fn=cmd_cleanup)

    sp = sub.add_parser("series", help="сериалы: new | show | list | note")
    sp.add_argument("action", choices=("new", "show", "list", "note"))
    sp.add_argument("description", nargs="?", help="описание сериала (new) или заметка (note)")
    sp.add_argument("--name", help="slug сериала")
    sp.add_argument("--episodes", type=int, default=6)
    sp.add_argument("--language", default="ru")
    sp.set_defaults(fn=cmd_series)

    sp = sub.add_parser("assets", help="переиндексировать библиотеку музыки и звуков")
    sp.set_defaults(fn=cmd_assets)

    sp = sub.add_parser("prefs", help="постоянные предпочтения для планировщика")
    sp.add_argument("text", nargs="?")
    sp.set_defaults(fn=cmd_prefs)

    sp = sub.add_parser("doctor", help="проверить окружение и настройки")
    sp.set_defaults(fn=cmd_doctor)

    sp = sub.add_parser("frame", help="задать первый кадр сцены фотографией (Claude подгонит сцену под кадр)")
    sp.add_argument("plan")
    sp.add_argument("--shot", required=True, help="id сцены, например 001")
    sp.add_argument("--image", help="путь к jpg / png / webp")
    sp.add_argument("--strength", type=float, help="сила условия 0.1-1.0 (1.0 = кадр точь-в-точь)")
    sp.add_argument("--no-adapt", action="store_true", help="не переписывать промпт сцены")
    sp.add_argument("--clear", action="store_true", help="убрать первый кадр")
    sp.set_defaults(fn=cmd_frame)

    sp = sub.add_parser("ui", help="открыть веб-интерфейс студии в браузере")
    sp.add_argument("--port", type=int, default=8765)
    sp.add_argument("--no-browser", action="store_true")
    sp.set_defaults(fn=cmd_ui)
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config()
    except ConfigError as e:
        _die(str(e))
    if args.cmd == "series":
        if args.action == "new" and not args.description:
            _die("series new: нужно описание сериала")
        if args.action in ("show", "note") and not args.name:
            _die(f"series {args.action}: укажите --name slug")
        if args.action == "note" and not args.description:
            _die("series note: нужен текст заметки")
    from .llm import LLMError
    from .references import ReferenceError
    try:
        args.fn(args, cfg)
    except KeyboardInterrupt:
        print("\nОстановлено.")
        sys.exit(130)
    except LLMError as e:
        msg = str(e)
        if "credit balance is too low" in msg:
            msg = ("на счёте Anthropic закончились кредиты — пополните баланс в console.anthropic.com "
                   "(Plans & Billing), затем повторите")
        _die("LLM: " + msg)
    except ReferenceError as e:
        _die(str(e))
