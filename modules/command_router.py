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
from modules import ai_engine, coding_assistant, computer_control

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


# --- actions on the PC (Phase 3) --------------------------------------------
# JARVIS can only request a NAMED action from the allowlist in
# computer_control.py. It never builds or runs a shell command.
_LIST_APPS_RE = re.compile(r"\b(?:list|which|what)\b.*\bapps?\b")
_RUN_SCRIPT_RE = re.compile(r"^(?:run|execute)\s+(?:the\s+)?(?:script|program)\s+(.+)$")
_OPEN_FILE_RE = re.compile(r"^(?:open|show|view)\s+(?:the\s+)?(?:file|document)\s+(.+)$")
_OPEN_APP_RE = re.compile(
    r"^(?:open|launch|start|run)\s+(?:the\s+|up\s+)?(.+?)(?:\s+(?:app|application))?$"
)

# Words that mean the question is about programming, so the coding assistant
# (Phase 4) answers it with a code-friendly prompt instead of the chat prompt.
_CODING_RE = re.compile(
    r"\b(code|coding|python|programming|function|debug|debugging|traceback|bug|syntax)\b"
)

# --- coding assistant commands (Phase 4) ------------------------------------
# "save that as hello.py" saves the previous answer, so a snippet can be kept
# without copy/paste. Everything still goes through security + confirmation.
_SAVE_CODE_RE = re.compile(
    r"^(?:save|write|keep)\s+(?:this|that|it)"
    r"(?:\s+(?:code|script|snippet|answer|program))?"
    r"\s+(?:as|to|in)\s+(\S+\.py)$"
)
_LIST_CODE_RE = re.compile(
    r"^(?:list|show)\s+(?:me\s+)?(?:my\s+)?(?:saved\s+)?(?:code|snippets?|files?)$"
)
_REVIEW_CODE_RE = re.compile(
    r"^(?:review|check|explain|look at)\s+(?:the\s+)?(?:file\s+|code\s+)?(?:in\s+)?([\w\-.]+\.py)$"
)


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
            "You can ask me the time or the date, say hello, ask a programming "
            "question, open an app such as notepad, or say 'save that as hello.py' "
            "to keep the last answer. For anything else I will think about it with "
            "your local AI model. Say 'exit' or 'goodbye JARVIS' to stop me.",
            source="rule",
        )

    if _THANKS_RE.search(cleaned):
        return Response("You are welcome.", source="rule")

    # 5. Coding assistant commands (save / list / review) ------------------
    coding_action = _handle_coding_action(cleaned, history or [])
    if coding_action is not None:
        return coding_action

    # 6. Safe things on the PC (apps, files, scripts) ----------------------
    action = _handle_action(cleaned)
    if action is not None:
        return action

    # 7. Programming questions go to the coding assistant (Phase 4) --------
    if _CODING_RE.search(cleaned):
        return _ask_coder(cleaned, history or [])

    # 8. Everything else: ask the local AI model ---------------------------
    return _ask_model(cleaned, history or [])


def _clean_target(raw: str) -> str:
    """Tidy a name from speech: strip quotes, spaces and trailing punctuation."""
    return raw.strip().strip("\"'").rstrip(".!? ").strip()


def _handle_action(cleaned: str) -> Response | None:
    """Try the safe named actions (look first). Returns None if not an action."""
    if _LIST_APPS_RE.search(cleaned):
        apps = ", ".join(computer_control.list_allowed_apps())
        return Response(
            f"I can open: {apps}. For example, say 'open notepad'.", source="rule"
        )

    match = _RUN_SCRIPT_RE.match(cleaned)
    if match:
        script = _clean_target(match.group(1))
        return Response(computer_control.run_script(script), source="action")

    match = _OPEN_FILE_RE.match(cleaned)
    if match:
        target = _clean_target(match.group(1))
        return Response(computer_control.open_file(target), source="action")

    match = _OPEN_APP_RE.match(cleaned)
    if match:
        app = _clean_target(match.group(1))
        try:
            return Response(computer_control.launch_app(app), source="action")
        except computer_control.ControlError as exc:
            return Response(str(exc), source="rule")

    return None


def _last_code_answer(history: list[dict]) -> str:
    """The most recent answer from the model (what 'save that as x.py' saves)."""
    for turn in reversed(history):
        if turn.get("role") == "assistant" and turn.get("content"):
            return str(turn["content"])
    return ""


def _handle_coding_action(cleaned: str, history: list[dict]) -> Response | None:
    """The coding assistant's own commands: save, list, review a file."""
    if _LIST_CODE_RE.match(cleaned):
        names = coding_assistant.list_generated_code()
        if not names:
            return Response(
                "You have not saved any code yet. Ask me for a snippet, then say "
                "'save that as hello.py'.",
                source="rule",
            )
        return Response("Saved code: " + ", ".join(names) + ".", source="rule")

    match = _SAVE_CODE_RE.match(cleaned)
    if match:
        filename = _clean_target(match.group(1))
        code = _last_code_answer(history)
        if not code:
            return Response(
                "I have no code to save yet. Ask me for a snippet first, then say "
                "'save that as hello.py'.",
                source="rule",
            )
        return Response(coding_assistant.save_code_snippet(filename, code), source="action")

    match = _REVIEW_CODE_RE.match(cleaned)
    if match:
        name = _clean_target(match.group(1))
        try:
            code = coding_assistant.load_code(name)
        except coding_assistant.CodingError as exc:
            return Response(str(exc), source="rule")
        return _ask_coder(f"Please review the file {name}.", history, code=code)

    return None


def _ask_coder(text: str, history: list[dict], code: str = "") -> Response:
    """Answer a programming question (or review `code`) with the coding prompt."""
    if code:
        answer = coding_assistant.review_code(code, filename=_file_from_text(text))
    else:
        answer = coding_assistant.answer_coding_question(text, history)
    new_history = history + [
        {"role": "user", "content": text},
        {"role": "assistant", "content": answer},
    ]
    return Response(answer, source="coding", history=new_history[-6:])


def _file_from_text(text: str) -> str:
    """Pull 'name.py' out of 'Please review the file name.py.' (cosmetic only)."""
    match = re.search(r"([\w\-.]+\.py)", text)
    return match.group(1) if match else ""


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
