"""Конфигурация студии: film_config.json + переменные окружения."""
from __future__ import annotations

import json
import os
import pathlib

HERE = pathlib.Path(__file__).resolve().parent.parent
CFG_PATH = pathlib.Path(os.environ.get("FILM_CONFIG", HERE / "film_config.json"))

DEFAULTS: dict = {
    "runpod_api_key": "",
    "network_volume_id": "",
    "gpu_types": ["NVIDIA GeForce RTX 5090", "NVIDIA L40S", "NVIDIA RTX 6000 Ada Generation"],
    "cloud_type": "SECURE",
    "max_hours": 10,
    "ntfy_topic": "",
    "hf_token": "",
    "quality": "high",
    "gpu_price_per_hour": 2.5,
    "llm": {
        "provider": "auto",            # auto | anthropic | ollama
        "model": "",                   # пусто = значение по умолчанию провайдера
        "ollama_url": "http://localhost:11434",
        "ollama_model": "qwen3:8b",
        "effort": "high",
    },
    "elevenlabs_api_key": "",
    "elevenlabs_voice_id": "",
    "elevenlabs_model": "eleven_multilingual_v2",
    "assets_dir": "assets",
    "plans_dir": "plans",
    "films_dir": "films",
    "series_dir": "series",
    "prefs_file": "studio_prefs.md",
}


class ConfigError(RuntimeError):
    pass


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(require_runpod: bool = False) -> dict:
    cfg = dict(DEFAULTS)
    if CFG_PATH.exists():
        try:
            cfg = _merge(cfg, json.loads(CFG_PATH.read_text(encoding="utf-8")))
        except json.JSONDecodeError as e:
            raise ConfigError(f"{CFG_PATH.name}: невалидный JSON ({e})") from e
    # переменные окружения перекрывают файл
    env_map = {"RUNPOD_API_KEY": "runpod_api_key", "RUNPOD_VOLUME_ID": "network_volume_id", "HF_TOKEN": "hf_token",
               "NTFY_TOPIC": "ntfy_topic", "ELEVENLABS_API_KEY": "elevenlabs_api_key"}
    for env, key in env_map.items():
        if os.environ.get(env):
            cfg[key] = os.environ[env]
    if os.environ.get("STUDIO_LLM_PROVIDER"):
        cfg["llm"]["provider"] = os.environ["STUDIO_LLM_PROVIDER"]
    if os.environ.get("STUDIO_LLM_MODEL"):
        cfg["llm"]["model"] = os.environ["STUDIO_LLM_MODEL"]
    if require_runpod:
        for k in ("runpod_api_key", "network_volume_id"):
            if not cfg.get(k) or "ВСТАВЬТЕ" in str(cfg.get(k)):
                raise ConfigError(f"Заполните {k} в {CFG_PATH.name} (см. film_config.example.json)")
    cfg["_root"] = str(HERE)
    return cfg


def path_in_root(cfg: dict, key: str) -> pathlib.Path:
    p = pathlib.Path(cfg[key])
    return p if p.is_absolute() else pathlib.Path(cfg["_root"]) / p
