"""API веб-интерфейса: сервер в потоке на случайном порту, реальные файлы проекта во временной папке."""
import json
import os
import pathlib
import shutil
import threading
import time
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer

import pytest

from tests.conftest import ROOT


@pytest.fixture
def server(tmp_path, monkeypatch):
    root = tmp_path
    for name in ("studio", "remote", "studio.py"):
        src = ROOT / name
        if src.is_dir():
            shutil.copytree(src, root / name, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy(src, root / name)
    (root / "plans").mkdir()
    shutil.copy(ROOT / "plans" / "storm.json", root / "plans" / "storm.json")
    (root / "films" / "demo").mkdir(parents=True)
    (root / "films" / "demo" / "film.mp4").write_bytes(bytes(range(256)) * 40)
    (root / "films" / "demo" / "report.json").write_text(json.dumps({"title": "Demo", "seconds": 10, "resolution": "704x1280",
                                                                     "shots_ok": 1, "shots_failed": [], "shots": [], "timeline": []}))
    (root / "film_config.json").write_text(json.dumps({"runpod_api_key": "", "network_volume_id": ""}))
    monkeypatch.setenv("FILM_CONFIG", str(root / "film_config.json"))
    import importlib
    import studio.config as config
    importlib.reload(config)
    monkeypatch.setattr(config, "HERE", root)
    monkeypatch.setattr(config, "CFG_PATH", root / "film_config.json")
    import studio.ui as ui
    importlib.reload(ui)
    ui.Handler.studio = ui.Studio(root)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), ui.Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", root
    httpd.shutdown()


def call(url, method="GET", body=None, headers=None, raw=False):
    data = None
    h = dict(headers or {})
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        h.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            payload = r.read()
            return r.status, (payload if raw else json.loads(payload)), dict(r.headers)
    except urllib.error.HTTPError as e:
        payload = e.read()
        return e.code, (payload if raw else json.loads(payload)), dict(e.headers)


def test_state_and_plan_detail(server):
    base, root = server
    code, st, _ = call(base + "/api/state")
    assert code == 200 and [p["name"] for p in st["plans"]] == ["storm"]
    assert st["films"][0]["slug"] == "demo" and st["config"]["has_runpod"] is False
    code, d, _ = call(base + "/api/plan/storm")
    assert code == 200 and len(d["plan"]["shots"]) == 6 and any(i["level"] == "error" for i in d["issues"])
    code, d, _ = call(base + "/api/plan/nope")
    assert code == 404


def test_save_plan_validates(server):
    base, root = server
    code, d, _ = call(base + "/api/plan/storm", "PUT", b"{not json")
    assert code == 400 and "JSON" in d["error"]
    plan = json.loads((root / "plans" / "storm.json").read_text())
    plan["shots"][0]["seconds"] = 5
    code, d, _ = call(base + "/api/plan/storm", "PUT", json.dumps(plan).encode())
    assert code == 200 and d["plan"]["shots"][0]["seconds"] == 5


def test_static_files_range_and_traversal(server):
    base, root = server
    code, body, h = call(base + "/files/films/demo/film.mp4", headers={"Range": "bytes=10-19"}, raw=True)
    assert code == 206 and body == bytes(range(10, 20)) and h["Content-Range"] == "bytes 10-19/10240"
    code, body, h = call(base + "/files/films/demo/film.mp4", raw=True)
    assert code == 200 and len(body) == 10240 and h["Accept-Ranges"] == "bytes"
    code, _, _ = call(base + "/api/poster/demo", raw=True)
    assert code in (200, 404)          # 404, если нет ffmpeg или файл не видео
    code, _, _ = call(base + "/files/films/../film_config.json", raw=True)
    assert code in (403, 404)
    code, body, _ = call(base + "/", raw=True)
    assert code == 200 and b"<title>" in body


def test_render_refused_without_runpod(server):
    base, _ = server
    code, d, _ = call(base + "/api/render", "POST", {"plan": "storm"})
    assert code == 400 and "RunPod" in d["error"]


def test_job_lifecycle_with_cli_subprocess(server):
    base, root = server
    code, job, _ = call(base + "/api/plan", "POST", {"request": ""})
    assert code == 400
    # estimate — быстрая команда CLI, проверяем весь цикл задачи через менеджер
    import studio.ui as ui
    j = ui.Handler.studio.jobs.start("estimate", "Оценка", ["estimate", str(root / "plans" / "storm.json")])
    for _ in range(100):
        code, d, _ = call(base + f"/api/jobs/{j.id}?log=4000")
        if d["status"] != "running":
            break
        time.sleep(0.2)
    assert d["status"] == "done", d
    assert "Сцен: 6" in d["log"]
    code, lst, _ = call(base + "/api/jobs")
    assert any(x["id"] == j.id for x in lst)
    code, d, _ = call(base + f"/api/jobs/{j.id}", "DELETE")
    assert d["ok"] is True


def test_prefs_and_upload(server):
    base, root = server
    code, d, _ = call(base + "/api/prefs", "PUT", {"text": "- меньше крупных планов\n"})
    assert code == 200 and (root / "studio_prefs.md").read_text() == "- меньше крупных планов\n"
    boundary = "XX"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"rain calm.mp3\"\r\n"
            f"Content-Type: audio/mpeg\r\n\r\n").encode() + b"ID3fake" + f"\r\n--{boundary}--\r\n".encode()
    code, idx, _ = call(base + "/api/assets/upload?kind=music", "POST", body,
                        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    assert code == 200 and idx["music"][0]["file"].endswith("rain_calm.mp3") and "rain" in idx["music"][0]["tags"]
    assert (root / "assets" / "music" / "rain_calm.mp3").read_bytes() == b"ID3fake"


def test_prompt_assistant_api(server, monkeypatch):
    from studio.llm import FakeLLM
    from studio.prompt_assistant import FIELDS
    result = {**{key: 'Direction' for key in FIELDS}, 'assumptions': [], 'questions': []}
    llm = FakeLLM([result, {'subject': 'broken'}])
    monkeypatch.setattr('studio.llm.make_llm', lambda cfg: llm)
    base, root = server
    code, data, _ = call(base + '/api/prompt-assistant', 'POST', {'request': 'Rain'})
    assert code == 200 and data == result
    assert not list((root / '.studio').glob('**/job*.json'))
    code, data, _ = call(base + '/api/prompt-assistant', 'POST', {'request': 'Rain'})
    assert code == 502 and 'invalid' in data['error']
    code, _, _ = call(base + '/api/prompt-assistant', 'POST', {'request': ''})
    assert code == 400
