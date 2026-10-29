#!/usr/bin/env python3
"""Музыка к фильму: ACE-Step 1.5. Запускается питоном окружения ACE-Step (uv sync в репозитории).

    python music_worker.py job.json

job.json: {"items": [{"caption": "slow melancholic piano and strings, sparse, cinematic",
                       "duration": 62.5, "bpm": 70, "keyscale": "A minor", "seed": 7, "out": "score.wav"}]}

Партитура генерируется ровно в длину фильма, только инструментал (голос — отдельная дорожка).
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import sys

REPO = os.environ.get("ACESTEP_REPO", "/workspace/audio/music/ACE-Step-1.5")
JOB = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else ""   # до chdir: путь может быть относительным
sys.path.insert(0, REPO)
os.chdir(REPO)

from acestep.handler import AceStepHandler  # noqa: E402
from acestep.inference import GenerationConfig, GenerationParams, generate_music  # noqa: E402


def ready(path: str) -> bool:
    """Готовый файл, а не пустышка от прерванной записи."""
    p = pathlib.Path(path)
    return p.exists() and p.stat().st_size > 1024


def main() -> int:
    job = json.loads(pathlib.Path(JOB).read_text(encoding="utf-8"))
    items = [it for it in job.get("items") or [] if not ready(it["out"])]
    if not items:
        print("music: nothing to do", flush=True)
        return 0
    dit = AceStepHandler()
    status, ok = dit.initialize_service(project_root=REPO, config_path=job.get("model", "acestep-v15-turbo"),
                                        device="cuda")
    if ok is False:
        print(f"music: init failed: {status}", flush=True)
        return 1
    failed = 0
    for it in items:
        params = GenerationParams(caption=it["caption"], lyrics="[Instrumental]", instrumental=True,
                                  duration=float(it["duration"]), bpm=it.get("bpm") or None,
                                  keyscale=it.get("keyscale") or "", thinking=False,
                                  inference_steps=int(job.get("steps", 8)), seed=int(it.get("seed", 1)))
        config = GenerationConfig(batch_size=1, use_random_seed=False, seeds=[int(it.get("seed", 1))],
                                  audio_format="wav")
        out = pathlib.Path(it["out"])
        tmp = out.parent / f".{out.stem}_tmp"
        result = generate_music(dit, None, params, config, save_dir=str(tmp))
        if not result.success or not result.audios:
            print(f"music: failed {out.name}: {result.error}", flush=True)
            failed += 1
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(result.audios[0]["path"], out)
        shutil.rmtree(tmp, ignore_errors=True)
        print(f"music: {out.name} {it['duration']:.1f}s", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
