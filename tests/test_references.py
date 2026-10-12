"""Фото-референсы: файлы, анализ эстетики, назначение первых кадров, подгонка сцены под кадр."""
import pathlib
import struct
import zlib

import pytest

from studio.llm import FakeLLM, LLMError, OllamaLLM
from studio.planner import Planner, PlanRequest
from studio.references import (ReferenceError, adapt_shot_to_image, analyze_references, format_for_aspect, image_for_llm,
                               image_size, normalize_refs, parse_ref_arg, reference_brief, store_reference)
from studio.schema import Plan, Shot, frames_for
from tests.test_lint import GOOD


def make_png(path: pathlib.Path, w: int, h: int) -> pathlib.Path:
    raw = b"".join(b"\x00" + bytes([40, 80, 120]) * w for _ in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)  # noqa: E731
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return path


def test_size_format_and_args(tmp_path):
    assert image_size(make_png(tmp_path / "v.png", 90, 160)) == (90, 160)
    assert format_for_aspect(90, 160) == "9:16" and format_for_aspect(1920, 1080) == "16:9" and format_for_aspect(800, 1000) == "4:5"
    assert parse_ref_arg("x/a.jpg") == {"file": "x/a.jpg", "role": "style"}
    assert parse_ref_arg("x/a.jpg:opening") == {"file": "x/a.jpg", "role": "opening"}
    assert [r["role"] for r in normalize_refs([{"file": "a", "role": "opening"}, {"file": "b", "role": "opening"}])] == ["opening", "frame"]
    with pytest.raises(ReferenceError):
        normalize_refs([{"file": "a", "role": "mood"}])


def test_store_reference_dedupes_and_rejects_garbage(tmp_path):
    src = make_png(tmp_path / "a.png", 32, 18)
    one = store_reference(src, tmp_path / "assets")
    two = store_reference(src, tmp_path / "assets")
    assert one == two and one.parent.name == "refs" and one.suffix == ".png"
    bad = tmp_path / "x.jpg"
    bad.write_bytes(b"not an image")
    with pytest.raises(ReferenceError):
        store_reference(bad, tmp_path / "assets")
    with pytest.raises(ReferenceError):
        store_reference(tmp_path / "a.gif", tmp_path / "assets", data=b"x", name="a.gif")


def test_image_for_llm_small_png_passthrough(tmp_path):
    media, data = image_for_llm(make_png(tmp_path / "a.png", 64, 36))
    assert media == "image/png" and len(data) > 20


ANALYSIS = {"style": {"anchor": "A misty pine forest at dawn, low sun through haze, pale teal and amber, 35mm lens with soft grain.",
                      "visual": "photoreal misty forest", "palette": "teal, amber", "lens": "35mm", "lighting": "low sun", "camera": "slow"},
            "images": [{"index": 0, "description": "Wide shot of a misty forest path with a red fox standing in the centre.", "aspect": "portrait"},
                       {"index": 1, "description": "Close-up of dew on a fern leaf in amber light.", "aspect": "portrait"}],
            "notes": ["image 2 is warmer; kept the cool dominant look"]}


def test_analyze_references_sends_images(tmp_path):
    refs = [{"file": str(make_png(tmp_path / "a.png", 90, 160)), "role": "opening"},
            {"file": str(make_png(tmp_path / "b.png", 90, 160)), "role": "style"}]
    llm = FakeLLM(responses=[ANALYSIS])
    info = analyze_references(llm, refs, "a fox in the forest", log=lambda *_: None)
    assert len(llm.images[0]) == 2 and llm.images[0][0][0] == "image/png"
    assert info["style"]["anchor"].startswith("A misty pine forest")
    assert info["references"][0]["description"].startswith("Wide shot") and info["references"][0]["size"] == [90, 160]
    brief = reference_brief(info)
    assert "REFERENCE LOOK" in brief and "ref 0 (OPENING" in brief and "ref 1" not in brief   # style-фото не кадр


def test_planner_assigns_frames_style_and_format(tmp_path):
    opening = str(make_png(tmp_path / "a.png", 90, 160))
    frame = str(make_png(tmp_path / "b.png", 90, 160))
    outline = {"title": "Fox", "style": {"visual": "anime", "palette": "pink"},
               "acts": [{"name": "A", "seconds": 16, "beats": ["fox", "fern"]}]}
    shots = {"shots": [{"beat": "fox", "seconds": 8, "transition": "cut", "prompt": GOOD, "ref": None},
                       {"beat": "fern", "seconds": 8, "transition": "continue", "prompt": GOOD, "ref": 1}]}
    analysis = dict(ANALYSIS, images=ANALYSIS["images"])
    llm = FakeLLM(responses=[analysis, outline, shots, {"shots": [], "notes": []}])
    req = PlanRequest(request="fox", kind="aesthetic", seconds=16, quality="high",
                      refs=[{"file": opening, "role": "opening"}, {"file": frame, "role": "frame"}])
    plan = Planner(llm, log=lambda *_: None).plan(req)
    assert plan.format == "9:16"                                     # формат взят из первого кадра
    assert plan.shots[0].image == opening                            # opening закреплён, хотя модель не поставила ref
    assert plan.shots[1].image == frame and plan.shots[1].transition == "cut"
    assert all(frames_for(s.seconds) <= 121 for s in plan.shots)     # сцены с кадром в high ≤ 5 с
    assert plan.style["anchor"].startswith("A misty pine forest") and plan.style["palette"] == "teal, amber"
    assert {r["role"]: r["shot"] for r in plan.references} == {"opening": "001", "frame": "002"}
    assert "REFERENCE LOOK" in llm.calls[1][0]                       # эстетика попала в системный промпт
    assert all("A misty pine forest" in s.prompt for s in plan.shots)  # и якорем в каждую сцену
    restored = Plan.from_dict(plan.to_dict())
    assert restored.references == plan.references and restored.shots[1].image == frame


def test_adapt_shot_to_image(tmp_path):
    img = make_png(tmp_path / "a.png", 160, 90)
    plan = Plan(title="t", style={"anchor": "x"}, shots=[Shot("001", 5, GOOD, direction={"end": "e1"}), Shot("002", 5, GOOD, direction={"start": "s2"})])
    llm = FakeLLM(responses=[{"prompt": "Wide shot of the photo. Then the fox runs. Sound: leaves.", "direction": {"start": "photo", "end": "fox gone"},
                              "conflict": None}])
    res = adapt_shot_to_image(llm, plan, 0, img)
    assert res["prompt"].startswith("Wide shot of the photo") and res["direction"]["end"] == "fox gone" and res["conflict"] is None
    assert len(llm.images[0]) == 1 and '"next_shot_start": "s2"' in llm.calls[0][1]


def test_local_model_refuses_images():
    with pytest.raises(LLMError):
        OllamaLLM().complete_json("s", "u", images=[("image/png", "AAAA")])
