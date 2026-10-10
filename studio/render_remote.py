"""Рендер на RunPod: поднять GPU-Pod, загрузить студию и план, дождаться, скачать фильм, удалить Pod.

Перенесено из make_film.py и расширено: на Pod уезжает весь пакет studio/ и remote/,
план с папкой ассетов (музыка, sfx, озвучка), обратно приезжают film.mp4,
report.json, manifest.json, render.log и нормализованные клипы (для пересборки
без GPU командой `studio assemble`).
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

from .config import HERE, path_in_root
from .schema import Plan, load_plan, validate

API = os.environ.get("RUNPOD_REST", "https://rest.runpod.io/v1")
FAKE_SSH = os.environ.get("FAKE_SSH")  # только для проверки без RunPod
IMAGE = "runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404"
POD_PREFIX = "ltx-film-"
HIGH_GPUS = ["NVIDIA RTX PRO 6000 Blackwell Server Edition", "NVIDIA RTX PRO 6000 Blackwell Workstation Edition",
             "NVIDIA H100 80GB HBM3", "NVIDIA H100 PCIe", "NVIDIA H100 NVL", "NVIDIA A100 80GB PCIe",
             "NVIDIA A100-SXM4-80GB", "NVIDIA H200"]
FALLBACK_GPUS = ["NVIDIA GeForce RTX 5090", "NVIDIA RTX PRO 6000 Blackwell Server Edition",
                 "NVIDIA RTX PRO 6000 Blackwell Workstation Edition", "NVIDIA L40S", "NVIDIA RTX 6000 Ada Generation",
                 "NVIDIA L40", "NVIDIA A100 80GB PCIe", "NVIDIA A100-SXM4-80GB"]
KEY = pathlib.Path.home() / ".ssh" / "ltx_film_ed25519"
POLL = float(os.environ.get("FILM_POLL", "60"))
REMOTE_STUDIO = "/workspace/studio"


class RenderError(RuntimeError):
    pass


def log(msg: str) -> None:
    print(time.strftime("[%H:%M:%S] ") + msg, flush=True)


# ---------- RunPod API ----------
class RunPod:
    def __init__(self, key: str):
        self.key = key

    def call(self, method: str, path: str, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(API + path, data=data, method=method, headers={
            "Authorization": f"Bearer {self.key}", "Content-Type": "application/json",
            "Accept": "application/json", "User-Agent": "curl/8.7.1"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                txt = r.read().decode()
                return r.status, (json.loads(txt) if txt.strip() else None)
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(errors="replace")
        except urllib.error.URLError as e:
            return 599, str(e)

    def try_create(self, body: dict):
        return self.call("POST", "/pods", body)

    def create(self, body: dict) -> dict:
        code, res = self.call("POST", "/pods", body)
        if code not in (200, 201):
            if "1010" in str(res) or code == 401:
                raise RenderError(f"RunPod отклонил запрос ({code}): {res}\nПроверьте runpod_api_key в film_config.json "
                                  "(ключ с правами Read/Write).")
            raise RenderError(f"RunPod не создал Pod ({code}): {res}\nЧастые причины: нет свободных карт выбранного типа "
                              "в дата-центре тома, мало денег на балансе, неверный network_volume_id.")
        return res

    def get(self, pod_id: str):
        code, res = self.call("GET", f"/pods/{pod_id}")
        return res if code == 200 else None

    def delete(self, pod_id: str) -> bool:
        code, _ = self.call("DELETE", f"/pods/{pod_id}")
        return code in (200, 202, 204, 404)

    def list(self):
        code, res = self.call("GET", "/pods")
        return res if code == 200 and isinstance(res, list) else []


# ---------- SSH ----------
class Remote:
    def __init__(self, host: str, port: int):
        self.host, self.port = host, port
        self.opts = ["-i", str(KEY), "-o", "StrictHostKeyChecking=no", "-o", f"UserKnownHostsFile={os.devnull}",
                     "-o", "LogLevel=ERROR", "-o", "ServerAliveInterval=30", "-o", "ConnectTimeout=20"]

    def run(self, cmd: str, check=False, capture=True) -> subprocess.CompletedProcess:
        args = ["bash", "-c", cmd] if FAKE_SSH else ["ssh", *self.opts, "-p", str(self.port), f"root@{self.host}", cmd]
        r = subprocess.run(args, capture_output=capture, text=True)
        if check and r.returncode != 0:
            raise RenderError(f"Команда на сервере не выполнилась: {cmd}\n{r.stderr or r.stdout}")
        return r

    def put(self, local: pathlib.Path, remote: str) -> None:
        if FAKE_SSH:
            if local.is_dir():
                shutil.copytree(local, remote, dirs_exist_ok=True)
            else:
                pathlib.Path(remote).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(local, remote)
            return
        args = ["scp", *self.opts, "-r", "-P", str(self.port), str(local), f"root@{self.host}:{remote}"]
        if subprocess.run(args).returncode != 0:
            raise RenderError(f"Не удалось загрузить {local.name} на сервер")

    def get(self, remote: str, local: pathlib.Path, recursive: bool = False) -> bool:
        local.parent.mkdir(parents=True, exist_ok=True)
        if FAKE_SSH:
            src = pathlib.Path(remote)
            if not src.exists():
                return False
            if src.is_dir():
                shutil.copytree(src, local, dirs_exist_ok=True)
            else:
                shutil.copy(src, local)
            return True
        args = ["scp", *self.opts, *(["-r"] if recursive else []), "-P", str(self.port),
                f"root@{self.host}:{remote}", str(local)]
        return subprocess.run(args, capture_output=True).returncode == 0


def ensure_key() -> str:
    if not FAKE_SSH:
        missing = [t for t in ("ssh", "scp", "ssh-keygen") if not shutil.which(t)]
        if missing:
            raise RenderError("Не найдены программы: " + ", ".join(missing))
    if not KEY.exists():
        KEY.parent.mkdir(parents=True, exist_ok=True)
        log("Создаю SSH-ключ для доступа к Pod (один раз)")
        subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-q", "-f", str(KEY)], check=True)
    return KEY.with_suffix(".pub").read_text().strip()


def is_high(cfg: dict) -> bool:
    return str(cfg.get("quality", "fast")).lower() == "high"


def gpu_lists(cfg: dict) -> tuple[list, list]:
    """(ваши карты, запасные) с учётом режима качества."""
    if is_high(cfg):
        mine = cfg.get("gpu_types_high") or HIGH_GPUS
        return mine, [g for g in HIGH_GPUS if g not in mine]
    mine = cfg.get("gpu_types") or ["NVIDIA GeForce RTX 5090"]
    return mine, [g for g in FALLBACK_GPUS if g not in mine]


def start_pod(rp: RunPod, cfg: dict, name: str, cpu=False) -> tuple[str, Remote]:
    pub = ensure_key()
    body = {"name": POD_PREFIX + name, "imageName": IMAGE, "networkVolumeId": cfg["network_volume_id"],
            "containerDiskInGb": 50, "volumeMountPath": "/workspace",
            "ports": ["8888/http", "22/tcp", "7860/http"], "env": {"PUBLIC_KEY": pub}}
    if cpu:
        body.update({"computeType": "CPU", "cpuFlavorIds": ["cpu3c", "cpu3g", "cpu5c"], "vcpuCount": 2})
        pod = rp.create(body)
    else:
        body.update({"gpuTypeIds": gpu_lists(cfg)[0], "gpuCount": 1,
                     "cloudType": cfg.get("cloud_type", "SECURE"), "allowedCudaVersions": ["13.0"]})
        if cfg.get("hf_token"):
            body["env"]["HF_TOKEN"] = cfg["hf_token"]
        pod = None
        wait_min = int(cfg.get("wait_for_gpu_minutes", 60))
        deadline = time.time() + wait_min * 60
        round_no = 0
        while pod is None:
            round_no += 1
            user_gpus, extra = gpu_lists(cfg)
            attempts = [("ваши карты, CUDA 13", user_gpus, "SECURE", True),
                        ("ваши карты, любая CUDA", user_gpus, "SECURE", False),
                        ("расширенный список карт", user_gpus + extra, "SECURE", False),
                        ("Community Cloud", user_gpus + extra, "COMMUNITY", False)]
            for label, gpus, cloud, cuda in attempts:
                b = dict(body, gpuTypeIds=gpus, cloudType=cloud)
                if cuda:
                    b["allowedCudaVersions"] = ["13.0"]
                else:
                    b.pop("allowedCudaVersions", None)
                if cloud == "COMMUNITY":
                    b["supportPublicIp"] = True
                code, res = rp.try_create(b)
                if code in (200, 201):
                    pod = res
                    break
                if code < 500:
                    raise RenderError(f"RunPod не создал Pod ({code}): {res}")
                log(f"  нет свободных карт ({label})")
            if pod is not None:
                break
            if time.time() > deadline and is_high(cfg) and cfg.get("fallback_to_fast", True):
                log(f"За {wait_min} мин карт на 80-96 ГБ не нашлось. Переключаюсь на обычное качество (RTX 5090 и т.п.)")
                cfg["quality"] = "fast"
                body["gpuTypeIds"] = gpu_lists(cfg)[0]
                deadline = time.time() + wait_min * 60
                continue
            if time.time() > deadline:
                raise RenderError(f"За {wait_min} мин не освободилась ни одна подходящая карта в дата-центре тома. "
                                  "Попробуйте позже или создайте том в другом дата-центре.")
            log(f"Все карты заняты, жду 5 минут и пробую снова (попытка {round_no}, ждём до {wait_min} мин)")
            time.sleep(300 if not FAKE_SSH else 1)
    pod_id = pod["id"]
    gpu = (pod.get("machine") or {}).get("gpuTypeId") or pod.get("gpuTypeId") or ("CPU" if cpu else "GPU")
    price = pod.get("costPerHr") or pod.get("adjustedCostPerHr")
    log(f"Pod создан: {pod_id} ({gpu}{f', ${price}/ч' if price else ''}). Жду запуска...")
    remote = wait_ssh(rp, pod_id, 900)
    if remote is None:
        rp.delete(pod_id)
        raise RenderError("Pod не поднялся за 15 минут, удалил его. Попробуйте позже или другой тип карты.")
    return pod_id, remote


def wait_ssh(rp: RunPod, pod_id: str, timeout: int):
    t0 = time.time()
    while time.time() - t0 < timeout:
        info = rp.get(pod_id) or {}
        ip, ports = info.get("publicIp"), info.get("portMappings") or {}
        if ip and str(ports.get("22") or ports.get(22) or "").isdigit():
            remote = Remote(ip, int(ports.get("22") or ports.get(22)))
            if remote.run("echo ok").returncode == 0:
                log(f"Pod на связи ({ip}:{remote.port}) через {time.time() - t0:.0f} с")
                return remote
        time.sleep(10)
    return None


def find_existing(rp: RunPod, cfg: dict):
    """Ищем уже созданный GPU-Pod с нашим томом: работающий или остановленный."""
    if not cfg.get("reuse_existing", True):
        return None
    ensure_key()
    code, pods = rp.call("GET", f"/pods?networkVolumeId={cfg['network_volume_id']}&computeType=GPU&includeMachine=true")
    if code != 200 or not isinstance(pods, list):
        return None
    ok_gpus = set(sum(gpu_lists(cfg), []))
    cands = []
    for p in pods:
        gpu = (p.get("machine") or {}).get("gpuTypeId") or (p.get("gpu") or {}).get("id") or ""
        if p.get("desiredStatus") not in ("RUNNING", "EXITED"):
            continue
        if gpu and gpu not in ok_gpus:
            log(f"  Pod {p['id']} ({gpu}) не подходит для режима {'high' if is_high(cfg) else 'fast'}, не беру")
            continue
        cands.append(p)
    cands.sort(key=lambda p: p.get("desiredStatus") != "RUNNING")
    for p in cands:
        pid, gpu = p["id"], (p.get("machine") or {}).get("gpuTypeId") or "GPU"
        if p.get("desiredStatus") == "EXITED":
            log(f"Нашёл остановленный Pod {pid} ({gpu}) с вашим томом, запускаю его")
            code, res = rp.call("POST", f"/pods/{pid}/start")
            if code not in (200, 201, 202, 204):
                log(f"  не запустился ({code}): {str(res)[:150]}")
                continue
        else:
            log(f"Нашёл работающий Pod {pid} ({gpu}) с вашим томом, использую его")
        remote = wait_ssh(rp, pid, 300)
        if remote:
            return pid, remote
        log(f"  нет SSH-доступа к {pid}. Добавьте ключ {KEY.with_suffix('.pub')} в RunPod -> Settings -> SSH Public Keys")
        if p.get("desiredStatus") == "EXITED":
            rp.call("POST", f"/pods/{pid}/stop")
    return None


# ---------- загрузка / скачивание ----------
def upload_studio(remote: Remote, plan_path: pathlib.Path) -> str:
    """Копирует пакет studio/, remote/, план и его ассеты. Возвращает путь плана на Pod."""
    remote.run(f"mkdir -p {REMOTE_STUDIO} /workspace/film/plans", check=True)
    remote.put(HERE / "studio", f"{REMOTE_STUDIO}/studio")
    remote.put(HERE / "remote", f"{REMOTE_STUDIO}/remote")
    remote.put(plan_path, f"/workspace/film/plans/{plan_path.name}")
    assets = plan_path.parent / f"{plan_path.stem}_assets"
    if assets.is_dir():
        remote.put(assets, f"/workspace/film/plans/{assets.name}")
    # очищаем кэш байткода, чтобы Pod не подхватил старые .pyc
    remote.run(f"find {REMOTE_STUDIO} -name __pycache__ -type d -exec rm -rf {{}} + 2>/dev/null; true")
    return f"/workspace/film/plans/{plan_path.name}"


def download(remote: Remote, slug: str, films_dir: pathlib.Path, with_clips: bool = True) -> pathlib.Path | None:
    out_dir = films_dir / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    ok = remote.get(f"/workspace/film/{slug}/film.mp4", out_dir / "film.mp4")
    for name in ("report.json", "manifest.json", "render.log", "timeline.json"):
        remote.get(f"/workspace/film/{slug}/{name}", out_dir / name)
    if ok and with_clips:
        if remote.get(f"/workspace/film/{slug}/norm", out_dir / "clips", recursive=True):
            log(f"Клипы скачаны в {out_dir / 'clips'} (для пересборки без GPU: studio assemble {out_dir})")
    if ok:
        log(f"ФИЛЬМ СКАЧАН: {out_dir / 'film.mp4'}")
        return out_dir / "film.mp4"
    return None


def plan_assets_dir(plan_path: pathlib.Path) -> pathlib.Path:
    return plan_path.parent / f"{plan_path.stem}_assets"


def collect_plan_assets(plan: Plan, plan_path: pathlib.Path, root: pathlib.Path, log_fn=log) -> None:
    """Копирует музыку и sfx, на которые ссылается план, в <plan>_assets/, чтобы они уехали на Pod."""
    assets = plan_assets_dir(plan_path)
    files = []
    if plan.music and plan.music.file:
        files.append(plan.music.file)
    for s in plan.shots:
        files += [x.file for x in s.sfx]
    for f in files:
        src = pathlib.Path(f) if pathlib.Path(f).is_absolute() else root / f
        if not src.exists():
            log_fn(f"ВНИМАНИЕ: аудиофайл {f} не найден, на Pod он не попадёт")
            continue
        dst = assets / f if not pathlib.Path(f).is_absolute() else assets / src.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
            shutil.copy(src, dst)


# ---------- основной сценарий ----------
def render(plan_path: pathlib.Path, cfg: dict, keep: bool = False, with_clips: bool = True) -> pathlib.Path | None:
    plan = load_plan(plan_path)
    problems = validate(plan, cfg.get("quality", "fast"))
    if problems:
        raise RenderError("План нельзя рендерить: " + "; ".join(problems))
    installer = HERE / "remote" / "ltx_studio.sh"
    if not installer.exists():
        raise RenderError("Нет remote/ltx_studio.sh")
    if plan.quality:
        cfg["quality"] = plan.quality
    root = pathlib.Path(cfg["_root"])
    collect_plan_assets(plan, plan_path, root)
    try:
        from .audio import prepare_narration
        prepare_narration(plan, cfg, plan_assets_dir(plan_path))
    except Exception as e:  # noqa: BLE001 — озвучка не должна срывать рендер
        log(f"Озвучка пропущена: {e}")
    slug = plan.slug
    log(f"Качество: {'high — DFR, 1080p, карта 80-96 ГБ' if is_high(cfg) else 'fast — RTX 5090, 720p'}")
    log(f"План «{plan.title}»: {len(plan.shots)} сцен, ~{plan.total_seconds / 60:.1f} мин видео")
    rp = RunPod(cfg["runpod_api_key"])
    found = find_existing(rp, cfg)
    pod_id, remote = found if found else start_pod(rp, cfg, slug)
    films_dir = path_in_root(cfg, "films_dir")
    result = None
    try:
        log("Загружаю студию и план")
        remote.run(f"rm -f /workspace/film/{slug}/report.json", check=False)
        remote_plan = upload_studio(remote, plan_path)
        log("Установка/проверка студии (первый раз 20-40 минут, потом ~1 минута)")
        hf = f"HF_TOKEN={shlex.quote(cfg['hf_token'])} " if cfg.get("hf_token") else ""
        remote.run(f"{hf}nohup bash {REMOTE_STUDIO}/remote/ltx_studio.sh < /dev/null > /workspace/install.log 2>&1 & "
                   f"echo $! > /workspace/install.pid", check=True)
        last, t_inst = "", time.time()
        while True:
            time.sleep(POLL / 3)
            tail = remote.run("tail -n 3 /workspace/install.log").stdout.strip()
            line = tail.splitlines()[-1] if tail else ""
            if line and line != last:
                log("  установка: " + re.sub(r"\x1b\[[0-9;]*m", "", line)[:150])
                last = line
            if "Готово!" in tail or "установка пропустится" in tail:
                break
            running = remote.run("kill -0 $(cat /workspace/install.pid) 2>/dev/null").returncode == 0
            if "ОШИБКА" in tail or "не запустился" in tail or not running or time.time() - t_inst > 5400:
                print(remote.run("tail -n 30 /workspace/install.log").stdout)
                raise RenderError("установка не удалась или зависла (лог выше)")
        env = (f"MAX_HOURS={int(cfg.get('max_hours', 10))} SHUTDOWN_DELAY=1800 "
               f"FILM_QUALITY={'high' if is_high(cfg) else 'fast'}")
        if cfg.get("ntfy_topic"):
            env += f" NTFY_TOPIC={shlex.quote(cfg['ntfy_topic'])}"
        log("Запускаю рендер фильма. Можно оставить компьютер включённым и идти спать.")
        r = remote.run(f"{env} bash {REMOTE_STUDIO}/remote/film_night.sh {remote_plan}", check=True)
        night_log = (re.findall(r"tail -f (\S+)", r.stdout) or [""])[0]
        last, t_run = "", time.time()
        while True:
            time.sleep(POLL)
            if rp.get(pod_id) is None:
                raise RenderError("Pod пропал (удалён по лимиту времени или вручную). Готовое лежит на томе: studio fetch")
            if time.time() - t_run > (int(cfg.get("max_hours", 10)) + 1) * 3600:
                raise RenderError("рендер идёт дольше лимита")
            if remote.run(f"test -f /workspace/film/{slug}/report.json").returncode == 0:
                break
            if night_log:
                tail = remote.run(f"tail -n 1 {night_log}").stdout.strip()
                if tail and tail != last:
                    log("  " + tail[:160])
                    last = tail
                if any(m in tail for m in ("завершился с ошибкой", "Превышен лимит", "не установлена",
                                           "Ни одной сцены", "Сборка не удалась", "будет остановлен")):
                    if remote.run(f"test -f /workspace/film/{slug}/report.json").returncode != 0:
                        raise RenderError("рендер остановился: " + tail)
        time.sleep(5)
        result = download(remote, slug, films_dir, with_clips)
        if not result:
            raise RenderError("не удалось скачать фильм")
        rep = json.loads((films_dir / slug / "report.json").read_text(encoding="utf-8"))
        log(f"Качество фильма: {rep.get('quality', '?')}, {rep.get('resolution', '?')}, {rep.get('seconds', '?')} с")
        used = {d.get("pipeline") for d in rep.get("shots", [])}
        if "distilled" in used and is_high(cfg):
            log("Внимание: часть сцен отрендерена быстрым пайплайном (откат после ошибки DFR), см. report.json")
        if rep.get("shots_failed"):
            log(f"Внимание: не получились сцены {', '.join(rep['shots_failed'])} (фильм собран без них)")
    except KeyboardInterrupt:
        log("Остановлено вами.")
        remote.get(f"/workspace/film/{slug}/render.log", films_dir / slug / "render.log")
    except RenderError as e:
        log(f"Проблема: {e}. Лог скачан в папку films/ (если был).")
        remote.get(f"/workspace/film/{slug}/render.log", films_dir / slug / "render.log")
    finally:
        if keep:
            log(f"Pod {pod_id} оставлен (--keep-pod). Не забудьте удалить его в RunPod!")
        elif rp.delete(pod_id):
            log(f"Pod {pod_id} удалён, деньги больше не списываются. Модели и клипы остались на томе.")
        else:
            log(f"НЕ УДАЛОСЬ удалить Pod {pod_id}. Удалите вручную в RunPod или: studio cleanup")
    return result


def fetch(slug: str, cfg: dict) -> None:
    rp = RunPod(cfg["runpod_api_key"])
    log("Поднимаю дешёвый CPU-Pod, чтобы забрать фильм с тома")
    pod_id, remote = start_pod(rp, cfg, "fetch-" + slug, cpu=True)
    try:
        if not download(remote, slug, path_in_root(cfg, "films_dir")):
            log(f"Фильма /workspace/film/{slug}/film.mp4 на томе нет")
    finally:
        rp.delete(pod_id)
        log(f"CPU-Pod {pod_id} удалён")


def cleanup(cfg: dict) -> None:
    rp = RunPod(cfg["runpod_api_key"])
    pods = [p for p in rp.list() if str(p.get("name", "")).startswith(POD_PREFIX)]
    if not pods:
        log("Pod'ов от этого скрипта нет")
    for p in pods:
        log(f"Удаляю {p['id']} ({p.get('name')}): {'ok' if rp.delete(p['id']) else 'ошибка'}")
