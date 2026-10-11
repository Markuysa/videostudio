"""Локальный веб-интерфейс студии: python studio.py ui

Сервер на стандартной библиотеке (без зависимостей): отдаёт страницу из studio/web,
JSON-API поверх тех же команд CLI (задачи — отдельные процессы, см. jobs.py) и файлы
фильмов/клипов с поддержкой Range (перемотка в <video>).
"""
from __future__ import annotations

import email
import email.policy
import json
import mimetypes
import os
import pathlib
import re
import shutil
import threading
import time
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .audio import index_assets, load_index
from .config import load_config, path_in_root
from .jobs import JobManager
from .lint import lint_plan
from .schema import FORMATS, KINDS, Plan, PlanError, load_plan, validate

WEB = pathlib.Path(__file__).resolve().parent / "web"
SAFE_NAME = re.compile(r"^[A-Za-z0-9_\-]{1,90}$")


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class Studio:
    """Состояние приложения: конфиг, задачи, доступ к папкам."""

    def __init__(self, root: pathlib.Path | None = None):
        self.cfg = load_config()
        self.root = pathlib.Path(root or self.cfg["_root"])
        self.jobs = JobManager(self.root)
        self.lock = threading.Lock()

    # ---------- папки ----------
    def dir(self, key: str) -> pathlib.Path:
        return path_in_root(self.cfg, key)

    def plan_path(self, name: str) -> pathlib.Path:
        if not SAFE_NAME.match(name):
            raise ApiError("invalid plan name")
        p = self.dir("plans_dir") / f"{name}.json"
        if not p.exists():
            raise ApiError(f"no plan {name}", 404)
        return p

    # ---------- обзор ----------
    def plans(self) -> list[dict]:
        out = []
        films = {f["slug"] for f in self.films()}
        for p in sorted(self.dir("plans_dir").glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                plan = load_plan(p)
            except (PlanError, OSError):
                out.append({"name": p.stem, "title": p.stem, "broken": True, "modified": p.stat().st_mtime})
                continue
            out.append({"name": p.stem, "title": plan.title, "kind": plan.kind, "format": plan.format,
                        "quality": plan.quality or self.cfg.get("quality", "fast"), "shots": len(plan.shots),
                        "seconds": plan.total_seconds, "logline": plan.logline, "series": plan.series,
                        "modified": p.stat().st_mtime, "has_film": plan.slug in films or p.stem in films,
                        "captions": plan.captions.enabled, "music": bool(plan.music and plan.music.file)})
        return out

    def films(self) -> list[dict]:
        out = []
        films_dir = self.dir("films_dir")
        if not films_dir.exists():
            return out
        for d in sorted(films_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if d.is_dir() and (d / "film.mp4").exists():
                rep = _read_json(d / "report.json") or {}
                recuts = sorted((x.name for x in d.glob("film_recut_*.mp4")), reverse=True)
                out.append({"slug": d.name, "title": rep.get("title", d.name), "file": f"films/{d.name}/film.mp4",
                            "seconds": rep.get("seconds"), "resolution": rep.get("resolution"), "quality": rep.get("quality"),
                            "shots_ok": rep.get("shots_ok"), "shots_failed": rep.get("shots_failed") or [],
                            "shots": rep.get("shots") or [], "timeline": rep.get("timeline") or [],
                            "music": rep.get("music"), "captions": rep.get("captions"), "minutes": rep.get("minutes"),
                            "modified": (d / "film.mp4").stat().st_mtime, "size": (d / "film.mp4").stat().st_size,
                            "has_clips": (d / "clips").is_dir(), "has_manifest": (d / "manifest.json").exists(),
                            "recuts": [f"films/{d.name}/{r}" for r in recuts]})
            elif d.is_file() and d.suffix == ".mp4" and not d.stem.startswith("film_recut"):
                rep = _read_json(films_dir / f"{d.stem}_report.json") or {}   # старая раскладка films/<name>.mp4
                out.append({"slug": d.stem + "__legacy", "title": d.stem + " (legacy layout)", "file": f"films/{d.name}", "legacy": True,
                            "resolution": rep.get("resolution"), "quality": rep.get("quality"),
                            "shots_ok": rep.get("shots_ok"), "shots_failed": rep.get("shots_failed") or [], "shots": [],
                            "timeline": [], "modified": d.stat().st_mtime, "size": d.stat().st_size, "has_clips": False,
                            "has_manifest": False, "recuts": []})
        return out

    def series(self) -> list[dict]:
        root = self.dir("series_dir")
        out = []
        if root.exists():
            for p in sorted(root.glob("*/bible.json")):
                b = _read_json(p) or {}
                out.append({"slug": p.parent.name, "title": b.get("title", p.parent.name), "premise": b.get("premise"),
                            "episodes": len(b.get("episodes") or []), "characters": len(b.get("characters") or []),
                            "planned": len(b.get("season_arc") or [])})
        return out

    def config_summary(self) -> dict:
        llm = self.cfg.get("llm", {})
        has_key = bool(os.environ.get("ANTHROPIC_API_KEY") or self.cfg.get("anthropic_api_key"))
        provider = llm.get("provider", "auto")
        effective = provider if provider != "auto" else ("anthropic" if has_key else "ollama")
        return {"quality": self.cfg.get("quality", "fast"), "llm_provider": provider, "llm_effective": effective,
                "llm_model": llm.get("model") or ("claude-opus-5-5" if effective == "anthropic" else llm.get("ollama_model")),
                "has_anthropic": has_key, "has_runpod": bool(self.cfg.get("runpod_api_key") and self.cfg.get("network_volume_id")),
                "has_elevenlabs": bool(self.cfg.get("elevenlabs_api_key")), "gpu_price": self.cfg.get("gpu_price_per_hour", 2.5),
                "gpu_types": self.cfg.get("gpu_types"), "max_hours": self.cfg.get("max_hours"), "ffmpeg": bool(shutil.which("ffmpeg")),
                "config_path": str(self.root / "film_config.json"), "kinds": list(KINDS), "formats": list(FORMATS)}

    def state(self) -> dict:
        prefs = self.dir("prefs_file")
        return {"plans": self.plans(), "films": self.films(), "series": self.series(), "jobs": self.jobs.list(),
                "library": load_index(self.dir("assets_dir")), "config": self.config_summary(),
                "prefs": prefs.read_text(encoding="utf-8") if prefs.exists() else "", "now": time.time()}

    # ---------- планы ----------
    def plan_detail(self, name: str) -> dict:
        p = self.plan_path(name)
        raw = p.read_text(encoding="utf-8")
        try:
            plan = load_plan(p)
        except PlanError as e:
            return {"name": name, "raw": raw, "error": str(e), "issues": [], "problems": [str(e)]}
        from .planner import plan_summary
        q = plan.quality or self.cfg.get("quality", "fast")
        issues = [{"shot": i.shot_id, "level": i.level, "code": i.code, "message": i.message} for i in lint_plan(plan, q)]
        return {"name": name, "plan": plan.to_dict(), "raw": raw, "summary": plan_summary(plan, self.cfg),
                "issues": issues, "problems": validate(plan, q), "path": str(p)}

    def save_plan(self, name: str, raw: str) -> dict:
        p = self.plan_path(name)
        try:
            data = json.loads(raw)
            Plan.from_dict(data, source_path=str(p))
        except json.JSONDecodeError as e:
            raise ApiError(f"invalid JSON: {e}")
        except PlanError as e:
            raise ApiError(str(e))
        p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        return self.plan_detail(name)

    # ---------- задачи ----------
    def start_plan(self, body: dict) -> dict:
        req = str(body.get("request", "")).strip()
        if not req:
            raise ApiError("describe what we are shooting")
        args = ["make" if body.get("render") else "plan", req]
        kind = body.get("kind") or "film"
        if kind not in KINDS:
            raise ApiError("unknown type")
        args += ["--kind", kind]
        if body.get("duration"):
            args += ["--duration", str(int(body["duration"]))]
        if body.get("format"):
            args += ["--format", str(body["format"])]
        if body.get("quality"):
            args += ["--quality", str(body["quality"])]
        if body.get("language"):
            args += ["--language", str(body["language"])]
        name = str(body.get("name") or "").strip()
        if name:
            if not SAFE_NAME.match(name):
                raise ApiError("name: latin letters, digits, _ and -")
            args += ["--name", name]
        if body.get("series"):
            args += ["--series", str(body["series"])]
        if body.get("music") and body["music"] != "auto":
            args += ["--music", str(body["music"])]
        if body.get("captions") is True:
            args.append("--captions")
        elif body.get("captions") is False:
            args.append("--no-captions")
        if body.get("notes"):
            args += ["--notes", str(body["notes"])]
        if body.get("loop"):
            args.append("--loop")
        if body.get("audio") in ("raw", "leveled"):
            args += ["--audio", str(body["audio"])]
        title = ("Film: " if body.get("render") else "Plan: ") + req[:60]
        return self.jobs.start("make" if body.get("render") else "plan", title, args, meta={"request": req}).to_dict()

    def start_render(self, name: str) -> dict:
        p = self.plan_path(name)
        plan = load_plan(p)
        problems = validate(plan, plan.quality or self.cfg.get("quality", "fast"))
        if problems:
            raise ApiError("plan cannot be rendered: " + "; ".join(problems))
        if not self.config_summary()["has_runpod"]:
            raise ApiError("RunPod is not configured (runpod_api_key, network_volume_id in film_config.json)")
        return self.jobs.start("render", f"Render: {plan.title}", ["render", str(p)], meta={"plan": name}).to_dict()

    def start_review(self, name: str) -> dict:
        p = self.plan_path(name)
        return self.jobs.start("review", f"Prompt fixes: {name}", ["review", str(p), "--fix"], meta={"plan": name}).to_dict()

    def start_assemble(self, body: dict) -> dict:
        slug = str(body.get("film", ""))
        if not SAFE_NAME.match(slug):
            raise ApiError("invalid film name")
        d = self.dir("films_dir") / slug
        if not (d / "manifest.json").exists():
            raise ApiError("this film has no manifest.json and clips — re-assembly is impossible")
        if not shutil.which("ffmpeg"):
            raise ApiError("ffmpeg is not installed on this computer (brew install ffmpeg)")
        args = ["assemble", str(d)]
        if body.get("music"):
            args += ["--music", str(body["music"])]
        if body.get("music_volume") not in (None, ""):
            args += ["--music-volume", str(float(body["music_volume"]))]
        if body.get("captions"):
            args.append("--captions")
        if body.get("audio") in ("raw", "leveled"):
            args += ["--audio", str(body["audio"])]
        return self.jobs.start("assemble", f"Re-assembly: {slug}", args, meta={"film": slug}).to_dict()

    def start_series(self, body: dict) -> dict:
        desc = str(body.get("description", "")).strip()
        if not desc:
            raise ApiError("describe the series")
        args = ["series", "new", desc, "--episodes", str(int(body.get("episodes") or 6)),
                "--language", str(body.get("language") or "ru")]
        if body.get("name"):
            if not SAFE_NAME.match(str(body["name"])):
                raise ApiError("slug: latin letters, digits, _ and -")
            args += ["--name", str(body["name"])]
        return self.jobs.start("series", "Series bible: " + desc[:50], args).to_dict()

    # ---------- прочее ----------
    def bible(self, slug: str) -> dict:
        if not SAFE_NAME.match(slug):
            raise ApiError("invalid slug")
        p = self.dir("series_dir") / slug / "bible.json"
        if not p.exists():
            raise ApiError("no such series", 404)
        return _read_json(p) or {}

    def add_note(self, slug: str, text: str) -> dict:
        b = self.bible(slug)
        b.setdefault("notes", []).append(text.strip())
        (self.dir("series_dir") / slug / "bible.json").write_text(json.dumps(b, ensure_ascii=False, indent=1), encoding="utf-8")
        return b

    def save_prefs(self, text: str) -> str:
        p = self.dir("prefs_file")
        p.write_text(text, encoding="utf-8")
        return text

    def upload_asset(self, kind: str, filename: str, data: bytes) -> dict:
        if kind not in ("music", "sfx"):
            raise ApiError("kind: music | sfx")
        name = re.sub(r"[^A-Za-z0-9._\-]+", "_", pathlib.Path(filename).name)
        if pathlib.Path(name).suffix.lower() not in (".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".aiff", ".aif"):
            raise ApiError("audio file: mp3, wav, m4a, flac, ogg, aac")
        dest = self.dir("assets_dir") / kind / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return index_assets(self.dir("assets_dir"))

    def delete_plan(self, name: str) -> None:
        p = self.plan_path(name)
        p.unlink()
        assets = p.parent / f"{name}_assets"
        if assets.is_dir():
            shutil.rmtree(assets)

    def delete_film(self, slug: str) -> None:
        if not SAFE_NAME.match(slug):
            raise ApiError("invalid name")
        if slug.endswith("__legacy"):
            stem = slug[: -len("__legacy")]
            for name in (f"{stem}.mp4", f"{stem}_report.json", f"{stem}_render.log"):
                (self.dir("films_dir") / name).unlink(missing_ok=True)
            return
        d = self.dir("films_dir") / slug
        if d.is_dir():
            shutil.rmtree(d)

    def poster(self, slug: str) -> pathlib.Path | None:
        """Кадр-превью фильма (films/<slug>/poster.jpg), создаётся ffmpeg по требованию."""
        if not SAFE_NAME.match(slug) or not shutil.which("ffmpeg"):
            return None
        films = self.dir("films_dir")
        if slug.endswith("__legacy"):
            video, poster = films / (slug[: -len("__legacy")] + ".mp4"), films / (slug[: -len("__legacy")] + "_poster.jpg")
        else:
            video, poster = films / slug / "film.mp4", films / slug / "poster.jpg"
        if not video.exists():
            return None
        if not poster.exists() or poster.stat().st_mtime < video.stat().st_mtime:
            import subprocess
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1", "-i", str(video), "-frames:v", "1",
                            "-vf", "scale=-2:640", "-q:v", "4", str(poster)], capture_output=True, timeout=60)
        return poster if poster.exists() else None

    def doctor(self) -> list[str]:
        import io
        import contextlib
        from .cli import cmd_doctor
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cmd_doctor(None, self.cfg)
        return buf.getvalue().strip().splitlines()


def _read_json(p: pathlib.Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# ---------- HTTP ----------
class Handler(BaseHTTPRequestHandler):
    studio: Studio = None  # type: ignore[assignment]
    protocol_version = "HTTP/1.1"

    def handle(self):
        try:
            super().handle()
        except (ConnectionResetError, BrokenPipeError, TimeoutError):
            pass   # браузер оборвал соединение (обычное дело для <video preload=metadata>)

    def log_message(self, fmt, *args):  # тише: не засоряем консоль каждым запросом
        if os.environ.get("STUDIO_UI_DEBUG"):
            super().log_message(fmt, *args)

    # ----- утилиты -----
    def _json(self, data, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not getattr(self, "_head_only", False):
            self.wfile.write(body)

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _json_body(self) -> dict:
        raw = self._body()
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            raise ApiError("request body must be JSON")

    def _file(self, path: pathlib.Path) -> None:
        if not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        size = path.stat().st_size
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        start, end = 0, size - 1
        rng = self.headers.get("Range")
        status = 200
        if rng and rng.startswith("bytes="):
            m = re.match(r"bytes=(\d*)-(\d*)", rng)
            if m:
                if m.group(1):
                    start = int(m.group(1))
                    if m.group(2):
                        end = min(int(m.group(2)), size - 1)
                elif m.group(2):
                    start = max(0, size - int(m.group(2)))
                if start > end or start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                status = 206
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        if path.suffix in (".html", ".js", ".css"):
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if getattr(self, "_head_only", False):
            return
        with open(path, "rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(1 << 20, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                left -= len(chunk)

    def _safe_under(self, base: pathlib.Path, rel: str) -> pathlib.Path:
        target = (base / urllib.parse.unquote(rel)).resolve()
        if base.resolve() not in target.parents and target != base.resolve():
            raise ApiError("access denied", 403)
        return target

    # ----- маршруты -----
    def do_GET(self):
        try:
            self._route("GET")
        except ApiError as e:
            self._json({"error": str(e)}, e.status)

    def do_POST(self):
        try:
            self._route(self.command)
        except ApiError as e:
            self._json({"error": str(e)}, e.status)
        except (PlanError, OSError, ValueError) as e:
            self._json({"error": str(e)}, 400)

    def do_HEAD(self):
        """Заголовки файла без тела (некоторые плееры спрашивают размер и Accept-Ranges через HEAD)."""
        self._head_only = True
        try:
            self._route("GET")
        except ApiError as e:
            self.send_response(e.status)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def do_PUT(self):
        self.do_POST()

    def do_DELETE(self):
        self.do_POST()

    def _route(self, method: str) -> None:
        s = self.studio
        url = urllib.parse.urlparse(self.path)
        path = url.path
        q = urllib.parse.parse_qs(url.query)
        parts = [p for p in path.split("/") if p]

        if method == "GET" and not path.startswith(("/api/", "/files/")):
            # собранный React-интерфейс (ui/ -> studio/web): файл, если есть, иначе index.html (SPA)
            target = self._safe_under(WEB, path.lstrip("/")) if path not in ("/", "") else WEB / "index.html"
            if target.is_file():
                return self._file(target)
            if "." not in path.rsplit("/", 1)[-1]:
                return self._file(WEB / "index.html")
            raise ApiError("not found", 404)
        if method == "GET":
            if path == "/api/state":
                return self._json(s.state())
            if path == "/api/jobs":
                return self._json(s.jobs.list())
            if len(parts) == 3 and parts[:2] == ["api", "jobs"]:
                job = s.jobs.get(parts[2])
                if not job:
                    raise ApiError("no such job", 404)
                job.poll()
                return self._json(job.to_dict(with_log_tail=int(q.get("log", ["12000"])[0])))
            if len(parts) == 3 and parts[:2] == ["api", "plan"]:
                return self._json(s.plan_detail(parts[2]))
            if len(parts) == 3 and parts[:2] == ["api", "series"]:
                return self._json(s.bible(parts[2]))
            if path == "/api/prefs":
                p = s.dir("prefs_file")
                return self._json({"text": p.read_text(encoding="utf-8") if p.exists() else ""})
            if path == "/api/doctor":
                return self._json({"lines": s.doctor()})
            if len(parts) == 3 and parts[:2] == ["api", "poster"]:
                poster = s.poster(parts[2])
                if not poster:
                    raise ApiError("no poster", 404)
                return self._file(poster)
            if parts[:1] == ["files"] and len(parts) >= 3 and parts[1] in ("films", "assets"):
                base = s.dir("films_dir") if parts[1] == "films" else s.dir("assets_dir")
                return self._file(self._safe_under(base, "/".join(parts[2:])))
            raise ApiError("not found", 404)

        if method == "DELETE":
            if len(parts) == 3 and parts[:2] == ["api", "jobs"]:
                return self._json({"ok": s.jobs.remove(parts[2])})
            if len(parts) == 3 and parts[:2] == ["api", "plan"]:
                s.delete_plan(parts[2])
                return self._json({"ok": True})
            if len(parts) == 3 and parts[:2] == ["api", "film"]:
                s.delete_film(parts[2])
                return self._json({"ok": True})
            raise ApiError("not found", 404)

        if method == "PUT":
            if len(parts) == 3 and parts[:2] == ["api", "plan"]:
                return self._json(s.save_plan(parts[2], self._body().decode("utf-8")))
            if path == "/api/prefs":
                return self._json({"text": s.save_prefs(self._json_body().get("text", ""))})
            raise ApiError("not found", 404)

        # POST
        if path == "/api/plan":
            return self._json(s.start_plan(self._json_body()))
        if path == "/api/render":
            return self._json(s.start_render(str(self._json_body().get("plan", ""))))
        if path == "/api/review":
            return self._json(s.start_review(str(self._json_body().get("plan", ""))))
        if path == "/api/assemble":
            return self._json(s.start_assemble(self._json_body()))
        if path == "/api/series":
            return self._json(s.start_series(self._json_body()))
        if path == "/api/series/note":
            b = self._json_body()
            return self._json(s.add_note(str(b.get("name", "")), str(b.get("text", ""))))
        if len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] == "stop":
            job = s.jobs.get(parts[2])
            if not job:
                raise ApiError("no such job", 404)
            job.stop()
            return self._json(job.to_dict())
        if path == "/api/assets/reindex":
            return self._json(index_assets(s.dir("assets_dir")))
        if path == "/api/assets/upload":
            kind = q.get("kind", ["music"])[0]
            ctype = self.headers.get("Content-Type", "")
            if not ctype.startswith("multipart/form-data"):
                raise ApiError("multipart/form-data expected")
            msg = email.message_from_bytes(b"Content-Type: " + ctype.encode() + b"\r\nMIME-Version: 1.0\r\n\r\n" + self._body(),
                                           policy=email.policy.HTTP)
            index = None
            for part in msg.iter_parts():
                fn = part.get_filename()
                if fn:
                    index = s.upload_asset(kind, fn, part.get_payload(decode=True) or b"")
            if index is None:
                raise ApiError("no file in the request")
            return self._json(index)
        raise ApiError("not found", 404)


def serve(port: int = 8765, open_browser: bool = True, root: pathlib.Path | None = None) -> None:
    Handler.studio = Studio(root)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    url = f"http://127.0.0.1:{port}/"
    print(f"Studio is open: {url}  (Ctrl+C stops the server; running renders keep going)", flush=True)
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        httpd.server_close()
