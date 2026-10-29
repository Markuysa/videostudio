#!/usr/bin/env python3
"""Имитация звуковых воркеров для тестов: fake_audio.py tts|foley|music job.json — пишет синус нужной длины."""
import json
import pathlib
import subprocess
import sys

kind, job = sys.argv[1], json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))


def tone(out: str, seconds: float, freq: int) -> None:
    pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    f"sine=frequency={freq}:sample_rate=48000:duration={seconds}", out], check=True)


if kind == "tts":
    for v in job["voices"].values():
        if not v.get("sample"):
            tone(v["cache"], 3.0, 220)
    for ln in job["lines"]:
        tone(ln["out"], 0.08 * len(ln["text"]), 330)       # длина «речи» пропорциональна тексту
elif kind == "foley":
    for it in job["items"]:
        dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                              it["video"]], capture_output=True, text=True).stdout.strip()
        tone(it["out"], float(dur), 110)
elif kind == "music":
    for it in job["items"]:
        tone(it["out"], it["duration"], 523)
