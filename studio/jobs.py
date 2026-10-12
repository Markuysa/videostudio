"""Фоновые задачи интерфейса: планирование, рендер, пересборка.

Каждая задача — отдельный процесс CLI (`python studio.py ...`), его вывод пишется в
файл. Так интерфейс переживает перезапуск сервера: процесс рендера продолжает
работать, а лог и статус восстанавливаются из .studio/jobs/.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import signal
import subprocess
import sys
import threading
import time
import uuid

PROGRESS_RE = re.compile(r"\[(\d+)/(\d+)\] сцена")
PLAN_RE = re.compile(r"План сохранён: (.+)")
FILM_RE = re.compile(r"ФИЛЬМ СКАЧАН: (.+)")
RECUT_RE = re.compile(r"Готово: (.+?\.mp4)")
STAGES = [   # (шаблон в логе CLI, подпись для интерфейса)
    ("Pod создан", "Pod created, waiting for boot"), ("Pod на связи", "Pod is online"),
    ("Нашёл", "Reusing an existing Pod"), ("Загружаю студию", "Uploading studio and plan"),
    ("Установка/проверка", "Checking LTX installation"), ("Запускаю рендер", "Rendering shots"),
    ("Собираю фильм", "Assembling the film"), ("ФИЛЬМ СКАЧАН", "Film downloaded"), ("Планирую", "Planning"),
    ("Сюжет:", "Story ready, writing shots"), ("Раунд правок", "Prompt fixes"),
    ("Промпты прошли проверку", "Prompts checked"), ("Pod .* удалён", "Pod deleted"),
    ("Изучаю референсы", "Studying reference photos"), ("Подгоняю сцену", "Fitting the shot to the frame"),
]
TERMINAL_OK = ("ФИЛЬМ СКАЧАН", "План сохранён", "Готово:", "Библия сохранена", "Исправленный план сохранён", "Сохранено:")


class Job:
    def __init__(self, kind: str, title: str, cmd: list[str], jobs_dir: pathlib.Path, job_id: str | None = None,
                 meta: dict | None = None):
        self.id = job_id or time.strftime("%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        self.kind, self.title, self.cmd = kind, title, cmd
        self.meta = meta or {}
        self.status = "queued"           # queued | running | done | error | stopped
        self.started: float | None = None
        self.finished: float | None = None
        self.returncode: int | None = None
        self.pid: int | None = None
        self.log_path = jobs_dir / f"{self.id}.log"
        self.state_path = jobs_dir / f"{self.id}.json"
        self.proc: subprocess.Popen | None = None

    # ---------- сериализация ----------
    def to_dict(self, with_log_tail: int = 0) -> dict:
        d = {"id": self.id, "kind": self.kind, "title": self.title, "status": self.status, "started": self.started,
             "finished": self.finished, "returncode": self.returncode, "pid": self.pid, "meta": self.meta,
             "cmd": self.cmd}
        d.update(self.progress())
        if with_log_tail:
            d["log"] = self.log_tail(with_log_tail)
        return d

    def save(self) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.state_path)

    @staticmethod
    def load(path: pathlib.Path) -> "Job":
        d = json.loads(path.read_text(encoding="utf-8"))
        j = Job(d["kind"], d["title"], d["cmd"], path.parent, job_id=d["id"], meta=d.get("meta") or {})
        j.status, j.started, j.finished = d["status"], d.get("started"), d.get("finished")
        j.returncode, j.pid = d.get("returncode"), d.get("pid")
        return j

    # ---------- жизненный цикл ----------
    def start(self) -> None:
        self.started = time.time()
        self.status = "running"
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        logf = open(self.log_path, "ab", buffering=0)
        self.proc = subprocess.Popen(self.cmd, stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     env=env, start_new_session=True, cwd=str(self.log_path.parent.parent.parent))
        self.pid = self.proc.pid
        self.save()

    def poll(self) -> None:
        if self.status != "running":
            return
        code = None
        if self.proc is not None:
            code = self.proc.poll()
            if code is None:
                return
        elif self.pid and _alive(self.pid):
            return
        else:
            code = 0 if any(m in self.log_tail(4000) for m in TERMINAL_OK) else 1
        self.returncode = code
        self.finished = time.time()
        self.status = "done" if code == 0 else "error"
        self.save()

    def stop(self) -> None:
        if self.status != "running":
            return
        if self.pid:
            try:
                os.killpg(self.pid, signal.SIGINT)      # KeyboardInterrupt: рендер успеет скачать лог и удалить Pod
            except ProcessLookupError:
                pass
        self.status = "stopped"
        self.finished = time.time()
        self.save()

    # ---------- данные для UI ----------
    def log_tail(self, max_bytes: int = 12000) -> str:
        if not self.log_path.exists():
            return ""
        with open(self.log_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            data = f.read()
        return data.decode("utf-8", errors="replace")

    def progress(self) -> dict:
        tail = self.log_tail(20000)
        out: dict = {"stage": "", "shot": None, "shots": None, "result": None}
        m = None
        for m in PROGRESS_RE.finditer(tail):
            pass
        if m:
            out["shot"], out["shots"] = int(m.group(1)), int(m.group(2))
        for pat, label in STAGES:
            if re.search(pat, tail):
                out["stage"] = label
        for rx in (FILM_RE, PLAN_RE, RECUT_RE):
            mm = None
            for mm in rx.finditer(tail):
                pass
            if mm:
                out["result"] = mm.group(1).strip()
        err = re.findall(r"(?:ОШИБКА|Проблема): (.+)", tail)
        if err:
            out["error"] = err[-1][:300]
        return out


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


class JobManager:
    def __init__(self, root: pathlib.Path):
        self.root = root
        self.dir = root / ".studio" / "jobs"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()
        for p in sorted(self.dir.glob("*.json")):
            try:
                j = Job.load(p)
            except (json.JSONDecodeError, KeyError):
                continue
            if j.status == "running" and not (j.pid and _alive(j.pid)):
                j.poll()
            self.jobs[j.id] = j

    def studio_cmd(self, *args: str) -> list[str]:
        return [sys.executable, "-u", str(self.root / "studio.py"), *args]

    def start(self, kind: str, title: str, args: list[str], meta: dict | None = None) -> Job:
        job = Job(kind, title, self.studio_cmd(*args), self.dir, meta=meta)
        with self.lock:
            self.jobs[job.id] = job
            job.start()
        return job

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def list(self) -> list[dict]:
        with self.lock:
            for j in self.jobs.values():
                j.poll()
            return [j.to_dict() for j in sorted(self.jobs.values(), key=lambda j: j.started or 0, reverse=True)]

    def active(self) -> list[Job]:
        return [j for j in self.jobs.values() if j.status == "running"]

    def remove_finished(self) -> int:
        """Удаляет все завершённые задачи (done / error / stopped) вместе с логами."""
        ids = [j.id for j in self.jobs.values() if j.status != "running"]
        for jid in ids:
            self.remove(jid)
        return len(ids)

    def remove(self, job_id: str) -> bool:
        with self.lock:
            j = self.jobs.pop(job_id, None)
        if not j:
            return False
        if j.status == "running":
            j.stop()
        for p in (j.log_path, j.state_path):
            p.unlink(missing_ok=True)
        return True
