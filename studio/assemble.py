"""Сборка фильма из клипов одним проходом ffmpeg: без видимых швов.

Что делает:
- нормализует каждый клип (размер, fps, кодеки, стерео 48 кГц), выравнивает длину
  звука по видео;
- соединяет сцены: cut (жёсткая склейка с микро-фейдом звука против щелчков),
  continue (клип начат с последнего кадра предыдущего: убираем дублирующийся
  первый кадр), dissolve (xfade + acrossfade);
- подмешивает музыку (луп, фейды, приглушение под речь через sidechain),
  звуковые эффекты и закадровый голос в нужные моменты таймлайна;
- жжёт субтитры (ASS) для шортсов, если в ffmpeg есть libass;
- по умолчанию отдаёт звук модели как есть (режим raw); в режиме leveled выравнивает
  сцены между собой и общую громкость под платформы (-14 LUFS) с лимитером.

Модуль не зависит от остального пакета, кроме schema, и одинаково работает на
GPU-Pod (Ubuntu) и локально (macOS).
"""
from __future__ import annotations

import functools
import json
import pathlib
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field

from .schema import FPS

CUT_AUDIO_FADE = 0.06      # с: микро-фейд на краях клипов при жёсткой склейке (убирает щелчки)
DUCK = dict(threshold=0.05, ratio=3, attack=250, release=1200)
LOUDNORM_TARGET = dict(I=-14.0, TP=-1.5, LRA=11.0)   # YouTube/TikTok
# Выравнивание сцен между собой: LTX отдаёт клипы с разбросом уровня в 40 дБ (−9 … −50 LUFS).
# Постоянное усиление на клип, ограниченное сверху, чтобы почти тишина не превращалась в шипение.
CLIP_TARGET_LUFS = -18.0
CLIP_MAX_BOOST_DB = 18.0
CLIP_MAX_CUT_DB = 12.0


class AssembleError(RuntimeError):
    pass


@dataclass
class ClipSpec:
    path: str
    shot_id: str = ""
    transition: str = "cut"          # соединение с предыдущим клипом
    transition_seconds: float = 0.5
    caption: str | None = None
    sfx: list[tuple[str, float, float]] = field(default_factory=list)   # (файл, смещение с, громкость)
    narration: str | None = None     # путь к аудиофайлу озвучки
    trim_end: float = 0.0            # с: отрезать с конца (луп: последний кадр дублирует первый кадр фильма)
    gain_db: float = 0.0             # выравнивание громкости сцены (см. clip_gain_db)
    voices: list[tuple[str, float, float]] = field(default_factory=list)  # реплики звуковой студии (файл, смещение, громкость)
    audio_volume: float = 1.0        # звук самой LTX: 0 — заглушён (его заменили фоли и реплики)


@dataclass
class Segment:
    clip: ClipSpec
    start: float      # позиция в итоговом фильме
    end: float
    duration: float   # длительность клипа после обрезки


@dataclass
class AssembleOptions:
    width: int
    height: int
    fps: int = FPS
    music_path: str | None = None
    music_volume: float = 0.25
    music_duck: bool = True
    music_fade_in: float = 1.0
    music_fade_out: float = 2.5
    captions: bool = False
    caption_position: str = "bottom"
    caption_font_size: int = 0
    fade_in: float = 0.5
    fade_out: float = 1.5
    leveling: bool = False     # выравнивать громкость сцен между собой (по умолчанию звук модели как есть)
    loudnorm: bool = False     # общая громкость к -14 LUFS с лимитером (тоже только в режиме leveled)
    crf: int = 18
    preset: str = "medium"


# ---------- ffmpeg helpers ----------
def ffmpeg_bin() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


def ffprobe_bin() -> str:
    return shutil.which("ffprobe") or "ffprobe"


@functools.lru_cache(maxsize=None)
def ffmpeg_has_filter(name: str) -> bool:
    try:
        out = subprocess.run([ffmpeg_bin(), "-hide_banner", "-filters"], capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.TimeoutExpired):
        return False
    return any(line.split()[1:2] == [name] for line in out.splitlines() if line.strip())


def probe(path: str | pathlib.Path) -> dict:
    """{'duration': float, 'width': int, 'height': int, 'has_audio': bool, 'fps': float}"""
    cmd = [ffprobe_bin(), "-v", "error", "-show_entries",
           "format=duration:stream=codec_type,width,height,r_frame_rate,nb_frames,duration", "-of", "json", str(path)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise AssembleError(f"ffprobe не прочитал {path}: {r.stderr.strip()[:300]}")
    info = json.loads(r.stdout or "{}")
    out = {"duration": float((info.get("format") or {}).get("duration") or 0), "width": 0, "height": 0,
           "has_audio": False, "fps": float(FPS)}
    for s in info.get("streams", []):
        if s.get("codec_type") == "video" and not out["width"]:
            out["width"], out["height"] = int(s.get("width", 0)), int(s.get("height", 0))
            num, _, den = str(s.get("r_frame_rate", "24/1")).partition("/")
            try:
                out["fps"] = float(num) / float(den or 1)
            except (ValueError, ZeroDivisionError):
                pass
            vdur = s.get("duration")
            nbf = s.get("nb_frames")
            if nbf and str(nbf).isdigit() and out["fps"]:
                out["duration"] = int(nbf) / out["fps"]
            elif vdur:
                out["duration"] = float(vdur)
        elif s.get("codec_type") == "audio":
            out["has_audio"] = True
    return out


@functools.lru_cache(maxsize=None)
def ffmpeg_major() -> int:
    try:
        out = subprocess.run([ffmpeg_bin(), "-version"], capture_output=True, text=True, timeout=30).stdout
        m = re.search(r"ffmpeg version n?(\d+)", out)
        return int(m.group(1)) if m else 0
    except (OSError, subprocess.TimeoutExpired):
        return 0


def _filter_complex_args(graph: str, script: pathlib.Path) -> list[str]:
    """Граф передаём инлайн (переносимо между версиями ffmpeg); очень большой — файлом.

    ffmpeg 7+ читает опцию из файла синтаксисом `-/filter_complex FILE`, старые версии —
    `-filter_complex_script FILE`.
    """
    if len(graph) < 100_000:
        return ["-filter_complex", graph.replace("\n", "")]
    return ["-/filter_complex", str(script)] if ffmpeg_major() >= 7 else ["-filter_complex_script", str(script)]


def measure_loudness(path: str | pathlib.Path) -> float | None:
    """Интегральная громкость файла (LUFS, EBU R128) или None, если звука нет / не измерить."""
    r = subprocess.run([ffmpeg_bin(), "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af", "ebur128", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.search(r"Summary:.*?I:\s*(-?[\d.]+)\s*LUFS", r.stderr, re.S)
    if not m:
        return None
    val = float(m.group(1))
    return None if val <= -70 else val      # -70 = тишина по R128


def quiet_shots(levels: dict, gap_db: float = 18.0) -> list[str]:
    """Сцены, которые тише медианы фильма больше чем на gap_db (в режиме raw слышны как провалы звука)."""
    vals = sorted(v for v in levels.values() if v is not None)
    if len(vals) < 2:
        return []
    median = vals[len(vals) // 2]
    return [k for k, v in levels.items() if v is None or v < median - gap_db]


def clip_gain_db(lufs: float | None, target: float = CLIP_TARGET_LUFS, max_boost: float = CLIP_MAX_BOOST_DB,
                 max_cut: float = CLIP_MAX_CUT_DB) -> float:
    """Постоянное усиление клипа к целевому уровню, ограниченное сверху и снизу."""
    if lufs is None:
        return 0.0
    return round(max(-max_cut, min(max_boost, target - lufs)), 1)


def measure_graph_loudness(cmd_inputs: list[str], graph_audio: str, cwd: str) -> dict | None:
    """Первый проход: громкость собранного аудио (без видео) для линейного loudnorm."""
    g = graph_audio + ";\n[aout]loudnorm=I={I}:TP={TP}:LRA={LRA}:print_format=json[anorm]".format(**LOUDNORM_TARGET)
    cmd = [ffmpeg_bin(), "-hide_banner", "-nostats", *cmd_inputs, "-filter_complex", g.replace("\n", ""),
           "-map", "[anorm]", "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def loudnorm_filter(measured: dict | None) -> str:
    """Финальная громкость: постоянный коэффициент по замеру + true-peak лимитер.

    `loudnorm ... linear=true` молча переходит в динамический режим, если пики выше цели, и тогда
    тихие сцены снова накачиваются до шипения. Поэтому считаем усиление сами: к целевой громкости,
    но так, чтобы пики не превысили цель больше чем на 3 дБ (их съедает лимитер).
    Без замеров — однопроходный loudnorm как запасной вариант.
    """
    tp_limit = 10 ** (LOUDNORM_TARGET["TP"] / 20)
    limiter = f"alimiter=limit={tp_limit:.4f}:attack=5:release=80:level=false"
    if not measured:
        return "loudnorm=I={I}:TP={TP}:LRA={LRA}".format(**LOUDNORM_TARGET)
    try:
        in_i, in_tp = float(measured["input_i"]), float(measured["input_tp"])
    except (KeyError, ValueError):
        return "loudnorm=I={I}:TP={TP}:LRA={LRA}".format(**LOUDNORM_TARGET)
    gain = LOUDNORM_TARGET["I"] - in_i
    gain = min(gain, LOUDNORM_TARGET["TP"] - in_tp + 6.0)      # до 6 дБ пиков съедает лимитер
    gain = max(-30.0, min(30.0, gain))
    return f"volume={gain:+.2f}dB,{limiter}"


def run(cmd: list[str], logf=None, cwd: str | None = None) -> int:
    if logf is not None:
        logf.write("\n$ " + " ".join(shlex.quote(c) for c in cmd) + "\n")
        logf.flush()
    return subprocess.call(cmd, stdout=logf, stderr=subprocess.STDOUT, cwd=cwd)


def normalize_cmd(src: pathlib.Path, dst: pathlib.Path, w: int, h: int, fps: int, src_has_audio: bool,
                  crf: int = 16) -> list[str]:
    """Единый формат для склейки; звук подгоняется под длину видео (apad + shortest)."""
    vf = (f"scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos,"
          f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,fps={fps},format=yuv420p")
    cmd = [ffmpeg_bin(), "-y", "-loglevel", "error", "-i", str(src)]
    if src_has_audio:
        cmd += ["-map", "0:v:0", "-map", "0:a:0", "-af", "aresample=48000,apad"]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-map", "0:v:0", "-map", "1:a:0"]
    cmd += ["-shortest", "-vf", vf, "-c:v", "libx264", "-crf", str(crf), "-preset", "medium", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "192k", "-movflags", "+faststart", str(dst)]
    return cmd


def normalize(src: pathlib.Path, dst: pathlib.Path, w: int, h: int, fps: int = FPS, logf=None) -> bool:
    info = probe(src)
    code = run(normalize_cmd(src, dst, w, h, fps, info["has_audio"]), logf)
    return code == 0 and dst.exists() and dst.stat().st_size > 0


# ---------- таймлайн и граф фильтров ----------
def build_timeline(clips: list[ClipSpec], durations: list[float], fps: int = FPS) -> list[Segment]:
    segs: list[Segment] = []
    cur = 0.0
    for i, (c, dur) in enumerate(zip(clips, durations)):
        trim = (1 / fps) if (i > 0 and c.transition == "continue") else 0.0
        d = max(0.1, dur - trim - c.trim_end)
        if i == 0:
            start = 0.0
            cur = d
        elif c.transition == "dissolve":
            x = _xfade_len(c.transition_seconds, d, cur)
            start = cur - x
            cur = cur + d - x
        else:
            start = cur
            cur += d
        segs.append(Segment(clip=c, start=round(start, 3), end=round(cur, 3), duration=round(d, 3)))
    return segs


def _xfade_len(requested: float, this_dur: float, prev_total: float) -> float:
    return round(max(0.2, min(requested, this_dur / 2, prev_total / 2)), 3)


def _ass_time(t: float) -> str:
    t = max(0.0, t)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def write_ass(segments: list[Segment], w: int, h: int, position: str = "bottom", font_size: int = 0) -> str:
    size = font_size or max(28, round(h * 0.042))
    margin_v = round(h * (0.17 if position == "bottom" else 0.0))
    align = 2 if position == "bottom" else 5
    outline = max(2, round(size * 0.07))
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,DejaVu Sans,{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{outline},1,{align},{round(w * 0.08)},{round(w * 0.08)},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for seg in segments:
        if seg.clip.caption:
            start = seg.start + 0.15
            end = max(start + 0.8, seg.end - 0.15)
            lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Cap,,0,0,0,,{_ass_escape(seg.clip.caption)}")
    return header + "\n".join(lines) + "\n"


def build_graph(clips: list[ClipSpec], durations: list[float], opts: AssembleOptions, extra_inputs: list[str],
                ass_name: str | None, loudnorm: str | None = None, audio_only: bool = False) -> tuple[str, list[Segment], float]:
    """Возвращает (filter_complex, таймлайн, длительность фильма).

    Входы ffmpeg: 0..n-1 — клипы, далее extra_inputs в порядке: музыка (если есть),
    затем файлы sfx/озвучки в порядке появления в `extra_inputs`.
    """
    n = len(clips)
    fps = opts.fps
    segs = build_timeline(clips, durations, fps)
    total = segs[-1].end
    lines: list[str] = []
    fade = CUT_AUDIO_FADE
    for i, (c, dur) in enumerate(zip(clips, durations)):
        trim = (1 / fps) if (i > 0 and c.transition == "continue") else 0.0
        d = segs[i].duration
        end = trim + d
        if not audio_only:
            lines.append(f"[{i}:v]trim=start={trim:.4f}:end={end:.4f},setpts=PTS-STARTPTS,fps={fps},"
                         f"format=yuv420p,settb=AVTB[v{i}]")
        # усиленный клип тут же ограничиваем по пикам (-3 dBTP): транзиенты тихих сцен иначе
        # задирают пик всего фильма и не дают поднять общий уровень
        gain = f"volume={c.gain_db:+.1f}dB," if abs(c.gain_db) >= 0.05 else ""
        if abs(c.audio_volume - 1.0) > 1e-3:
            gain = f"volume={max(0.0, c.audio_volume):.3f}," + gain
        if c.gain_db > 0.05:
            gain += f"alimiter=limit={10 ** (-3 / 20):.4f}:attack=5:release=80:level=false,"
        lines.append(f"[{i}:a]atrim=start={trim:.4f}:end={end:.4f},asetpts=PTS-STARTPTS,"
                     f"aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,{gain}apad=whole_dur={d:.4f},"
                     f"atrim=end={d:.4f},afade=t=in:st=0:d={fade},afade=t=out:st={max(0.0, d - fade):.4f}:d={fade}[a{i}]")
    cur_v, cur_a, cur_dur = "[v0]", "[a0]", segs[0].duration
    for i in range(1, n):
        c, d = clips[i], segs[i].duration
        if c.transition == "dissolve":
            x = _xfade_len(c.transition_seconds, d, cur_dur)
            if not audio_only:
                lines.append(f"{cur_v}[v{i}]xfade=transition=fade:duration={x}:offset={cur_dur - x:.4f}[vx{i}]")
            lines.append(f"{cur_a}[a{i}]acrossfade=d={x}:c1=tri:c2=tri[ax{i}]")
            cur_dur = cur_dur + d - x
        else:
            if not audio_only:
                lines.append(f"{cur_v}[v{i}]concat=n=2:v=1:a=0[vx{i}]")
            lines.append(f"{cur_a}[a{i}]concat=n=2:v=0:a=1[ax{i}]")
            cur_dur += d
        cur_v, cur_a = f"[vx{i}]", f"[ax{i}]"
    # видео: фейды фильма и субтитры
    if not audio_only:
        vchain = []
        if opts.fade_in > 0:
            vchain.append(f"fade=t=in:st=0:d={opts.fade_in}")
        if opts.fade_out > 0:
            vchain.append(f"fade=t=out:st={max(0.0, total - opts.fade_out):.3f}:d={opts.fade_out}")
        if ass_name:
            vchain.append(f"ass={ass_name}")
        lines.append(f"{cur_v}{','.join(vchain) if vchain else 'copy'}[vout]")
    # аудио: диалоги/эмбиент + озвучка -> (sidechain) музыка -> sfx -> loudnorm
    idx = n
    music_label = None
    if opts.music_path:
        music_in = idx
        idx += 1
        fo_start = max(0.0, total - opts.music_fade_out)
        lines.append(f"[{music_in}:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
                     f"atrim=end={total:.3f},asetpts=PTS-STARTPTS,volume={opts.music_volume},"
                     f"afade=t=in:st=0:d={opts.music_fade_in},afade=t=out:st={fo_start:.3f}:d={opts.music_fade_out}[mus0]")
        music_label = "[mus0]"
    event_labels: list[str] = []
    nar_labels: list[str] = []
    for seg in segs:
        if seg.clip.narration:
            at_ms = int(round((seg.start + 0.25) * 1000))
            lines.append(f"[{idx}:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
                         f"adelay={at_ms}|{at_ms},apad=whole_dur={total:.3f},atrim=end={total:.3f}[nar{idx}]")
            nar_labels.append(f"[nar{idx}]")
            idx += 1
        for (_, offset, vol) in seg.clip.voices:
            at_ms = int(round(max(0.0, seg.start + offset) * 1000))
            lines.append(f"[{idx}:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
                         f"volume={vol},adelay={at_ms}|{at_ms},apad=whole_dur={total:.3f},atrim=end={total:.3f}[vox{idx}]")
            nar_labels.append(f"[vox{idx}]")
            idx += 1
        for (_, offset, vol) in seg.clip.sfx:
            at_ms = int(round(max(0.0, seg.start + offset) * 1000))
            lines.append(f"[{idx}:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
                         f"volume={vol},adelay={at_ms}|{at_ms},apad=whole_dur={total:.3f},atrim=end={total:.3f}[sfx{idx}]")
            event_labels.append(f"[sfx{idx}]")
            idx += 1
    dlg = cur_a
    if nar_labels:
        lines.append(f"{dlg}{''.join(nar_labels)}amix=inputs={1 + len(nar_labels)}:duration=first:normalize=0[dlg]")
        dlg = "[dlg]"
    mix_inputs = [dlg]
    if music_label:
        if opts.music_duck:
            lines.append(f"{dlg}asplit=2[dlgA][dlgSC]")
            lines.append(f"{music_label}[dlgSC]sidechaincompress=threshold={DUCK['threshold']}:ratio={DUCK['ratio']}:"
                         f"attack={DUCK['attack']}:release={DUCK['release']}[mus]")
            mix_inputs = ["[dlgA]", "[mus]"]
        else:
            mix_inputs.append(music_label)
    mix_inputs += event_labels
    if len(mix_inputs) > 1:
        lines.append(f"{''.join(mix_inputs)}amix=inputs={len(mix_inputs)}:duration=first:normalize=0[mix]")
        a = "[mix]"
    else:
        a = mix_inputs[0]
    if audio_only:
        lines.append(f"{a}anull[aout]")                       # первый проход: сырой микс для замера
    else:
        tail = ((loudnorm or loudnorm_filter(None)) + ",aresample=48000") if opts.loudnorm else "aresample=48000"
        lines.append(f"{a}{tail}[aout]")
    return ";\n".join(lines), segs, total


def assemble(clips: list[ClipSpec], out_path: pathlib.Path, opts: AssembleOptions, workdir: pathlib.Path,
             logf=None, log=print) -> dict:
    """Нормализует клипы и собирает фильм. Возвращает отчёт с таймлайном."""
    if not clips:
        raise AssembleError("нет клипов для сборки")
    # ffmpeg запускается из workdir (ради ass=captions.ass), поэтому все пути делаем абсолютными
    workdir = workdir.resolve()
    out_path = pathlib.Path(out_path).resolve()
    absf = lambda x: str(pathlib.Path(x).resolve()) if x else x  # noqa: E731
    clips = [ClipSpec(path=absf(c.path), shot_id=c.shot_id, transition=c.transition, transition_seconds=c.transition_seconds,
                      caption=c.caption, sfx=[(absf(f), o, v) for (f, o, v) in c.sfx], narration=absf(c.narration),
                      trim_end=c.trim_end, gain_db=c.gain_db, voices=[(absf(f), o, v) for (f, o, v) in c.voices],
                      audio_volume=c.audio_volume) for c in clips]
    if opts.music_path:
        opts = AssembleOptions(**{**opts.__dict__, "music_path": absf(opts.music_path)})
    workdir.mkdir(parents=True, exist_ok=True)
    norm_dir = workdir / "norm"
    norm_dir.mkdir(exist_ok=True)
    normalized: list[ClipSpec] = []
    durations: list[float] = []
    levels: dict[str, float | None] = {}
    for c in clips:
        src = pathlib.Path(c.path)
        dst = norm_dir / (src.stem + ".mp4")
        if not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
            if not normalize(src, dst, opts.width, opts.height, opts.fps, logf):
                raise AssembleError(f"не удалось нормализовать {src.name}")
        info = probe(dst)
        gain = 0.0
        lufs = measure_loudness(dst)
        levels[c.shot_id] = lufs
        if opts.leveling:
            gain = clip_gain_db(lufs)
            if logf is not None:
                logf.write(f"\n# clip {c.shot_id}: {lufs if lufs is not None else '—'} LUFS -> gain {gain:+.1f} dB\n")
        normalized.append(ClipSpec(path=str(dst), shot_id=c.shot_id, transition=c.transition,
                                   transition_seconds=c.transition_seconds, caption=c.caption, sfx=c.sfx,
                                   narration=c.narration, trim_end=c.trim_end, gain_db=gain, voices=c.voices,
                                   audio_volume=c.audio_volume))
        durations.append(info["duration"])
    # дополнительные входы в том же порядке, в котором граф их нумерует
    extra: list[str] = []
    extra_pre: list[list[str]] = []
    if opts.music_path:
        extra_pre.append(["-stream_loop", "-1"])
        extra.append(opts.music_path)
    segs_tmp = build_timeline(normalized, durations, opts.fps)
    for seg in segs_tmp:
        if seg.clip.narration:
            extra_pre.append([])
            extra.append(seg.clip.narration)
        for (f, _, _) in seg.clip.voices:
            extra_pre.append([])
            extra.append(f)
        for (f, _, _) in seg.clip.sfx:
            extra_pre.append([])
            extra.append(f)
    ass_name = None
    use_captions = opts.captions and any(c.caption for c in normalized)
    if use_captions:
        if ffmpeg_has_filter("ass"):
            ass_name = "captions.ass"
            (workdir / ass_name).write_text(write_ass(segs_tmp, opts.width, opts.height, opts.caption_position,
                                                      opts.caption_font_size), encoding="utf-8")
        else:
            log("ВНИМАНИЕ: в этом ffmpeg нет libass — субтитры пропущены (на RunPod они будут)")
    inputs: list[str] = []
    for c in normalized:
        inputs += ["-i", c.path]
    for pre, path in zip(extra_pre, extra):
        inputs += pre + ["-i", path]
    loudnorm = None
    if opts.loudnorm:
        # первый проход: замер громкости микса -> линейный (постоянный) loudnorm вместо динамической накачки тишины
        graph_a, _, _ = build_graph(normalized, durations, opts, extra, None, audio_only=True)
        measured = measure_graph_loudness(inputs, graph_a, str(workdir))
        loudnorm = loudnorm_filter(measured)
        if logf is not None:
            logf.write(f"\n# loudness pass 1: {json.dumps(measured) if measured else 'n/a'}\n# loudnorm: {loudnorm}\n")
        if not measured:
            log("ВНИМАНИЕ: замер громкости не удался, используется однопроходный loudnorm")
    graph, segs, total = build_graph(normalized, durations, opts, extra, ass_name, loudnorm=loudnorm)
    script = workdir / "filter_complex.txt"
    script.write_text(graph, encoding="utf-8")
    cmd = [ffmpeg_bin(), "-y", "-loglevel", "error", *inputs]
    cmd += _filter_complex_args(graph, script) + ["-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-crf", str(opts.crf), "-preset", opts.preset, "-pix_fmt", "yuv420p", "-r", str(opts.fps),
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", "-t", f"{total:.3f}",
            str(out_path)]
    code = run(cmd, logf, cwd=str(workdir))
    if code != 0 or not out_path.exists():
        raise AssembleError(f"ffmpeg завершился с кодом {code}; граф фильтров: {script}")
    timeline = [{"shot": s.clip.shot_id, "start": s.start, "end": s.end, "transition": s.clip.transition,
                 "caption": s.clip.caption} for s in segs]
    report = {"film": str(out_path), "seconds": round(total, 2), "resolution": f"{opts.width}x{opts.height}",
              "shots": len(clips), "music": bool(opts.music_path), "captions": bool(ass_name), "timeline": timeline,
              "audio": "leveled" if (opts.leveling or opts.loudnorm) else "raw",
              "clip_lufs": levels, "quiet_shots": quiet_shots(levels),
              "clip_gains_db": {c.shot_id: c.gain_db for c in normalized}, "loudnorm": loudnorm}
    (workdir / "timeline.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=1), encoding="utf-8")
    return report
