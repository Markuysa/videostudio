"""Фото-референсы: эстетика для всего фильма и первые кадры сцен.

Три роли:
- style   — только эстетика (палитра, свет, оптика, фактура); Claude выводит из фото стилевую библию и якорь;
- frame   — фото становится первым кадром одной из сцен, Claude строит сцену вокруг него;
- opening — то же, но строго первая сцена фильма.

LTX-2.5 не умеет «перенос стиля по картинке», поэтому эстетика переносится текстом (якорь в каждом
промпте), а точное совпадение даёт только условие на первый кадр (--image PATH 0 STRENGTH).
"""
from __future__ import annotations

import base64
import hashlib
import json
import pathlib
import shutil
import struct
import subprocess
import tempfile

from .llm import LLM, LLMError
from .schema import FORMATS

ROLES = ("style", "frame", "opening")
IMAGE_EXT = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
FORMAT_RATIOS = {"16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1.0, "4:5": 4 / 5, "21:9": 21 / 9}
LLM_MAX_SIDE = 1568           # больше Claude всё равно уменьшает, а токены тратятся
LLM_MAX_BYTES = 3_500_000


class ReferenceError(ValueError):
    pass


# ---------- файлы ----------
def image_size(path: str | pathlib.Path) -> tuple[int, int] | None:
    """(ширина, высота) PNG / JPEG / WEBP без сторонних библиотек; None, если формат не распознан."""
    try:
        data = pathlib.Path(path).read_bytes()[:512 * 1024]
    except OSError:
        return None
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        w, h = struct.unpack(">II", data[16:24])
        return w, h
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        chunk = data[12:16]
        if chunk == b"VP8X" and len(data) >= 30:
            return 1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little")
        if chunk == b"VP8L" and len(data) >= 25:
            b = int.from_bytes(data[21:25], "little")
            return (b & 0x3FFF) + 1, ((b >> 14) & 0x3FFF) + 1
        if chunk == b"VP8 " and len(data) >= 30:
            w, h = struct.unpack("<HH", data[26:30])
            return w & 0x3FFF, h & 0x3FFF
        return None
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7 or marker == 0x01:
                i += 2
                continue
            seg = struct.unpack(">H", data[i + 2:i + 4])[0]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return w, h
            i += 2 + seg
    return None


def format_for_aspect(w: int, h: int) -> str:
    """Ближайший формат кадра студии для соотношения сторон картинки."""
    ratio = w / h if h else 1.0
    return min(FORMATS, key=lambda f: abs(FORMAT_RATIOS.get(f, 1.0) - ratio))


def store_reference(src: str | pathlib.Path, assets_dir: pathlib.Path, data: bytes | None = None,
                    name: str | None = None) -> pathlib.Path:
    """Кладёт картинку в assets/refs/<sha>.ext (одинаковые файлы не дублируются). Возвращает путь."""
    ext = pathlib.Path(name or str(src)).suffix.lower()
    if ext not in IMAGE_EXT:
        raise ReferenceError("reference image must be jpg, png or webp")
    if data is None:
        p = pathlib.Path(src)
        if not p.is_file():
            raise ReferenceError(f"reference image not found: {p}")
        data = p.read_bytes()
    if len(data) > 40_000_000:
        raise ReferenceError("reference image is larger than 40 MB")
    dst = assets_dir / "refs" / (hashlib.sha256(data).hexdigest()[:16] + (".jpg" if ext == ".jpeg" else ext))
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        dst.write_bytes(data)
    if image_size(dst) is None:
        dst.unlink(missing_ok=True)
        raise ReferenceError("file is not a readable jpg / png / webp image")
    return dst


def image_for_llm(path: str | pathlib.Path) -> tuple[str, str]:
    """(media_type, base64) для Claude; большие картинки уменьшаются ffmpeg до 1568 px по длинной стороне."""
    p = pathlib.Path(path)
    media = IMAGE_EXT.get(p.suffix.lower())
    if not media:
        raise ReferenceError(f"unsupported image type: {p.name}")
    size = image_size(p) or (0, 0)
    data = p.read_bytes()
    if (max(size) > LLM_MAX_SIDE or len(data) > LLM_MAX_BYTES) and shutil.which("ffmpeg"):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "ref.jpg"
            scale = f"scale='if(gt(iw,ih),min({LLM_MAX_SIDE},iw),-2)':'if(gt(iw,ih),-2,min({LLM_MAX_SIDE},ih))'"
            r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(p), "-vf", scale, "-q:v", "3", str(out)],
                               capture_output=True)
            if r.returncode == 0 and out.exists():
                data, media = out.read_bytes(), "image/jpeg"
    if len(data) > 5_000_000:
        raise ReferenceError(f"{p.name} is too large for the model even after resizing; install ffmpeg or use a smaller image")
    return media, base64.standard_b64encode(data).decode()


def parse_ref_arg(arg: str) -> dict:
    """'path' или 'path:role' из командной строки."""
    path, _, role = arg.rpartition(":") if arg.rsplit(":", 1)[-1] in ROLES else (arg, "", "style")
    return {"file": path or arg, "role": role or "style"}


def normalize_refs(refs: list[dict]) -> list[dict]:
    out, opening = [], False
    for r in refs or []:
        role = str(r.get("role") or "style").lower()
        if role not in ROLES:
            raise ReferenceError(f"unknown reference role {role!r}; use style, frame or opening")
        if role == "opening":
            if opening:
                role = "frame"           # первый кадр фильма может быть только один
            opening = True
        out.append({"file": str(r["file"]), "role": role})
    return out


# ---------- анализ ----------
ANALYZE_SYSTEM = """\
You are the director of photography of an AI film studio. The producer attached reference photos. The LTX-2.5
video model cannot copy a look from an image, so the look must be transferred as text that is pasted into every
shot prompt, and some photos will be used literally as the first frame of a shot.

Look carefully at every image and return JSON:
{
 "style": {
   "anchor": str,     // ONE literal sentence, 25-40 words, present tense: the world as the camera sees it in these
                      // references — place type, time of day, weather, light logic, palette, lens and grain/texture.
   "visual": str, "palette": str, "lens": str, "lighting": str, "camera": str, "pace": str
 },
 "images": [{"index": int, "description": str, "aspect": str}],
 "notes": [str]
}
Rules:
- Describe only what is visible. Colors by name and role ("teal shadows, amber practical highlights"), light by
  source/direction/quality/temperature, optics by feel (focal length, depth of field, grain, halation, contrast).
- If references disagree, choose the dominant shared look and say what you ignored in notes.
- images[i].description: a literal English description of that photo AS THE FIRST FRAME of a video shot, 40-80
  words: framing and angle, subject(s) and their exact positions and poses, setting, light, colors, textures.
  Never identify real people by name; describe them by visible appearance only.
- aspect: "landscape", "portrait" or "square".
- Write everything in English.
"""


def analyze_references(llm: LLM, refs: list[dict], request: str, log=print) -> dict:
    refs = normalize_refs(refs)
    if not refs:
        return {}
    images = [image_for_llm(r["file"]) for r in refs]
    listing = "\n".join(f"Image {i}: role={r['role']}" for i, r in enumerate(refs))
    user = (f"PRODUCER'S REQUEST: {request}\n\nThe images are attached in this order:\n{listing}\n"
            "Roles: style = aesthetic only; frame = will become the first frame of some shot; opening = will become the "
            "first frame of the film.")
    log(f"Изучаю референсы ({len(refs)} фото): эстетика, свет, палитра, оптика")
    res = llm.complete_json(ANALYZE_SYSTEM, user, max_tokens=6000, images=images)
    style = res.get("style") if isinstance(res, dict) else None
    if not isinstance(style, dict) or not str(style.get("anchor") or "").strip():
        raise LLMError("анализ референсов: модель не вернула style.anchor")
    descs = {int(x.get("index", -1)): str(x.get("description") or "").strip()
             for x in res.get("images") or [] if isinstance(x, dict)}
    out_refs = []
    for i, r in enumerate(refs):
        size = image_size(r["file"])
        out_refs.append({**r, "description": descs.get(i, ""), "size": list(size) if size else None})
    return {"style": {k: str(v) for k, v in style.items() if isinstance(v, (str, int, float)) and str(v).strip()},
            "references": out_refs, "notes": [str(n) for n in res.get("notes") or [] if isinstance(n, str)]}


def reference_brief(info: dict) -> str:
    """Текст для системного промпта планировщика."""
    if not info:
        return ""
    lines = ["REFERENCE LOOK (binding, taken from the producer's reference photos; it overrides genre defaults):",
             json.dumps(info.get("style", {}), ensure_ascii=False)]
    frames = [(i, r) for i, r in enumerate(info.get("references", [])) if r["role"] in ("frame", "opening")]
    if frames:
        lines.append("FRAME REFERENCES (each must become the FIRST FRAME of exactly one shot; set that shot's \"ref\" to the "
                     "reference index):")
        for i, r in frames:
            lines.append(f"- ref {i} ({'OPENING: the very first shot of the film' if r['role'] == 'opening' else 'frame'}): "
                         f"{r['description']}")
        lines.append("A shot with a ref starts exactly from that photo: its prompt's first sentence restates the photo "
                     "description literally (framing, subject, positions, light), then describes only what moves next "
                     "and the sound. Keep such shots at most 5 seconds and use transition \"cut\".")
    return "\n".join(lines)


# ---------- подгонка сцены под кадр ----------
ADAPT_SYSTEM = """\
You rewrite ONE shot of an AI film so that it starts from a given photo. The LTX-2.5 video model receives the photo
as the exact first frame and the prompt as instructions for what happens next. Return JSON:
{"prompt": str, "direction": {"start": str, "action": str, "camera": str, "end": str}, "conflict": str|null}
Rules:
- One English paragraph, 70-160 words, present tense. First sentence: a literal description of the photo as the
  opening frame (framing, subject and positions, light, colors). Then one simple achievable action that continues
  the shot's story beat from that frame, the camera behaviour, and the sound (concrete physical sources).
- Keep recurring characters' descriptors verbatim when they appear. No on-screen text, no negations, no "hiss".
- direction.start describes the photo; direction.end must lead into the next shot's start when one is given.
- If the photo clearly contradicts the film's world (different place, time or characters), still fit the shot to
  the photo and explain the contradiction in "conflict"; otherwise conflict is null.
"""


def adapt_shot_to_image(llm: LLM, plan, index: int, image: str | pathlib.Path) -> dict:
    shot = plan.shots[index]
    prev_end = (plan.shots[index - 1].direction or {}).get("end") if index > 0 else None
    next_start = (plan.shots[index + 1].direction or {}).get("start") if index + 1 < len(plan.shots) else None
    ctx = {"film": plan.title, "logline": plan.logline, "world_anchor": (plan.style or {}).get("anchor"),
           "characters": plan.characters, "shot": {"id": shot.id, "seconds": shot.seconds, "beat": shot.beat,
                                                   "current_prompt": shot.prompt, "direction": shot.direction},
           "previous_shot_end": prev_end, "next_shot_start": next_start}
    res = llm.complete_json(ADAPT_SYSTEM, json.dumps(ctx, ensure_ascii=False), max_tokens=4000,
                            images=[image_for_llm(image)])
    if not isinstance(res, dict) or not str(res.get("prompt") or "").strip():
        raise LLMError("подгонка сцены: модель не вернула prompt")
    d = res.get("direction") if isinstance(res.get("direction"), dict) else {}
    return {"prompt": str(res["prompt"]).strip(), "direction": {k: str(v) for k, v in d.items() if isinstance(v, str)},
            "conflict": res.get("conflict") if isinstance(res.get("conflict"), str) else None}
