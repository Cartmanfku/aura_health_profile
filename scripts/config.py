"""Paths, API key loading, and DashScope OpenAI-compatible chat completions."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests

CHAT_COMPLETIONS_URL = (
    "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
)
DEFAULT_VISION_MODEL = os.environ.get("AURA_VISION_MODEL", "qwen3.6-plus")
DEFAULT_TEXT_MODEL = os.environ.get("AURA_TEXT_MODEL", "qwen3.6-plus")

AURA_STATE_HOME = Path(os.environ.get("AURA_STATE_HOME", Path.home() / ".aura-health"))
INTERMEDIATE_DIR = AURA_STATE_HOME / "intermediate"
METRICS_PATH = AURA_STATE_HOME / "metrics.json"
PROCESSED_PATH = AURA_STATE_HOME / "processed.json"
PROFILE_MERGE_STATE_PATH = AURA_STATE_HOME / "profile_merge_state.json"
CONFIG_PATH = AURA_STATE_HOME / "config.json"

OUTPUT_ROOT = Path(
    os.environ.get("AURA_OUTPUT_DIR", Path.home() / "Documents" / "AuraHealth")
)

_ZH_HINTS = {
    "zh",
    "zh-cn",
    "zh-hans",
    "chinese",
    "simplified chinese",
    "cn",
    "中文",
    "简体中文",
}


def skill_dir() -> Path:
    """Directory containing SKILL.md (parent of scripts/)."""
    return Path(__file__).resolve().parent.parent


def ensure_state_dirs() -> None:
    AURA_STATE_HOME.mkdir(parents=True, exist_ok=True)
    INTERMEDIATE_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)


def _load_local_config() -> dict[str, Any]:
    if not CONFIG_PATH.is_file():
        return {}
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def preferred_language() -> str:
    """Return normalized user language for profile generation ('zh-CN' or 'en')."""
    raw = (
        os.environ.get("AURA_USER_LANGUAGE", "").strip()
        or os.environ.get("AURA_PROFILE_LANGUAGE", "").strip()
    )
    if not raw:
        cfg = _load_local_config()
        raw = str(
            cfg.get("preferred_language")
            or cfg.get("common_language")
            or cfg.get("language")
            or ""
        ).strip()

    token = raw.lower().replace("_", "-")
    if token in _ZH_HINTS or token.startswith("zh-"):
        return "zh-CN"
    return "en"


def load_api_key() -> str:
    key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if key:
        return key
    data = _load_local_config()
    key = str(data.get("dashscope_api_key", "")).strip()
    if key:
        return key
    raise SystemExit(
        f"Missing API key: set DASHSCOPE_API_KEY or {CONFIG_PATH} "
        'with {"dashscope_api_key": "sk-..."}'
    )


def chat_completions(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 8192,
) -> str:
    """POST to DashScope compatible chat/completions; return assistant text."""
    api_key = load_api_key()
    model = model or DEFAULT_TEXT_MODEL
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    r = requests.post(
        CHAT_COMPLETIONS_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=300,
    )
    if not r.ok:
        raise RuntimeError(
            f"DashScope HTTP {r.status_code}: {r.text[:2000]}"
        )
    data = r.json()
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"Unexpected API response: {data!r}") from e
