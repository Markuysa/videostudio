"""Полный прогон pod-стороны (remote/film.py) с имитацией LTX."""
import json
import os
import pathlib
import subprocess
import sys

from tests.conftest import ROOT, needs_ffmpeg


@needs_ffmpeg
def test_film_py_end_to_end_with_fallback(tmp_path):
    for p in pathlib.Path("/tmp").glob("fake_ltx_failed_*"):
        p.unlink()
    plan = {"title": "Тест", "format": "9:16", "quality": "high", "seed": 1, "shots": [
        {"id": "001", "seconds": 4, "prompt": "p" * 40},
        {"id": "002", "seconds": 4, "prompt": "p" * 40, "transition": "continue"},
        {"id": "003", "seconds": 3, "prompt": "p" * 40, "transition": "dissolve", "transition_seconds": 0.5, "caption": "Конец"},
    ]}
    plan_path = tmp_path / "test.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    env = dict(os.environ, LTX_TEST_CMD=f"bash {ROOT / 'tests' / 'fake_ltx.sh'}", FILM_QUALITY="high",
               FILM_DIR=str(tmp_path / "proj"), FILM_RETRIES="1", FAKE_LTX_FAIL_ONCE="shot_002")
    r = subprocess.run([sys.executable, str(ROOT / "remote" / "film.py"), str(plan_path)], env=env,
                       capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout + r.stderr
    report = json.loads((tmp_path / "proj" / "report.json").read_text(encoding="utf-8"))
    assert report["shots_ok"] == 3 and report["shots_failed"] == []
    by_id = {s["id"]: s for s in report["shots"]}
    assert by_id["001"]["pipeline"] == "dfr"
    assert by_id["002"]["pipeline"] == "distilled" and by_id["002"]["continuity"] is True   # откат сохранил непрерывность
    assert (tmp_path / "proj" / "film.mp4").exists()
    assert [t["transition"] for t in report["timeline"]] == ["cut", "continue", "dissolve"]
    # повторный запуск берёт клипы из кэша
    r2 = subprocess.run([sys.executable, str(ROOT / "remote" / "film.py"), str(plan_path)], env=env,
                        capture_output=True, text=True, timeout=600)
    assert r2.returncode == 0 and "уже готова" in r2.stdout


def test_attempts_chain_skips_dfr_for_long_conditioned_shots():
    import importlib.util
    spec = importlib.util.spec_from_file_location("film", ROOT / "remote" / "film.py")
    film = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(film)
    chain = film.attempts_for(True, "start.png", (704, 1280), frames=193)
    assert [c["pipeline"] for c in chain] == ["distilled", "distilled"]
    assert all(c["image"] == "start.png" and not c.get("no_cond") for c in chain)
    chain = film.attempts_for(True, "start.png", (704, 1280), frames=121)
    assert [c["pipeline"] for c in chain] == ["dfr", "distilled", "distilled"]
    assert [c["pipeline"] for c in film.attempts_for(True, None, (704, 1280), 121, extra_conditioned=True)] == ["distilled", "distilled"]
    assert [c["pipeline"] for c in film.attempts_for(False, None, (704, 1280), 193)] == ["distilled"]


@needs_ffmpeg
def test_film_py_loop_closes_on_first_frame(tmp_path):
    for p in pathlib.Path("/tmp").glob("fake_ltx_failed_*"):
        p.unlink()
    plan = {"title": "Луп", "format": "9:16", "quality": "high", "seed": 1, "loop": True, "shots": [
        {"id": "001", "seconds": 4, "prompt": "p" * 40},
        {"id": "002", "seconds": 4, "prompt": "p" * 40},
        {"id": "003", "seconds": 8, "prompt": "p" * 40},      # в high + условие -> обрежется до 121 кадра
    ]}
    plan_path = tmp_path / "loop.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    env = dict(os.environ, LTX_TEST_CMD=f"bash {ROOT / 'tests' / 'fake_ltx.sh'}", FILM_QUALITY="high",
               FILM_DIR=str(tmp_path / "proj"), FILM_RETRIES="1")
    r = subprocess.run([sys.executable, str(ROOT / "remote" / "film.py"), str(plan_path)], env=env,
                       capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "замыкаю луп" in r.stdout and "обрезаю" in r.stdout
    report = json.loads((tmp_path / "proj" / "report.json").read_text(encoding="utf-8"))
    assert report["loop"] is True and report["loop_closed"] is True
    last = report["shots"][-1]
    assert last["loop_closed"] is True and last["pipeline"] == "distilled"
    # последний кадр лупа отрезан: 4.04 + 4.04 + (5.04 - 1/24)
    assert abs(report["seconds"] - (4.042 + 4.042 + 5.042 - 1 / 24)) < 0.06
    log = (tmp_path / "proj" / "render.log").read_text(encoding="utf-8")
    last_cmd = [l for l in log.splitlines() if l.startswith("$") and "fake_ltx" in l and "shot_003" in l][-1]
    assert last_cmd.count("--image") == 1 and "_loop_end.png 120 1.0" in last_cmd   # только финальный кадр, стартового нет


@needs_ffmpeg
def test_film_py_user_first_frame(tmp_path):
    from tests.test_references import make_png
    for p in pathlib.Path("/tmp").glob("fake_ltx_failed_*"):
        p.unlink()
    make_png(tmp_path / "opening.png", 90, 160)
    plan = {"title": "Ref", "format": "9:16", "quality": "high", "seed": 3, "shots": [
        {"id": "001", "seconds": 5, "prompt": "p" * 40, "image": "opening.png", "image_strength": 0.8},
        {"id": "002", "seconds": 4, "prompt": "p" * 40},
    ]}
    plan_path = tmp_path / "ref.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    env = dict(os.environ, LTX_TEST_CMD=f"bash {ROOT / 'tests' / 'fake_ltx.sh'}", FILM_QUALITY="high",
               FILM_DIR=str(tmp_path / "proj"), FILM_RETRIES="1")
    r = subprocess.run([sys.executable, str(ROOT / "remote" / "film.py"), str(plan_path)], env=env,
                       capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout + r.stderr
    log = (tmp_path / "proj" / "render.log").read_text(encoding="utf-8")
    cmd1 = [l for l in log.splitlines() if l.startswith("$") and "fake_ltx" in l and "shot_001" in l][-1]
    cmd2 = [l for l in log.splitlines() if l.startswith("$") and "fake_ltx" in l and "shot_002" in l][-1]
    assert f"--image {tmp_path / 'opening.png'} 0 0.8" in cmd1 and "--pipeline dfr" in cmd1   # 121 кадр с кадром -> DFR
    assert "--image" not in cmd2
    report = json.loads((tmp_path / "proj" / "report.json").read_text(encoding="utf-8"))
    assert report["shots_ok"] == 2 and report["shots_failed"] == []


@needs_ffmpeg
def test_loop_last_with_own_first_frame_skips_end_condition(tmp_path):
    from tests.test_references import make_png
    for p in pathlib.Path("/tmp").glob("fake_ltx_failed_*"):
        p.unlink()
    make_png(tmp_path / "a.png", 90, 160)
    plan = {"title": "L", "format": "9:16", "quality": "high", "seed": 5, "loop": True, "shots": [
        {"id": "001", "seconds": 4, "prompt": "p" * 40, "image": "a.png"},
        {"id": "002", "seconds": 4, "prompt": "p" * 40, "image": "a.png"}]}
    plan_path = tmp_path / "l.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    env = dict(os.environ, LTX_TEST_CMD=f"bash {ROOT / 'tests' / 'fake_ltx.sh'}", FILM_QUALITY="high",
               FILM_DIR=str(tmp_path / "proj"), FILM_RETRIES="1")
    r = subprocess.run([sys.executable, str(ROOT / "remote" / "film.py"), str(plan_path)], env=env, capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "луп закроется склейкой" in r.stdout
    log = (tmp_path / "proj" / "render.log").read_text(encoding="utf-8")
    cmd2 = [l for l in log.splitlines() if l.startswith("$") and "fake_ltx" in l and "shot_002" in l][-1]
    assert cmd2.count("--image") == 1 and "_loop_end" not in cmd2 and "--pipeline dfr" in cmd2
