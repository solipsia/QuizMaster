from __future__ import annotations

import json
import os
from pathlib import Path

from .models import ServiceConfig

DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config.default.json"


def get_config_path() -> Path:
    return Path(os.environ.get("QUIZ_CONFIG_PATH", "data/config.json"))


def load_config() -> ServiceConfig:
    path = get_config_path()
    data: dict = {}

    # Load defaults first
    if DEFAULT_CONFIG_PATH.exists():
        with open(DEFAULT_CONFIG_PATH) as f:
            data = json.load(f)

    # Overlay user config if it exists
    if path.exists():
        with open(path) as f:
            user_data = json.load(f)
        data = _deep_merge(data, user_data)

    return ServiceConfig(**data)


def save_config(config: ServiceConfig) -> None:
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(config.model_dump(), f, indent=2)
    tmp.replace(path)


def merge_config_update(current: ServiceConfig, update: dict) -> ServiceConfig:
    current_data = current.model_dump()
    merged = _deep_merge(current_data, update)
    return ServiceConfig(**merged)


def get_api_key(env_var_name: str) -> str | None:
    return os.environ.get(env_var_name)


def check_api_key_set(env_var_name: str) -> bool:
    val = os.environ.get(env_var_name)
    return val is not None and len(val) > 0


def _deep_merge(base: dict, override: dict) -> dict:
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
