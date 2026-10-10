"""Творческий планировщик: запрос -> готовый план с оптимизированными промптами.

Этапы:
1. outline   — название, логлайн, стилевая библия, персонажи с постоянными
               дескрипторами, разбиение на акты с битами и хронометражем;
2. shots     — по актам: сцены с промптами LTX-2.5, переходами, субтитрами;
3. lint      — детерминированная проверка промптов + исправление моделью
               только проблемных сцен (до 2 раундов);
4. fit       — подгонка длительностей к сетке кадров и целевому хронометражу,
               выбор музыки из библиотеки.
"""
from __future__ import annotations

import json
import math
import pathlib
import re
import time
from dataclasses import dataclass

from .audio import library_summary
from .knowledge import KIND_PRESETS, LTX_PROMPT_RULES, STYLE_REFERENCE, MOTION_PROMPT_RULES, DIRECTOR_RULES
from .lint import Issue, errors_only, issues_by_shot, lint_plan
from .llm import LLM, LLMError
from .schema import (FORMATS, MIN_SHOT_SECONDS, Captions, Music, Plan, Shot, Sfx, clamp_seconds, is_conditioned,
                     max_seconds, normalize_durations, slugify, validate)

SHOTS_PER_CALL = 12


@dataclass
class PlanRequest:
    request: str
    kind: str = "film"
    seconds: int | None = None
    format: str | None = None
    quality: str = "high"
    language: str = "ru"
    name: str | None = None
    series_bible: dict | None = None
    episode: int | None = None
    music: str = "auto"               # auto | none | путь к файлу
    captions: bool | None = None      # None = по пресету
    prefs: str = ""                   # studio_prefs.md
    library: dict | None = None       # индекс assets
    seed: int | None = None
    notes: str = ""                   # доп. указания к этому плану
    loop: bool = False                # бесшовный луп


def _preset(kind: str) -> dict:
    if kind not in KIND_PRESETS:
        raise ValueError(f"неизвестный тип {kind!r}; доступны: {', '.join(KIND_PRESETS)}")
    return KIND_PRESETS[kind]


def system_prompt(req: PlanRequest, high: bool) -> str:
    preset = _preset(req.kind)
    lo, hi = preset["shot_seconds"]
    hi = min(hi, int(max_seconds(high)))
    parts = [
        "You are the creative core of an automated AI film studio: showrunner, screenwriter, director of photography, "
        "editor and sound designer in one. Clips are rendered by the LTX-2.5 video+audio model (24 fps, "
        f"{'1080p, DFR quality' if high else '720p-class, fast mode'}), one clip per shot, then the studio stitches them. "
        "You think in finished films: story first, then images, then sound. You never produce generic AI-looking "
        "footage: every shot has a specific light, a specific texture and a reason to exist.",
        f"FORMAT PRESET — {preset['label']}:\n{preset['brief']}",
        f"Shot length rules: each shot {lo}-{hi} seconds (hard minimum {MIN_SHOT_SECONDS}, hard maximum {hi}). "
        "A longer continuous action is split into consecutive shots with transition=\"continue\" (the next clip starts "
        "from the exact last frame of the previous one). Transition values: \"cut\" (default, hard cut), "
        "\"continue\" (seamless continuation of the same take), \"dissolve\" (crossfade, only for time/space jumps)."
        + (" In this quality mode a \"continue\" shot must be at most 5 seconds (the renderer's keyframe decoder fails "
           "on longer conditioned clips): split a long take as 8 s + 5 s + 5 s ... rather than 8 s + 8 s." if high else ""),
        LTX_PROMPT_RULES,
        STYLE_REFERENCE,
        DIRECTOR_RULES,
    ]
    if req.kind == "motion":
        parts.append(MOTION_PROMPT_RULES)
    if req.loop:
        parts.append("LOOP MODE: the piece must play as a seamless loop. The LAST shot must end in exactly the visual state "
                     "the FIRST shot begins with: same location, framing, subject position, weather and light (the studio "
                     "technically conditions the last frame of the last shot on the first frame of the first shot). "
                     "Design the first shot to start from a calm, holdable composition and write the last shot so its "
                     "final seconds settle back into that composition. No fades, no title, no ending beat.")
    if req.series_bible:
        from .bible import bible_summary
        parts.append("SERIES BIBLE (binding; copy character/location descriptors verbatim into prompts):\n"
                     + bible_summary(req.series_bible))
    if req.prefs.strip():
        parts.append("PRODUCER'S STANDING PREFERENCES (always apply):\n" + req.prefs.strip())
    if req.library:
        parts.append("SOUND LIBRARY available to the studio (choose by file name exactly as listed, or null):\n"
                     + library_summary(req.library))
    parts.append(f"Dialogue, captions, title, logline and synopsis language: {req.language}. "
                 "Prompts themselves are ALWAYS in English (except quoted dialogue lines, which are in the dialogue "
                 "language, with the language named: 'she says in Russian: \"...\"').")
    return "\n\n".join(parts)


OUTLINE_SCHEMA = """\
Return JSON exactly in this shape:
{
 "title": str,
 "logline": str,                       // one sentence
 "synopsis": str,                      // 3-6 sentences, what literally happens
 "creative_brief": {"must_keep": [str], "avoid": [str], "assumptions": [str],
                    "visual_anchors": [str], "loop_anchor": str|null},
 "style": {"anchor": str, "visual": str, "palette": str, "lens": str, "lighting": str, "camera": str, "sound": str, "pace": str},
 "characters": [{"name": str, "descriptor": str, "description": str, "voice": str}],   // descriptor = exact phrase for prompts
 "locations": [{"name": str, "descriptor": str}],
 "music": {"file": str|null, "mood": str, "volume": 0.15-0.35, "duck": bool} ,   // file from the library or null
 "acts": [{"name": str, "seconds": int, "beats": [str, ...]}]   // beats = one line per planned shot, in order
}
Rules: sum of acts.seconds must equal the target duration (±5%). Number of beats per act = how many shots that act
will have given the shot-length rules. Keep characters to the few the story needs. For a short, the first beat is
the hook. For a series episode, reuse bible characters/locations verbatim and advance the season arc.
"""

SHOTS_SCHEMA = """\
Return JSON exactly in this shape:
{"shots": [
  {"beat": str,                       // the beat you are realizing (copy from the outline)
   "direction": {"start": str, "action": str, "camera": str, "end": str},   // start = previous shot's end (state ledger)
   "seconds": number,                 // within the shot-length rules
   "transition": "cut"|"continue"|"dissolve",
   "transition_seconds": number,      // only for dissolve, 0.4-1.2
   "prompt": str,                     // the LTX-2.5 prompt, one English paragraph, 70-180 words, ends with sound
   "caption": str|null,               // on-screen caption in the requested language (shorts only), 2-7 words
   "narration": str|null,             // voice-over text in the requested language, or null
   "sfx": [{"file": str, "offset": number, "volume": number}]   // only files from the library, else []
  }, ...]}
Rules: the sum of seconds for this act must match the act duration (±10%). The first shot of the whole film is
"cut". A "continue" shot must begin from the end state of the previous shot. Keep every recurring character's
descriptor identical across shots. Vary shot sizes and angles. Sound description is mandatory in every prompt.
STATE LEDGER: direction.start of every shot restates the direction.end of the previous shot (given below for
all earlier shots), or names the time/place jump explicitly. The prompt body does NOT include the world anchor
sentence (the studio inserts style.anchor verbatim, ~35 words); write the body as 60-130 words so the final prompt stays under 180.
"""

REVISE_SCHEMA = """\
Return JSON: {"shots": [{"id": str, "prompt": str, "seconds": number, "caption": str|null,
"direction": {"start": str, "action": str, "camera": str, "end": str}}]} — only the shots you were
asked to fix, same ids. Keep the world anchor sentence and the character descriptors verbatim; direction.start
must match the previous shot's direction.end. Keep the story beat and continuity; fix exactly the listed problems while obeying every
prompt rule (one English paragraph, 70-180 words, camera + light + sound, no on-screen text, no negatives).
"""


def ledger(shots: list[dict]) -> list[dict]:
    """Компактная история: бит и конечное состояние каждой сцены (для контекста следующих актов)."""
    out = []
    for i, s in enumerate(shots):
        d = s.get("direction") or {}
        out.append({"n": i + 1, "beat": s.get("beat"), "seconds": s.get("seconds"), "end": d.get("end") or s.get("end_state")})
    return out


def inject_anchor(prompt: str, anchor: str) -> str:
    """Вставляет якорное предложение мира после первой фразы промпта (кадр -> мир -> действие).

    Если якорь уже есть (модель скопировала его), ничего не меняет.
    """
    anchor = (anchor or "").strip()
    prompt = (prompt or "").strip()
    if not anchor or not prompt:
        return prompt
    norm = lambda t: re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()  # noqa: E731
    if norm(anchor)[:60] in norm(prompt):
        return prompt
    if not anchor.endswith((".", "!", "?")):
        anchor += "."
    m = re.search(r"[.!?](\s+)", prompt)
    if m:
        return prompt[: m.start() + 1] + " " + anchor + prompt[m.start() + 1:]
    return prompt + " " + anchor


def ensure_anchor(plan: Plan) -> None:
    anchor = (plan.style or {}).get("anchor")
    if anchor:
        for s in plan.shots:
            s.prompt = inject_anchor(s.prompt, anchor)


class Planner:
    def __init__(self, llm: LLM, log=print):
        self.llm = llm
        self.log = log
        self.trace: list[dict] = []

    # ---------- публичный API ----------
    def plan(self, req: PlanRequest) -> Plan:
        preset = _preset(req.kind)
        high = req.quality == "high"
        fmt = req.format or preset["default_format"]
        if fmt not in FORMATS:
            raise ValueError(f"формат {fmt} не поддерживается")
        target = int(req.seconds or preset["default_seconds"])
        target = max(preset["min_seconds"], min(preset["max_seconds"], target))
        system = system_prompt(req, high)

        self.log(f"Планирую «{req.request[:70]}…»: {preset['label']}, ~{target} с, {fmt}, качество {req.quality}")
        outline = self._outline(system, req, target, fmt)
        acts = outline.get("acts") or []
        if not acts:
            raise RuntimeError("модель не вернула акты (acts)")
        self.log(f"Сюжет: «{outline.get('title')}» — {outline.get('logline')}")
        self.log(f"Актов: {len(acts)}, битов: {sum(len(a.get('beats') or []) for a in acts)}")

        raw_shots: list[dict] = []
        prev_tail: list[dict] = []
        for ai, act in enumerate(acts):
            got = self._write_act(system, req, outline, act, ai, prev_tail, high,
                                  opening=raw_shots[0] if raw_shots else None, history=raw_shots)
            raw_shots += got
            prev_tail = got[-2:]
            self.log(f"  акт {ai + 1}/{len(acts)} «{act.get('name')}»: {len(got)} сцен")

        plan = self._build_plan(req, outline, raw_shots, fmt, high)
        self._fit_duration(plan, target, high)
        self.director_review(plan, system)
        ensure_anchor(plan)
        plan = self.refine(plan, system, rounds=2)
        problems = validate(plan, req.quality)
        if problems:
            self.log("ВНИМАНИЕ, план требует правки: " + "; ".join(problems))
        return plan

    def director_review(self, plan: Plan, system: str | None = None) -> Plan:
        """Semantic text review; never claims to evaluate rendered frames."""
        if system is None:
            system = system_prompt(PlanRequest(request=plan.request or plan.title, kind=plan.kind,
                                   language=plan.language, quality=plan.quality or "high", loop=plan.loop),
                                   plan.is_high("high"))
        self.log("Режиссёрская проверка: замысел, постановка, непрерывность и выполнимость сцен")
        # Bounded batches with adjacent shots and a global opening/ending for long films.
        pending = {}
        notes = []
        for start in range(0, len(plan.shots), SHOTS_PER_CALL):
            batch = plan.shots[start:start + SHOTS_PER_CALL]
            context = {
                "request": plan.request, "creative_brief": plan.creative_brief, "style": plan.style,
                "characters": plan.characters, "locations": plan.locations, "loop": plan.loop,
                "format": plan.format, "opening": vars(plan.shots[0]) | {"sfx": []},
                "ending": vars(plan.shots[-1]) | {"sfx": []},
                "previous": plan.shots[start - 1].prompt if start else None,
                "next": plan.shots[start + len(batch)].prompt if start + len(batch) < len(plan.shots) else None,
                "shots": [{"id": s.id, "seconds": s.seconds, "beat": s.beat, "prompt": s.prompt,
                           "direction": s.direction, "transition": s.transition, "image": s.image} for s in batch],
            }
            user = ("Review this planned sequence against the ORIGINAL REQUEST, not generic cinematic taste. "
                    "Check missing or invented requirements, appearance and spatial continuity, contradictory camera "
                    "moves, action overload for the actual seconds, concrete light/materials, audio, and loop closure. "
                    "Fix only defective prompts and direction; keep IDs, beats, duration, transitions and intent. "
                    "Treat image paths as metadata, not images you have seen. Do not claim visual quality scores. "
                    "If a problem requires a new shot, a reference image or different timing, report it in notes. "
                    "Return JSON {\"shots\": [{\"id\": str, \"prompt\": str, \"direction\": "
                    "{\"start\": str, \"action\": str, \"camera\": str, \"end\": str}}], "
                    "\"notes\": [str]}. shots contains only necessary corrections; empty is valid. "
                    f"Notes language: {plan.language}.\n" + json.dumps(context, ensure_ascii=False))
            res = self._ask("director_review", system, user)
            if not isinstance(res.get("shots"), list) or not isinstance(res.get("notes"), list):
                raise LLMError("режиссёрская проверка: ожидаются списки shots и notes")
            allowed = {s.id for s in batch}
            for fix in res["shots"]:
                if (not isinstance(fix, dict) or fix.get("id") not in allowed
                        or fix["id"] in pending or not isinstance(fix.get("prompt"), str)
                        or not fix["prompt"].strip()):
                    raise LLMError("режиссёрская проверка вернула неизвестную/повторную сцену или пустой промпт")
                if "direction" in fix and (not isinstance(fix["direction"], dict)
                        or any(not isinstance(v, str) for v in fix["direction"].values())):
                    raise LLMError("режиссёрская проверка: direction должен быть объектом строк")
                pending[fix["id"]] = fix
            if any(not isinstance(n, str) for n in res["notes"]):
                raise LLMError("режиссёрская проверка: notes должен содержать строки")
            notes.extend(res["notes"])
        for shot in plan.shots:
            if shot.id in pending:
                fix = pending[shot.id]
                shot.prompt = fix["prompt"].strip()
                shot.direction = fix.get("direction", shot.direction)
        plan.review_notes = list(dict.fromkeys(notes))
        for note in plan.review_notes:
            self.log("Режиссёрская заметка: " + note)
        return plan

    def refine(self, plan: Plan, system: str | None = None, rounds: int = 2) -> Plan:
        """Линт + точечные исправления моделью. Можно вызывать для готового плана (studio review)."""
        if system is None:
            req = PlanRequest(request=plan.request or plan.title, kind=plan.kind, language=plan.language,
                              quality=plan.quality or "high", loop=plan.loop)
            system = system_prompt(req, plan.is_high("high"))
        for rnd in range(rounds):
            ensure_anchor(plan)          # правки модели могли потерять якорь мира
            issues = lint_plan(plan, plan.quality or "high")
            errs = errors_only(issues)
            if not errs:
                self.log(f"Промпты прошли проверку ({len(issues)} предупреждений)" if issues else "Промпты прошли проверку")
                return plan
            by = issues_by_shot([i for i in issues if i.shot_id != "*"])
            bad_ids = {i.shot_id for i in errs}
            self.log(f"Раунд правок {rnd + 1}: {len(bad_ids)} сцен с ошибками промпта")
            fixes = self._revise(system, plan, {sid: by[sid] for sid in bad_ids if sid in by})
            for s in plan.shots:
                f = fixes.get(s.id)
                if f:
                    if f.get("prompt"):
                        s.prompt = str(f["prompt"]).strip()
                    if isinstance(f.get("direction"), dict):
                        s.direction = {k: str(v) for k, v in f["direction"].items()}
                    if f.get("seconds"):
                        idx = plan.shots.index(s)
                        s.seconds = clamp_seconds(float(f["seconds"]), plan.is_high("high"),
                                                  conditioned=is_conditioned(s, idx, plan.loop and idx == len(plan.shots) - 1))
                    if "caption" in f and plan.captions.enabled:
                        s.caption = (str(f["caption"]).strip() or None) if f["caption"] else s.caption
        ensure_anchor(plan)
        remaining = errors_only(lint_plan(plan, plan.quality or "high"))
        if remaining:
            self.log("Остались проблемы в промптах: " + "; ".join(str(i) for i in remaining[:8]))
        return plan

    # ---------- этапы ----------
    def _ask(self, stage: str, system: str, user: str, max_tokens: int = 16000) -> dict:
        t = time.time()
        res = self.llm.complete_json(system, user, max_tokens=max_tokens)
        self.trace.append({"stage": stage, "seconds": round(time.time() - t, 1), "usage": getattr(self.llm, "last_usage", {})})
        return res

    def _outline(self, system: str, req: PlanRequest, target: int, fmt: str) -> dict:
        preset = _preset(req.kind)
        lo, hi = preset["shot_seconds"]
        avg = (lo + hi) / 2
        user = (f"PRODUCER'S REQUEST: {req.request}\n\n"
                f"Target duration: {target} seconds total. Aspect ratio: {fmt}. Expected number of shots: about "
                f"{max(1, round(target / avg))} (shots of {lo}-{hi} s).\n")
        if req.kind == "episode" and req.series_bible:
            user += f"This is episode {req.episode or len(req.series_bible.get('episodes', [])) + 1} of the series.\n"
        if req.music == "none":
            user += "No music will be added; set music.file to null.\n"
        elif req.music != "auto":
            user += f"The producer chose the music track {req.music}; set music.file to that string and describe its mood.\n"
        elif not (req.library or {}).get("music"):
            user += "The sound library is empty: set music.file to null but still describe the intended music mood.\n"
        if req.notes:
            user += f"Additional instructions for this piece: {req.notes}\n"
        user += "\n" + OUTLINE_SCHEMA
        return self._ask("outline", system, user)

    def _write_act(self, system: str, req: PlanRequest, outline: dict, act: dict, index: int,
                   prev_tail: list[dict], high: bool, opening: dict | None = None,
                   history: list[dict] | None = None) -> list[dict]:
        beats = act.get("beats") or []
        act_seconds = int(act.get("seconds") or 0)
        context = {k: outline.get(k) for k in ("title", "logline", "synopsis", "style", "characters", "locations", "creative_brief")}
        user = (f"ORIGINAL PRODUCER REQUEST: {req.request}\nPROJECT NOTES: {req.notes}\n"
                f"FILM CONTEXT:\n{json.dumps(context, ensure_ascii=False)}\n\n"
                f"ALL ACTS (for orientation): {json.dumps([{'name': a.get('name'), 'seconds': a.get('seconds')} for a in outline.get('acts', [])], ensure_ascii=False)}\n\n"
                f"NOW WRITE ACT {index + 1}: \"{act.get('name')}\", {act_seconds} seconds, beats:\n"
                + "\n".join(f"{i + 1}. {b}" for i, b in enumerate(beats)))
        if req.loop and opening:
            user += "\nLOOP OPENING TO RETURN TO:\n" + json.dumps(opening, ensure_ascii=False)
        if history:
            user += "\n\nSTATE LEDGER OF ALL EARLIER SHOTS (beat and end state; your first shot starts from the last end state):\n" \
                    + json.dumps(ledger(history), ensure_ascii=False)
        if prev_tail:
            user += ("\n\nLAST SHOTS OF THE PREVIOUS ACT IN FULL (for continuity, do not repeat them):\n"
                     + json.dumps([{"seconds": s.get("seconds"), "prompt": s.get("prompt"), "direction": s.get("direction")}
                                   for s in prev_tail], ensure_ascii=False))
        else:
            user += "\n\nThis is the beginning of the film: the first shot has transition \"cut\"."
        want_caps = req.captions if req.captions is not None else _preset(req.kind)["captions"]
        user += ("\n\nCaptions: " + ("every shot gets a short caption in " + req.language if want_caps else "null for all shots")
                 + ". Narration: only if the producer asked for voice-over, else null.")
        user += "\n\n" + SHOTS_SCHEMA
        # большие акты режем на части, чтобы ответ не упирался в лимит токенов
        if len(beats) > SHOTS_PER_CALL:
            shots: list[dict] = []
            for start in range(0, len(beats), SHOTS_PER_CALL):
                chunk = beats[start:start + SHOTS_PER_CALL]
                part_secs = round(act_seconds * len(chunk) / len(beats))
                u = user.replace(f"{act_seconds} seconds, beats:\n" + "\n".join(f"{i + 1}. {b}" for i, b in enumerate(beats)),
                                 f"{part_secs} seconds, beats:\n" + "\n".join(f"{start + i + 1}. {b}" for i, b in enumerate(chunk)))
                if shots:
                    u += "\n\nSTATE LEDGER OF THIS ACT SO FAR:\n" + json.dumps(ledger(shots), ensure_ascii=False)
                    u += "\n\nPREVIOUS SHOTS OF THIS ACT IN FULL:\n" + json.dumps(
                        [{"seconds": s.get("seconds"), "prompt": s.get("prompt"), "direction": s.get("direction")}
                         for s in shots[-2:]], ensure_ascii=False)
                    if req.loop and not opening:
                        u += "\nLOOP OPENING TO RETURN TO:\n" + json.dumps(shots[0], ensure_ascii=False)
                res = self._ask(f"shots_act{index + 1}_{start}", system, u)
                shots += list(res.get("shots") or [])
            return shots
        res = self._ask(f"shots_act{index + 1}", system, user)
        return list(res.get("shots") or [])

    def _revise(self, system: str, plan: Plan, issues: dict[str, list[Issue]]) -> dict[str, dict]:
        if not issues:
            return {}
        items = []
        for sid, iss in issues.items():
            shot = next((s for s in plan.shots if s.id == sid), None)
            if shot is None:
                continue
            idx = plan.shots.index(shot)
            items.append({"id": sid, "seconds": shot.seconds, "prompt": shot.prompt, "caption": shot.caption,
                          "direction": shot.direction, "transition": shot.transition,
                          "previous_prompt": plan.shots[idx - 1].prompt if idx else None,
                          "previous_end_state": (plan.shots[idx - 1].direction or {}).get("end") if idx else None,
                          "problems": [f"{i.code}: {i.message}" for i in iss]})
        user = (f"ORIGINAL REQUEST: {plan.request}\nCREATIVE BRIEF: {json.dumps(plan.creative_brief, ensure_ascii=False)}\n"
                f"WORLD ANCHOR (must stay verbatim in every prompt): {plan.style.get('anchor') or '(none)'}\n"
                f"FILM: {plan.title}. Style: {json.dumps(plan.style, ensure_ascii=False)}. "
                f"Characters: {json.dumps(plan.characters, ensure_ascii=False)}\n\n"
                f"Fix these shots:\n{json.dumps(items, ensure_ascii=False, indent=1)}\n\n{REVISE_SCHEMA}")
        res = self._ask("revise", system, user)
        return {str(s.get("id")): s for s in res.get("shots") or [] if s.get("id")}

    # ---------- сборка плана ----------
    def _build_plan(self, req: PlanRequest, outline: dict, raw_shots: list[dict], fmt: str, high: bool) -> Plan:
        preset = _preset(req.kind)
        want_caps = req.captions if req.captions is not None else preset["captions"]
        shots: list[Shot] = []
        lib_files = {e["file"] for kind in ("music", "sfx") for e in (req.library or {}).get(kind, [])}
        for i, r in enumerate(raw_shots):
            if not str(r.get("prompt", "")).strip():
                continue
            tr = str(r.get("transition") or "cut").lower()
            if tr not in ("cut", "continue", "dissolve") or i == 0:
                tr = "cut"
            secs = clamp_seconds(float(r.get("seconds") or 6), high,
                                 conditioned=(tr == "continue") or (req.loop and i == len(raw_shots) - 1))
            sfx = []
            for x in r.get("sfx") or []:
                if isinstance(x, dict) and x.get("file") in lib_files:
                    sfx.append(Sfx(file=x["file"], offset=float(x.get("offset", 0)), volume=float(x.get("volume", 0.8))))
            shots.append(Shot(id=f"{len(shots) + 1:03d}", seconds=secs, prompt=str(r["prompt"]).strip(), transition=tr,
                              transition_seconds=float(r.get("transition_seconds") or 0.5),
                              caption=(str(r["caption"]).strip() or None) if (want_caps and r.get("caption")) else None,
                              narration=(str(r["narration"]).strip() or None) if r.get("narration") else None,
                              sfx=sfx, beat=r.get("beat"), direction=dict(r.get("direction") or {})))
        if not shots:
            raise RuntimeError("модель не вернула ни одной сцены")
        music = None
        m = outline.get("music") or {}
        if req.music == "none":
            music = None
        elif req.music != "auto":
            music = Music(file=req.music, mood=m.get("mood"), volume=float(m.get("volume", 0.25) or 0.25),
                          duck=bool(m.get("duck", True)))
        else:
            file = m.get("file") if m.get("file") in lib_files else None
            music = Music(file=file, mood=m.get("mood"), volume=float(m.get("volume", 0.25) or 0.25),
                          duck=bool(m.get("duck", True))) if (file or m.get("mood")) else None
        title = str(outline.get("title") or req.request[:40])
        slug = req.name or slugify(title)
        characters = [{"name": c.get("name"), "descriptor": c.get("descriptor"), "description": c.get("description"),
                       "voice": c.get("voice")} for c in outline.get("characters") or [] if isinstance(c, dict)]
        plan = Plan(title=title, shots=shots, slug=slug, kind=req.kind, format=fmt, quality=req.quality,
                    seed=req.seed if req.seed is not None else int(time.time()) % 100000, language=req.language,
                    logline=outline.get("logline"), synopsis=outline.get("synopsis"), style=dict(outline.get("style") or {}),
                    characters=characters, locations=list(outline.get("locations") or []),
                    series=(req.series_bible or {}).get("slug"), episode=req.episode, music=music,
                    captions=Captions(enabled=bool(want_caps)), request=req.request, loop=req.loop,
                    creative_brief=dict(outline.get("creative_brief") or {}) | {"project_notes": req.notes})
        if req.kind == "short":
            plan.fade_in, plan.fade_out = 0.0, 0.4
        if req.loop:
            plan.fade_in, plan.fade_out = 0.0, 0.0
        normalize_durations(plan)
        return plan

    def _fit_duration(self, plan: Plan, target: int, high: bool) -> None:
        """Если модель промахнулась по хронометражу больше чем на 15 %, масштабируем сцены."""
        total = sum(s.seconds for s in plan.shots)
        if total <= 0:
            return
        ratio = target / total
        if abs(1 - ratio) <= 0.15:
            return
        self.log(f"Хронометраж {total:.0f} с вместо {target} с — подгоняю длительности сцен")
        for i, s in enumerate(plan.shots):
            s.seconds = clamp_seconds(s.seconds * ratio, high, conditioned=is_conditioned(s, i, plan.loop and i == len(plan.shots) - 1))


def plan_summary(plan: Plan, cfg: dict | None = None) -> str:
    high = plan.is_high((cfg or {}).get("quality", "fast"))
    w, h = plan.size(high)
    per_shot_min = 3.2 if high else 1.3           # эмпирически по логам: включает загрузку модели в каждую сцену
    minutes = len(plan.shots) * per_shot_min + 6   # + установка/склейка
    price = float((cfg or {}).get("gpu_price_per_hour", 2.5))
    lines = [f"«{plan.title}» — {KIND_PRESETS.get(plan.kind, {}).get('label', plan.kind)}, {plan.format} {w}x{h}, "
             f"качество {'high (DFR)' if high else 'fast'}",
             f"Сцен: {len(plan.shots)}, хронометраж ≈ {plan.total_seconds:.0f} с ({plan.total_seconds / 60:.1f} мин)",
             f"Оценка рендера: ~{minutes:.0f} мин GPU ≈ ${minutes / 60 * price:.2f} при ${price}/ч"]
    if plan.logline:
        lines.append(f"Логлайн: {plan.logline}")
    if plan.music and (plan.music.file or plan.music.mood):
        lines.append(f"Музыка: {plan.music.file or '(трек не выбран)'} — {plan.music.mood or ''}")
    if plan.captions.enabled:
        lines.append(f"Субтитры: {sum(1 for s in plan.shots if s.caption)} из {len(plan.shots)} сцен")
    tr = {t: sum(1 for s in plan.shots if s.transition == t) for t in ("cut", "continue", "dissolve")}
    lines.append(f"Переходы: cut {tr['cut']}, continue {tr['continue']}, dissolve {tr['dissolve']}" + (" · бесшовный луп" if plan.loop else ""))
    return "\n".join(lines)
