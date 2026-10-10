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
    assert [c["pipeline"] for c in chain] == ["distilled", "dfr", "distilled"]
    chain = film.attempts_for(True, "start.png", (704, 1280), frames=121)
    assert [c["pipeline"] for c in chain] == ["dfr", "distilled", "dfr", "distilled"]
    assert [c["pipeline"] for c in film.attempts_for(False, None, (704, 1280), 193)] == ["distilled"]
