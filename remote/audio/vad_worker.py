#!/usr/bin/env python3
"""Где в клипе звучит речь: Silero VAD. Запускается питоном /workspace/audio/tts/venv.

    python vad_worker.py job.json      job.json: {"items": [{"media": "clip.mp4", "out": "clip.vad.json",
                                                             "fill": {"out": "clean.wav", "extra": [[a, b]]}}]}

LTX сам решает, когда персонаж заговорит (по смыслу промпта), и рисует движение рта в этот момент.
Реплику TTS ставим туда же — иначе рот говорит в тишине, а голос звучит над закрытым ртом.

С `fill` найденная речь (и окна `extra`) вырезается из звука и заполняется соседним куском того же
звука с плавными переходами. Так чистится фоли: модель видит говорящий рот и дорисовывает бормотание
поверх реплики TTS (проверено 2026-10-31: речь в фоли всех трёх сцен с диалогом). Дождь и эмбиент —
однородная текстура, подмена соседним куском на слух незаметна, а глушить их значит оставить дыру.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import numpy as np


def pcm16k(path: str):
    import torch
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return torch.from_numpy(np.frombuffer(raw, np.float32).copy())


def merge(spans: list[list[float]], pad: float, total: float) -> list[list[float]]:
    out: list[list[float]] = []
    for a, b in sorted([max(0.0, a - pad), min(total, b + pad)] for a, b in spans):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def fill_gaps(x: np.ndarray, sr: int, spans: list[list[float]], fade: float = 0.08) -> np.ndarray:
    """x: (сэмплы, каналы). Каждый отрезок заменяется соседним звуком той же длины (до или после)."""
    y = x.copy()
    n, f = len(x), max(1, int(fade * sr))
    bad = np.zeros(n, bool)
    for a, b in spans:
        bad[int(a * sr):int(b * sr)] = True
    ramp = np.sin(np.linspace(0, np.pi / 2, f))[:, None] ** 2
    for a, b in spans:
        i, j = int(a * sr), int(b * sr)
        length = j - i
        if length <= 0:
            continue
        donor = None
        for start in (i - length - f, j + f, 0):        # до отрезка, после, или с начала по кругу
            if start >= 0 and start + length <= n and not bad[start:start + length].any():
                donor = x[start:start + length]
                break
        if donor is None:                                # всё вокруг — тоже речь: тайлим чистые сэмплы
            clean = x[~bad]
            if not len(clean):
                y[i:j] = 0
                continue
            donor = np.resize(clean, (length, x.shape[1]))
        seg = donor.copy()
        k = min(f, length // 2)
        if k:
            seg[:k] = seg[:k] * ramp[:k] + x[i:i + k] * (1 - ramp[:k])          # вход: исходник -> донор
            seg[-k:] = seg[-k:] * (1 - ramp[:k]) + x[j - k:j] * ramp[:k]        # выход: донор -> исходник
        y[i:j] = seg
    return y


def read_wav(path: str) -> tuple[np.ndarray, int]:
    import wave
    with wave.open(path, "rb") as w:
        sr, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width != 2:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "s16le", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.int16).reshape(-1, ch).astype(np.float32) / 32768, sr


def write_wav(path: str, x: np.ndarray, sr: int) -> None:
    import io
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(x.shape[1])
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
    pathlib.Path(path).write_bytes(buf.getvalue())


def main() -> int:
    from silero_vad import get_speech_timestamps, load_silero_vad   # torch только в окружении Pod
    job = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    model = load_silero_vad()
    for it in job.get("items") or []:
        try:
            spans = get_speech_timestamps(pcm16k(it["media"]), model, return_seconds=True, threshold=0.45,
                                          min_speech_duration_ms=200, min_silence_duration_ms=250)
        except Exception as e:  # noqa: BLE001
            print(f"vad: failed {it['media']}: {e}", flush=True)
            continue
        found = [[s["start"], s["end"]] for s in spans]
        pathlib.Path(it["out"]).write_text(json.dumps(found), encoding="utf-8")
        print(f"vad: {pathlib.Path(it['media']).name} {spans}", flush=True)
        if it.get("fill"):
            x, sr = read_wav(it["media"])
            gaps = merge(found + list(it["fill"].get("extra") or []), 0.15, len(x) / sr)
            write_wav(it["fill"]["out"], fill_gaps(x, sr, gaps), sr)
            print(f"fill: {pathlib.Path(it['fill']['out']).name} {gaps}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
