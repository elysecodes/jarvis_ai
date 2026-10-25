"""
JARVIS configuration.

Settings can be changed in three ways (highest priority first):
  1. Environment variables (e.g. JARVIS_OLLAMA_MODEL)
  2. A `config.json` file in the project folder (optional, handy for beginners)
  3. The built-in defaults written below

Nothing here ever contains passwords or API keys: JARVIS only talks to the
local Ollama server on your own machine.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Where things live
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
GENERATED_CODE_DIR = BASE_DIR / "generated_code"
CONFIG_JSON_PATH = BASE_DIR / "config.json"

# Folders JARVIS is allowed to touch (Phase 3 uses this; empty = none allowed yet).
# Add more by editing config.json, for example:
#   "approved_directories": ["C:/Users/Students/Documents/jarvis_workspace"]
DEFAULT_APPROVED_DIRECTORIES: list[str] = []

ASSISTANT_NAME = "JARVIS"

# Offline speech recognition model (Vosk). Downloaded once into models\ (Phase 2).
VOSK_MODEL_DIR = BASE_DIR / "models" / "vosk-model-small-en-us-0.15"

# ---------------------------------------------------------------------------
# Built-in defaults
# ---------------------------------------------------------------------------
_DEFAULTS = {
    "ollama_url": "http://localhost:11434",
    # Chosen from this PC's RAM (about 8 GB), so a small 3B model fits nicely.
    "ollama_model": "llama3.2:3b",
    "request_timeout": 60,  # seconds to wait for Ollama
    "enable_tts": True,  # speak answers out loud (pyttsx3 / Windows SAPI5)
    "tts_rate": 175,  # words per second feel; 175 is a calm default
    "tts_volume": 1.0,  # 0.0 to 1.0
    "approved_directories": DEFAULT_APPROVED_DIRECTORIES,
    # --- voice (Phase 2) ---
    "vosk_model_path": str(VOSK_MODEL_DIR),
    "input_device": None,  # None = Windows default mic; can be a number or name
    "wake_word": "hey jarvis",
    "command_timeout": 6,  # seconds to wait for your command after the wake word
    "wake_timeout": 0,  # 0 = listen for the wake word forever
}

# Environment variable name -> config key
_ENV_VARS = {
    "JARVIS_OLLAMA_URL": "ollama_url",
    "JARVIS_OLLAMA_MODEL": "ollama_model",
    "JARVIS_REQUEST_TIMEOUT": "request_timeout",
    "JARVIS_ENABLE_TTS": "enable_tts",
    "JARVIS_TTS_RATE": "tts_rate",
    "JARVIS_TTS_VOLUME": "tts_volume",
    "JARVIS_VOSK_MODEL_PATH": "vosk_model_path",
    "JARVIS_INPUT_DEVICE": "input_device",
    "JARVIS_WAKE_WORD": "wake_word",
    "JARVIS_COMMAND_TIMEOUT": "command_timeout",
    "JARVIS_WAKE_TIMEOUT": "wake_timeout",
}


def _as_bool(value: object) -> bool:
    """Turn "true"/"1"/"yes" (or a real bool) into True/False."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _load_json_config() -> dict:
    """Read config.json if it exists. A broken file is ignored (with a warning)."""
    if not CONFIG_JSON_PATH.exists():
        return {}
    try:
        with CONFIG_JSON_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            print(f"[config] Ignoring {CONFIG_JSON_PATH.name}: it must contain a JSON object.")
            return {}
        return data
    except (OSError, ValueError) as exc:
        print(f"[config] Could not read {CONFIG_JSON_PATH.name}: {exc}. Using defaults.")
        return {}


_json_config = _load_json_config()


def _setting(key: str):
    """Look up one setting: env var, then config.json, then the default."""
    env_name = next((name for name, k in _ENV_VARS.items() if k == key), None)
    if env_name and os.environ.get(env_name) not in (None, ""):
        return os.environ[env_name]
    if key in _json_config:
        return _json_config[key]
    return _DEFAULTS[key]


# ---------------------------------------------------------------------------
# Final settings used by the rest of the program
# ---------------------------------------------------------------------------
OLLAMA_URL: str = str(_setting("ollama_url")).rstrip("/")
OLLAMA_MODEL: str = str(_setting("ollama_model"))
REQUEST_TIMEOUT: int = int(_setting("request_timeout"))
ENABLE_TTS: bool = _as_bool(_setting("enable_tts"))
TTS_RATE: int = int(_setting("tts_rate"))
TTS_VOLUME: float = float(_setting("tts_volume"))
APPROVED_DIRECTORIES: list[str] = list(_setting("approved_directories") or [])

# --- voice settings (Phase 2) ----------------------------------------------
VOSK_MODEL_PATH: Path = Path(str(_setting("vosk_model_path")))
WAKE_WORD: str = str(_setting("wake_word"))
COMMAND_TIMEOUT: float = float(_setting("command_timeout"))
WAKE_TIMEOUT: float = float(_setting("wake_timeout"))


def _parse_device(raw) -> "int | str | None":
    """Turn the saved input-device value into something sounddevice understands."""
    if raw in (None, "", "default"):
        return None
    text = str(raw).strip()
    if text.lstrip("-").isdigit():  # e.g. "1" means device index 1
        return int(text)
    return text  # otherwise treat it as (part of) the device name


INPUT_DEVICE = _parse_device(_setting("input_device"))

# The personality / behaviour instructions sent to the local model.
SYSTEM_PROMPT = (
    "You are JARVIS, a polite, concise and professional voice assistant running "
    "locally on the user's Windows 11 computer. "
    "Answer in short, clear sentences (two or three at most) because your replies "
    "may be read out loud. Use plain language and avoid markdown symbols, emoji and "
    "long lists. If you are unsure, say so honestly. Never invent actions you cannot "
    "actually perform: you can chat and explain things, but you cannot run commands "
    "directly. Call yourself JARVIS."
)


def describe() -> str:
    """A short, human-readable summary (safe to print: no secrets)."""
    return (
        f"model={OLLAMA_MODEL}  ollama={OLLAMA_URL}  "
        f"tts={'on' if ENABLE_TTS else 'off'}"
    )
