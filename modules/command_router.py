"""
command_router.py - decides what to do with what the user typed or said.

How it works (this keeps JARVIS fast and predictable):
  1. Simple, known commands (time, date, greeting, help, goodbye) are answered
     by rules. No AI needed, so they always work - even when Ollama is off.
  2. Anything else is sent to the local Ollama model as a normal chat question.

The router never runs shell commands. It only produces a text answer.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

import config
from modules import ai_engine

logger = logging.getLogger(__name__)


@dataclass
class Response:
    """The result of handling one user command."""

    text: str
    exit: bool = False  # True means: JARVIS should shut down
    source: str = "rule"  # "rule", "llm" or "error"
    history: list[dict] = field(default_factory=list)  # chat turns to remember


# Phrases that shut JARVIS down.
_EXIT_PHRASES = {
    "exit",
    "quit",
    "bye",
    "goodbye",
    "goodbye jarvis",
    "good bye jarvis",
    "shut down",
    "shutdown",
    "stop",
    "stop listening",
    "stop listening jarvis",
    "close yourself",
}

# Words that count as a greeting when they are the whole sentence.
_GREETING_WORDS = {
    "hi",
    "hello",
    "hey",
    "yo",
    "hi jarvis",
    "hello jarvis",
    "hey jarvis",
    "good morning",
    "good afternoon",
    "good evening",
}

_TIME_RE = re.compile(r"\b(time|clock)\b")
_DATE_RE = re.compile(r"\b(date|day|today)\b")
_IDENTITY_RE = re.compile(r"\b(who are you|your name|what are you)\b")
_HELP_RE = re.compile(r"\b(help|what can you do|commands)\b")
_THANKS_RE = re.compile(r"\b(thanks|thank you|cheers)\b")

# Safety: refuse absurdly long inputs before they reach the AI model.
_MAX_INPUT_CHARS = 500


def _normalise(text: str) -> str:
    """Lower-case and squeeze whitespace, so rules match reliably."""
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def is_exit(text: str) -> bool:
    """True if this text means 'shut down JARVIS'."""
    cleaned = _normalise(text).rstrip("!?. ")
    return cleaned in _EXIT_PHRASES or cleaned.startswith("goodbye jarvis")


def _speakable_time() -> str:
    now = datetime.now()
    return now.strftime("%I:%M %p").lstrip("0").strip()


def _speakable_date() -> str:
    now = datetime.now()
    return f"{now.strftime('%A')}, {now.day} {now.strftime('%B %Y')}"


def route(text: str, history: list[dict] | None = None) -> Response:
    """Handle one user command and return a Response.

    `history` is the running conversation (a list of {"role", "content"} dicts).
    It is only used for the AI chat fallback.
    """
    cleaned = _normalise(text)

    if not cleaned:
        return Response("I did not catch that. Please type something.", source="rule")

    if len(cleaned) > _MAX_INPUT_CHARS:
        return Response(
            f"Your message is too long (over {_MAX_INPUT_CHARS} characters). "
            "Please keep it shorter so I can answer quickly.",
            source="rule",
        )

    # 1. Shut down ---------------------------------------------------------
    if is_exit(cleaned):
        return Response(f"Goodbye. Shutting down {config.ASSISTANT_NAME}.", exit=True)

    # 2. Time and date -----------------------------------------------------
    if _TIME_RE.search(cleaned):
        return Response(f"It is {_speakable_time()}.", source="rule")

    if _DATE_RE.search(cleaned):
        return Response(f"Today is {_speakable_date()}.", source="rule")

    # 3. Greetings ---------------------------------------------------------
    if cleaned in _GREETING_WORDS:
        return Response(
            f"Hello. {config.ASSISTANT_NAME} at your service. How can I help?", source="rule"
        )

    # 4. About JARVIS and help --------------------------------------------
    if _IDENTITY_RE.search(cleaned):
        return Response(
            "I am JARVIS, your local assistant. I run entirely on your computer "
            "and I can answer questions, tell the time, and later control a few safe "
            "things on your PC.",
            source="rule",
        )

    if _HELP_RE.search(cleaned):
        return Response(
            "You can ask me the time or the date, say hello, or ask me anything else "
            "and I will think about it with your local AI model. Say 'exit' or "
            "'goodbye JARVIS' to stop me.",
            source="rule",
        )

    if _THANKS_RE.search(cleaned):
        return Response("You are welcome.", source="rule")

    # 5. Everything else: ask the local AI model ---------------------------
    return _ask_model(cleaned, history or [])


def _ask_model(text: str, history: list[dict]) -> Response:
    """Send the question to Ollama. Never raises: failures become a message."""
    messages = [{"role": "system", "content": config.SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": text})

    # The local model needs a few seconds on this PC - say so instead of
    # leaving the user staring at a silent screen.
    print("(thinking...)")

    try:
        answer = ai_engine.chat(messages)
    except ai_engine.OllamaError as exc:
        # The exception message is already written for the user.
        logger.warning("AI fallback failed")
        return Response(str(exc), source="error")
    except Exception as exc:  # safety net: never show a traceback
        logger.exception("Unexpected AI error: %s", exc.__class__.__name__)
        return Response(
            "Something went wrong while thinking about that. Please try again.", source="error"
        )

    # Remember this turn so follow-up questions make sense (kept short to save RAM).
    new_history = history + [
        {"role": "user", "content": text},
        {"role": "assistant", "content": answer},
    ]
    return Response(answer, source="llm", history=new_history[-6:])
