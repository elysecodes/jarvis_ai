"""
ai_engine.py - the only place that talks to the local Ollama model.

Every failure (server not running, model not downloaded, timeout) is turned into
a friendly `OllamaError` message with the exact command the user should run.
The program never shows a raw traceback for these cases.
"""

from __future__ import annotations

import logging
from typing import Iterable

import requests

import config

logger = logging.getLogger(__name__)


class OllamaError(Exception):
    """Raised when we cannot get an answer from Ollama.

    The message inside is written for the user, not for a programmer, so it is
    safe to print or speak directly.
    """


def _chat_url() -> str:
    return f"{config.OLLAMA_URL}/api/chat"


def _tags_url() -> str:
    return f"{config.OLLAMA_URL}/api/tags"


def list_models(timeout: int = 5) -> list[str]:
    """Return the names of models already downloaded.

    Returns an empty list if Ollama cannot be reached (callers just use it to
    make error messages nicer).
    """
    try:
        response = requests.get(_tags_url(), timeout=timeout)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.debug("Could not list Ollama models: %s", exc.__class__.__name__)
        return []

    models = data.get("models", []) if isinstance(data, dict) else []
    names: list[str] = []
    for item in models:
        if isinstance(item, dict) and item.get("name"):
            names.append(str(item["name"]))
    return names


def ping(timeout: int = 3) -> tuple[bool, str]:
    """Quick health check.

    Returns (True, friendly message) when Ollama answers, otherwise
    (False, friendly message with the fix).
    """
    try:
        response = requests.get(_tags_url(), timeout=timeout)
        response.raise_for_status()
    except requests.exceptions.ConnectionError:
        return False, _not_running_message()
    except requests.exceptions.Timeout:
        return False, f"Ollama did not answer in {timeout} seconds. It may still be starting up."
    except requests.RequestException as exc:
        return False, f"Could not talk to Ollama ({exc.__class__.__name__}). Check that it is running."

    names = list_models()
    if config.OLLAMA_MODEL not in names:
        return False, _model_missing_message(names)
    return True, f"Ollama is ready (model: {config.OLLAMA_MODEL})."


def chat(
    messages: Iterable[dict],
    model: str | None = None,
    timeout: int | None = None,
) -> str:
    """Ask the model and return its reply as plain text.

    `messages` is the standard Ollama/OpenAI format:
        [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]

    Raises OllamaError with a user-friendly message on any problem.
    """
    model_name = model or config.OLLAMA_MODEL
    wait = timeout or config.REQUEST_TIMEOUT
    payload = {
        "model": model_name,
        "messages": list(messages),
        "stream": False,  # simpler: we get the whole answer in one response
    }

    try:
        response = requests.post(_chat_url(), json=payload, timeout=wait)
    except requests.exceptions.ConnectionError:
        logger.warning("Ollama connection failed")
        raise OllamaError(_not_running_message()) from None
    except requests.exceptions.Timeout:
        logger.warning("Ollama request timed out after %s seconds", wait)
        raise OllamaError(
            f"Ollama took longer than {wait} seconds to answer. "
            "Try a smaller model, or ask a shorter question."
        ) from None
    except requests.exceptions.RequestException as exc:
        logger.warning("Ollama request failed: %s", exc.__class__.__name__)
        raise OllamaError(
            f"Could not reach Ollama ({exc.__class__.__name__}). Check your network settings."
        ) from None

    if response.status_code == 404:
        # Ollama uses 404 when the model name is unknown.
        logger.warning("Ollama reports model missing (404)")
        raise OllamaError(_model_missing_message(list_models()))

    if response.status_code >= 400:
        logger.warning("Ollama returned HTTP %s", response.status_code)
        raise OllamaError(
            f"Ollama rejected the request (HTTP {response.status_code}). "
            f"Check that the model '{model_name}' is installed."
        )

    try:
        data = response.json()
    except ValueError:
        logger.warning("Ollama returned something that is not JSON")
        raise OllamaError(
            "Ollama sent an answer we could not read. Restart Ollama and try again."
        ) from None

    content = _extract_content(data)
    if content is None:
        logger.warning("Ollama response had no message content")
        raise OllamaError("Ollama sent an empty answer. Please try asking again.")
    return content


def _extract_content(data: object) -> str | None:
    """Pull the reply text out of Ollama's JSON, whatever shape it is in."""
    if not isinstance(data, dict):
        return None
    message = data.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        text = message["content"].strip()
        return text or None
    # Some endpoints return a plain "response" field instead.
    if isinstance(data.get("response"), str):
        text = data["response"].strip()
        return text or None
    return None


def _not_running_message() -> str:
    return (
        "I cannot reach Ollama, so my AI answers are unavailable. "
        "Open a Command Prompt and run: ollama serve  "
        "(or just start the Ollama app). Rule-based commands like the time or date still work."
    )


def _model_missing_message(installed: list[str]) -> str:
    installed_text = ", ".join(installed) if installed else "none found"
    return (
        f"The model '{config.OLLAMA_MODEL}' is not installed. "
        f"Run this command: ollama pull {config.OLLAMA_MODEL}  "
        f"(installed models: {installed_text})"
    )
