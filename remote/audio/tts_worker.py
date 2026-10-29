#!/usr/bin/env python3
"""Голоса персонажей: Qwen3-TTS. Запускается питоном /workspace/audio/tts/venv.

    python tts_worker.py job.json

job.json:
  {"voices": {"Анна": {"instruct": "Female, 30, warm alto...", "ref_text": "...", "language": "Russian",
                       "sample": "/path/ref.wav" | null, "cache": "/workspace/film/voices/<key>.wav"}},
   "lines": [{"voice": "Анна", "text": "...", "language": "Russian", "out": "/path/line.wav"}]}

Голос без образца сначала «кастингуется» моделью VoiceDesign по описанию (короткая проба
сохраняется в cache и переиспользуется во всех сценах и сериях), затем все реплики
клонируются моделью Base с этой пробы — тембр одинаковый от сцены к сцене.
"""
from __future__ import annotations

import gc
import io
import json
import os
import pathlib
import sys

import soundfile as sf
import torch
from qwen_tts import Qwen3TTSModel

MODELS = os.environ.get("AUDIO_MODELS", "/workspace/models/audio")
LANGS = {"ru": "Russian", "en": "English", "zh": "Chinese", "ja": "Japanese", "ko": "Korean", "de": "German",
         "fr": "French", "pt": "Portuguese", "es": "Spanish", "it": "Italian"}


def lang(code: str | None) -> str:
    code = (code or "ru").strip()
    return LANGS.get(code.lower(), code)


def load(name: str) -> Qwen3TTSModel:
    return Qwen3TTSModel.from_pretrained(f"{MODELS}/{name}", device_map="cuda:0", dtype=torch.bfloat16,
                                         attn_implementation="sdpa")


def save_wav(path: pathlib.Path, wav, sr: int) -> None:
    """libsndfile не может закрыть WAV прямо на сетевом томе RunPod (MooseFS) — пишем через память."""
    buf = io.BytesIO()
    sf.write(buf, wav, sr, format="WAV")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buf.getvalue())


def free(model) -> None:
    del model
    gc.collect()
    torch.cuda.empty_cache()


def ready(path: str) -> bool:
    """Готовый файл, а не пустышка от прерванной записи."""
    p = pathlib.Path(path)
    return p.exists() and p.stat().st_size > 1024


def main() -> int:
    job = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    voices: dict = job.get("voices") or {}
    lines: list = [ln for ln in job.get("lines") or [] if not ready(ln["out"])]
    refs: dict[str, tuple[str, str]] = {}
    to_design = []
    for name, v in voices.items():
        sample = v.get("sample") or v.get("cache")
        if sample and ready(sample):
            refs[name] = (sample, v.get("ref_text") or "")
        else:
            to_design.append(name)
    if to_design and lines:
        model = load("Qwen3-TTS-12Hz-1.7B-VoiceDesign")
        for name in to_design:
            v = voices[name]
            wavs, sr = model.generate_voice_design(text=v["ref_text"], language=lang(v.get("language")),
                                                   instruct=v["instruct"])
            out = pathlib.Path(v["cache"])
            save_wav(out, wavs[0], sr)
            out.with_suffix(".txt").write_text(v["ref_text"], encoding="utf-8")
            refs[name] = (str(out), v["ref_text"])
            print(f"voice designed: {name} -> {out}", flush=True)
        free(model)
    if not lines:
        print("tts: nothing to do", flush=True)
        return 0
    model = load("Qwen3-TTS-12Hz-1.7B-Base")
    prompts = {}
    failed = 0
    for ln in lines:
        name = ln.get("voice")
        if name not in refs:
            print(f"tts: no voice for {name!r}, skip {ln['out']}", flush=True)
            failed += 1
            continue
        if name not in prompts:
            audio, text = refs[name]
            text = text or (pathlib.Path(audio).with_suffix(".txt").read_text(encoding="utf-8")
                            if pathlib.Path(audio).with_suffix(".txt").exists() else "")
            prompts[name] = model.create_voice_clone_prompt(ref_audio=audio, ref_text=text or None,
                                                            x_vector_only_mode=not text)
        try:
            wavs, sr = model.generate_voice_clone(text=ln["text"], language=lang(ln.get("language")),
                                                  voice_clone_prompt=prompts[name])
        except Exception as e:  # noqa: BLE001 — одна реплика не должна ронять весь фильм
            print(f"tts: failed {ln['out']}: {e}", flush=True)
            failed += 1
            continue
        out = pathlib.Path(ln["out"])
        save_wav(out, wavs[0], sr)
        print(f"line: {out.name} {len(wavs[0]) / sr:.2f}s", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
