#!/usr/bin/env python3
"""Фоли и эмбиент по картинке: HunyuanVideo-Foley. Запускается питоном /workspace/audio/foley/venv.

    python foley_worker.py job.json

job.json: {"items": [{"video": "clip.mp4", "prompt": "footsteps on wet asphalt, distant traffic",
                       "out": "clip_foley.wav", "seed": 1}], "steps": 50, "guidance": 4.5}

Модель грузится один раз на все сцены фильма. Речь и музыку модель не должна рисовать:
это отдельные дорожки, поэтому они всегда в негативном промпте.
"""
from __future__ import annotations

import json
import os
import pathlib
import random
import sys

REPO = os.environ.get("FOLEY_REPO", "/workspace/audio/foley/HunyuanVideo-Foley")
WEIGHTS = os.environ.get("FOLEY_WEIGHTS", "/workspace/models/audio/HunyuanVideo-Foley")
JOB = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else ""   # до chdir: путь может быть относительным
sys.path.insert(0, REPO)
os.chdir(REPO)

import numpy as np  # noqa: E402
import torch  # noqa: E402
from hunyuanvideo_foley.utils.feature_utils import feature_process  # noqa: E402
from hunyuanvideo_foley.utils.model_utils import denoise_process, load_model  # noqa: E402

NEG = "speech, talking, voice, singing, music, noisy, harsh"


def save_wav(path: pathlib.Path, audio, sr: int) -> None:
    """16-бит WAV через stdlib: torchaudio>=2.9 требует torchcodec, а libsndfile не пишет на том RunPod."""
    import io
    import wave
    a = audio.float().cpu().clamp(-1, 1).numpy()
    a = a.T if a.ndim == 2 else a[:, None]                  # (каналы, сэмплы) -> (сэмплы, каналы)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(a.shape[1])
        w.setsampwidth(2)
        w.setframerate(int(sr))
        w.writeframes((a * 32767).astype(np.int16).tobytes())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buf.getvalue())


def ready(path: str) -> bool:
    """Готовый файл, а не пустышка от прерванной записи."""
    p = pathlib.Path(path)
    return p.exists() and p.stat().st_size > 1024


def main() -> int:
    job = json.loads(pathlib.Path(JOB).read_text(encoding="utf-8"))
    items = [it for it in job.get("items") or [] if not ready(it["out"])]
    if not items:
        print("foley: nothing to do", flush=True)
        return 0
    size = job.get("model_size", "xxl")
    cfg_path = f"{REPO}/configs/hunyuanvideo-foley-{size}.yaml"
    model_dict, cfg = load_model(WEIGHTS, cfg_path, torch.device("cuda:0"), enable_offload=False, model_size=size)
    failed = 0
    for it in items:
        seed = int(it.get("seed", 1))
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        try:
            visual, text, seconds = feature_process(it["video"], it["prompt"], model_dict, cfg,
                                                    neg_prompt=it.get("neg") or NEG)
            audio, sr = denoise_process(visual, text, seconds, model_dict, cfg,
                                        guidance_scale=float(job.get("guidance", 4.5)),
                                        num_inference_steps=int(job.get("steps", 50)))
        except Exception as e:  # noqa: BLE001
            print(f"foley: failed {it['video']}: {e}", flush=True)
            failed += 1
            continue
        out = pathlib.Path(it["out"])
        save_wav(out, audio[0] if audio.ndim == 3 else audio, sr)
        print(f"foley: {out.name} {seconds:.2f}s", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
