#!/bin/bash
# LTX-2.5 студия: установка и запуск на RunPod. Запуск: bash /workspace/studio/remote/ltx_studio.sh
set -e
# Подтягиваем переменные окружения Pod (в SSH-сессии RunPod их нет)
while IFS= read -r -d '' kv; do k=${kv%%=*}; [[ "$k" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] && [ -z "${!k+x}" ] && export "$kv"; done 2>/dev/null < /proc/1/environ || true
export UV_PYTHON_INSTALL_DIR=/workspace/uv-python UV_CACHE_DIR=/workspace/uv-cache HF_HOME=/workspace/hf-home
export HF_HUB_ENABLE_HF_TRANSFER=1
UI=/workspace/ltx-ui; REPO=/workspace/LTX-2; MODELS=/workspace/models/ltx-2.5
say(){ echo -e "\n\033[1;36m==> $*\033[0m"; }
fail(){ echo -e "\n\033[1;31mОШИБКА: $*\033[0m"; exit 1; }

say "1/7 Проверка сервера"
CUDA=$(nvidia-smi | grep -oP "CUDA Version: \K[0-9]+" || echo 0)
GPU=$(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)
VRAM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1)
FREE=$(df -BG --output=avail /workspace | tail -1 | tr -dc 0-9)
echo "GPU: $GPU, VRAM: ${VRAM} MiB, драйвер CUDA: $CUDA, свободно на /workspace: ${FREE} ГБ"
[ "$CUDA" -ge 13 ] || fail "драйвер этого сервера поддерживает только CUDA $CUDA, а LTX-2.5 нужна CUDA 13.
Удалите Pod (Terminate) и создайте новый: в Deploy -> Additional filters -> CUDA Versions выберите 13.x."
[ "${FREE:-0}" -ge 90 ] || echo "ВНИМАНИЕ: на /workspace меньше 90 ГБ свободно, моделям нужно ~70 ГБ."

say "2/7 Останавливаю старые интерфейсы (Wan2GP и прошлый запуск студии)"
pkill -f wgp.py || true; pkill -f "uvicorn app:app" || true

say "2b/7 ffmpeg и шрифты для субтитров"
which ffmpeg >/dev/null && fc-list 2>/dev/null | grep -qi dejavu || { apt-get update -qq && apt-get install -y -qq ffmpeg fonts-dejavu-core >/dev/null 2>&1 || true; }

say "3/7 Устанавливаю uv"
export PATH="$HOME/.local/bin:$PATH"
command -v uv >/dev/null || pip install -q -U uv 2>/dev/null || pip install -q -U uv --break-system-packages 2>/dev/null \
  || curl -LsSf https://astral.sh/uv/install.sh | sh
command -v uv >/dev/null || fail "не удалось установить uv"
mkdir -p "$UI" "$HF_HOME" /workspace/film/takes

say "4/7 Официальный код LTX-2 (первый раз ~10 минут)"
[ -d "$REPO/.git" ] || git clone https://github.com/Lightricks/LTX-2.git "$REPO"
if [ ! -f "$REPO/.venv/.ltx_ok" ]; then
  (cd "$REPO" && uv sync --all-packages --no-dev)
  "$REPO/.venv/bin/python" -c "import torch, ltx_pipelines.distilled; assert torch.cuda.is_available(), 'CUDA недоступна'; print('torch', torch.__version__, 'OK')" \
    || fail "LTX-2 установился, но не видит видеокарту. Пришлите вывод выше."
  touch "$REPO/.venv/.ltx_ok"
fi

say "5/7 Окружение для веб-интерфейса"
if [ ! -x "$UI/venv/bin/hf" ]; then
  [ -x "$UI/venv/bin/python" ] || uv venv --python 3.11 "$UI/venv"
  uv pip install --python "$UI/venv/bin/python" fastapi uvicorn python-multipart "huggingface_hub[cli]" hf_transfer
fi

say "6/7 Модель LTX-2.5 (~70 ГБ, первый раз 10-30 минут; уже скачанное пропускается)"
if [ -z "$HF_TOKEN" ] && [ ! -s "$HF_HOME/token" ]; then
  read -r -s -p "Вставьте токен Hugging Face (символы не отображаются) и нажмите Enter: " HF_TOKEN || true; echo
fi
if [ -n "$HF_TOKEN" ]; then (umask 077; printf "%s" "$HF_TOKEN" > "$HF_HOME/token"); fi
"$UI/venv/bin/hf" download Lightricks/LTX-2.5 \
  diffusion_models/ltx-2.5-22b-distilled-transformer-bf16.safetensors \
  text_encoders/gemma4-12b-with-proj-ltx-2.5-bf16.safetensors \
  vae/ltx-2.5-video-vae-conv-bf16.safetensors \
  vae/ltx-2.5-audio-vae-bf16.safetensors \
  latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors \
  vae/ltx-2.5-video-vae-bf16.safetensors \
  --local-dir "$MODELS" \
  || fail "не удалось скачать модель. Проверьте, что на huggingface.co/Lightricks/LTX-2.5 вы приняли лицензию, а токен типа Read.
Чтобы ввести токен заново: rm $HF_HOME/token и снова bash /workspace/ltx_studio.sh"

say "Модели для качества как в API (LoRA детализации)"
"$UI/venv/bin/hf" download Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler \
  ltx-2.5-22b-ic-lora-pixel-spatial-upscaler-x2-1.0.safetensors --local-dir "$MODELS/loras" \
  || echo "ВНИМАНИЕ: LoRA детализации не скачалась. Примите лицензию на huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-Pixel-Spatial-Upscaler, иначе режим high недоступен."
if [ ! -f "$REPO/.venv/.natten_tried" ]; then
  say "Ускоритель диффузионного декодера (natten), необязательно"
  (cd "$REPO" && uv sync --all-packages --no-dev --extra natten) && echo "natten установлен" \
    || echo "natten не установился: режим high будет работать, но медленнее"
  touch "$REPO/.venv/.natten_tried"
fi

say "7/7 Запуск веб-интерфейса на порту 7860"
EXTRA=""
[ "$VRAM" -lt 70000 ] && EXTRA="--quantization fp8-cast --offload cpu"
echo "Режим памяти для $GPU: ${EXTRA:-без ограничений}"
cat > "$UI/env" <<ENV
export LTX_EXTRA_ARGS="$EXTRA"
export HF_HOME=$HF_HOME UV_PYTHON_INSTALL_DIR=$UV_PYTHON_INSTALL_DIR
ENV
cat > "$UI/app.py" <<'APP_EOF'
"""Простой веб-интерфейс для LTX-2.5: промпт -> видео.
Каждый клип генерируется официальным CLI `python -m ltx_pipelines.distilled`.
"""
import json
import os
import pathlib
import queue
import random
import shlex
import subprocess
import threading
import time
import uuid

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

ROOT = pathlib.Path(os.environ.get("LTX_UI_ROOT", "/workspace/ltx-ui"))
OUT = pathlib.Path(os.environ.get("LTX_OUT", "/workspace/film/takes"))
REPO = os.environ.get("LTX_REPO", "/workspace/LTX-2")
LTX_PY = os.environ.get("LTX_PY", f"{REPO}/.venv/bin/python")
MODELS = os.environ.get("LTX_MODELS", "/workspace/models/ltx-2.5")
EXTRA = shlex.split(os.environ.get("LTX_EXTRA_ARGS", ""))
TEST_CMD = os.environ.get("LTX_TEST_CMD")  # только для проверки без GPU

UPLOADS = ROOT / "uploads"
LOGS = ROOT / "logs"
JOBS_FILE = ROOT / "jobs.json"
for d in (OUT, UPLOADS, LOGS):
    d.mkdir(parents=True, exist_ok=True)

SIZES = {"16:9": (1280, 704), "9:16": (704, 1280), "1:1": (960, 960)}
FRAMES = {"5": 121, "8": 193, "10": 241, "15": 361, "20": 481}  # 24 fps, 8n+1 кадров
LONG_ARGS = ["--chunk-pixel-frames", "97", "--chunk-carry-frames", "25"]  # длинные клипы окнами

jobs: list[dict] = json.loads(JOBS_FILE.read_text()) if JOBS_FILE.exists() else []
for j in jobs:  # после перезапуска незавершённые задачи считаем прерванными
    if j["status"] in ("queued", "running"):
        j["status"] = "error"
        j["error"] = "прервано перезапуском"
lock = threading.Lock()
work: "queue.Queue[str]" = queue.Queue()


def save_jobs() -> None:
    tmp = JOBS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(jobs, ensure_ascii=False, indent=1))
    tmp.replace(JOBS_FILE)


def find(job_id: str) -> dict:
    for j in jobs:
        if j["id"] == job_id:
            return j
    raise HTTPException(404, "нет такой задачи")


def build_cmd(j: dict) -> list[str]:
    w, h = SIZES[j["format"]]
    out = str(OUT / j["file"])
    if TEST_CMD:
        return shlex.split(TEST_CMD) + [out]
    cmd = [
        LTX_PY, "-m", "ltx_pipelines.distilled",
        "--transformer-path", f"{MODELS}/diffusion_models/ltx-2.5-22b-distilled-transformer-bf16.safetensors",
        "--text-encoder-path", f"{MODELS}/text_encoders/gemma4-12b-with-proj-ltx-2.5-bf16.safetensors",
        "--video-vae-path", f"{MODELS}/vae/ltx-2.5-video-vae-conv-bf16.safetensors",
        "--audio-vae-path", f"{MODELS}/vae/ltx-2.5-audio-vae-bf16.safetensors",
        "--spatial-upsampler-path",
        f"{MODELS}/latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors",
        "--width", str(w), "--height", str(h),
        "--num-frames", str(FRAMES[j["seconds"]]),
        "--seed", str(j["seed"]),
        "--output-path", out,
        "--prompt", j["prompt"],
    ]
    if j.get("image"):
        cmd += ["--image", j["image"], "0", "1.0"]  # картинка = первый кадр
    if FRAMES[j["seconds"]] > 241:
        cmd += LONG_ARGS
    return cmd + EXTRA


def worker() -> None:
    while True:
        job_id = work.get()
        with lock:
            j = find(job_id)
            j["status"], j["started"] = "running", time.time()
            save_jobs()
        log_path = LOGS / f"{job_id}.log"
        try:
            with open(log_path, "w") as log:
                code = subprocess.call(build_cmd(j), stdout=log, stderr=subprocess.STDOUT,
                                       cwd=REPO if os.path.isdir(REPO) else None)
            ok = code == 0 and (OUT / j["file"]).exists()
            err = None if ok else f"код выхода {code}, см. лог"
        except Exception as e:  # noqa: BLE001
            ok, err = False, str(e)
        with lock:
            j["status"] = "done" if ok else "error"
            j["error"] = err
            j["took"] = round(time.time() - j["started"])
            save_jobs()


threading.Thread(target=worker, daemon=True).start()

app = FastAPI()
app.mount("/videos", StaticFiles(directory=OUT), name="videos")


def enqueue(prompt: str, fmt: str, seconds: str, seed: int, image: str | None) -> dict:
    if fmt not in SIZES or seconds not in FRAMES:
        raise HTTPException(400, "неверный формат или длительность")
    if not prompt.strip():
        raise HTTPException(400, "пустой промпт")
    job_id = time.strftime("%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    j = {"id": job_id, "prompt": prompt.strip(), "format": fmt, "seconds": seconds,
         "seed": seed, "image": image, "file": f"{job_id}.mp4", "status": "queued",
         "created": time.time(), "error": None}
    with lock:
        jobs.append(j)
        save_jobs()
    work.put(job_id)
    return j


@app.post("/api/generate")
async def generate(prompt: str = Form(...), fmt: str = Form("16:9"), seconds: str = Form("5"),
                   seed: str = Form(""), image: UploadFile | None = File(None)):
    img_path = None
    if image is not None and image.filename:
        ext = pathlib.Path(image.filename).suffix.lower() or ".png"
        if ext not in (".png", ".jpg", ".jpeg", ".webp"):
            raise HTTPException(400, "картинка должна быть png/jpg/webp")
        dest = UPLOADS / f"{uuid.uuid4().hex}{ext}"
        dest.write_bytes(await image.read())
        img_path = str(dest)
    s = int(seed) if seed.strip().isdigit() else random.randint(0, 2**31 - 1)
    return enqueue(prompt, fmt, seconds, s, img_path)


@app.post("/api/retry/{job_id}")
def retry(job_id: str):
    j = find(job_id)
    return enqueue(j["prompt"], j["format"], j["seconds"], random.randint(0, 2**31 - 1), j.get("image"))


@app.get("/api/jobs")
def list_jobs():
    with lock:
        return list(reversed(jobs))


@app.get("/api/jobs/{job_id}/log")
def job_log(job_id: str):
    find(job_id)
    p = LOGS / f"{job_id}.log"
    text = p.read_text(errors="replace") if p.exists() else ""
    return {"log": text[-6000:]}


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE


PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>LTX-2.5 студия</title>
<style>
:root{--bg:#111318;--card:#1b1e25;--line:#2c313b;--text:#e8eaef;--muted:#9aa1ad;--accent:#6c7cff;--bad:#ff6b6b;--good:#4cc38a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 system-ui,sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:20px 16px}h1{font-size:22px;margin:0 0 16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:16px}
textarea{width:100%;min-height:130px;background:#0d0f13;color:var(--text);border:1px solid var(--line);border-radius:8px;padding:10px;font:inherit;resize:vertical}
.row{display:flex;flex-wrap:wrap;gap:12px;margin-top:12px;align-items:end}
label{display:flex;flex-direction:column;gap:4px;font-size:13px;color:var(--muted)}
select,input{background:#0d0f13;color:var(--text);border:1px solid var(--line);border-radius:8px;padding:8px;font:inherit}
button{background:var(--accent);color:#fff;border:0;border-radius:8px;padding:10px 18px;font:inherit;font-weight:600;cursor:pointer}
button.ghost{background:transparent;border:1px solid var(--line);color:var(--text);padding:6px 12px;font-weight:400}
.hint{color:var(--muted);font-size:13px;margin-top:8px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px}
.job video{width:100%;border-radius:8px;background:#000;margin-top:8px}
.st{font-size:12px;padding:2px 8px;border-radius:99px;border:1px solid var(--line)}
.done{color:var(--good)}.error{color:var(--bad)}.running{color:var(--accent)}
.p{font-size:13px;color:var(--muted);margin:6px 0;max-height:4.5em;overflow:hidden}
pre{white-space:pre-wrap;font-size:11px;max-height:160px;overflow:auto;background:#0d0f13;padding:8px;border-radius:6px;color:var(--muted)}
.acts{display:flex;gap:8px;margin-top:8px;flex-wrap:wrap}a{color:var(--accent)}
</style></head><body><div class="wrap">
<h1>LTX-2.5 студия</h1>
<form class="card" id="f">
<textarea name="prompt" placeholder="Опишите сцену по-английски: кто, что делает, движение камеры, звук..." required></textarea>
<div class="row">
<label>Формат<select name="fmt"><option value="16:9">16:9 · 1280×704</option><option value="9:16">9:16 · 704×1280 (шортс)</option><option value="1:1">1:1 · 960×960</option></select></label>
<label>Длительность<select name="seconds"><option value="5">5 сек</option><option value="8">8 сек</option><option value="10">10 сек</option><option value="15">15 сек (окнами)</option><option value="20">20 сек (окнами)</option></select></label>
<label>Seed<input name="seed" placeholder="случайный" size="10"></label>
<label>Первый кадр (необязательно)<input type="file" name="image" accept="image/png,image/jpeg,image/webp"></label>
<button type="submit">Сгенерировать</button>
</div>
<div class="hint">Задачи выполняются по очереди. Первый клип после запуска дольше: модель грузится в память.</div>
</form>
<div class="grid" id="jobs"></div></div>
<script>
const $=s=>document.querySelector(s);const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const names={queued:'в очереди',running:'генерируется…',done:'готово',error:'ошибка'};
const openLogs=new Set();
$('#f').onsubmit=async e=>{e.preventDefault();const r=await fetch('api/generate',{method:'POST',body:new FormData(e.target)});
 if(!r.ok){alert((await r.json()).detail||'ошибка');return}e.target.seed.value='';load()};
async function retry(id){await fetch('api/retry/'+id,{method:'POST'});load()}
async function toggleLog(id){openLogs.has(id)?openLogs.delete(id):openLogs.add(id);load()}
async function load(){const js=await (await fetch('api/jobs')).json();
 const parts=await Promise.all(js.map(async j=>{
  let el=`<span class="st ${j.status}">${names[j.status]}</span> <small>${j.format} · ${j.seconds} c · seed ${j.seed}${j.took?` · ${j.took} c`:''}${j.image?' · из картинки':''}</small>
  <div class="p">${esc(j.prompt)}</div>`;
  if(j.status==='done')el+=`<video src="videos/${j.file}" controls preload="metadata"></video>`;
  if(j.error)el+=`<div class="error" style="font-size:13px">${esc(j.error)}</div>`;
  el+=`<div class="acts">`;
  if(j.status==='done')el+=`<a href="videos/${j.file}" download>скачать</a>`;
  el+=`<button class="ghost" onclick="retry('${j.id}')">ещё вариант</button><button class="ghost" onclick="toggleLog('${j.id}')">лог</button></div>`;
  if(openLogs.has(j.id)||j.status==='running'){const l=await (await fetch('api/jobs/'+j.id+'/log')).json();el+=`<pre>${esc(l.log||'…')}</pre>`}
  return [j.id,el]}));
 // обновляем только изменившиеся карточки, чтобы не сбивать воспроизведение видео
 const box=$('#jobs');if(!parts.length){box.innerHTML='<div class="hint">Пока пусто.</div>';return}
 box.querySelector('.hint')?.remove();
 let prev=null;
 for(const [id,html] of parts){let c=document.getElementById('j-'+id);
  if(!c){c=document.createElement('div');c.className='card job';c.id='j-'+id;
   prev?prev.after(c):box.prepend(c)}
  if(c.dataset.h!==html){c.innerHTML=html;c.dataset.h=html}
  prev=c}}
load();setInterval(load,4000);
</script></body></html>"""
APP_EOF
say "Ночной режим: /workspace/studio/remote/film_night.sh (загружается с компьютера вместе с планом)"
mkdir -p /workspace/film/plans
cat > "$UI/start.sh" <<'START_EOF'
#!/bin/bash
source /workspace/ltx-ui/env
pkill -f wgp.py || true; pkill -f "uvicorn app:app" || true; sleep 1
cd /workspace/ltx-ui
nohup ./venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port 7860 > server.log 2>&1 &
sleep 4
if curl -s -o /dev/null localhost:7860/; then
  echo -e "\033[1;32mГотово! Откройте в RunPod: Connect -> HTTP Service [Port 7860]\033[0m"
else
  echo "Интерфейс не запустился, лог:"; tail -n 30 server.log
fi
START_EOF
chmod +x "$UI/start.sh"
bash "$UI/start.sh"
echo "В следующий раз (после нового Pod) достаточно: bash /workspace/studio/remote/ltx_studio.sh  (установка пропустится)"
