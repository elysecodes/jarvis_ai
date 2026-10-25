"""
coding_assistant.py - coding help using the local Ollama model (Phase 4).

Features:
  * Answer coding questions (explain, debug, review) via Ollama.
  * Optionally save generated code snippets to generated_code/ (with
    confirmation + path validation via the security module).
  * Never runs generated code - only saves it for the user to inspect.

All file writes go through security.validate_file_path so generated code can
only land inside approved directories.
"""

from __future__ import annotations

import logging
from pathlib import Path

import config
from modules import ai_engine, security

logger = logging.getLogger(__name__)

# System prompt that keeps the coding assistant helpful and safe.
CODING_SYSTEM_PROMPT = (
    "You are JARVIS, a coding assistant running locally on the user's Windows PC. "
    "Answer coding questions in short, clear sentences. Use plain language, avoid "
    "markdown symbols and long lists. Give practical code examples when useful, "
    "but never suggest code that deletes files, runs shell commands, or accesses "
    "the internet. If you are unsure, say so. Call yourself JARVIS."
)


def answer_coding_question(question: str, history: list[dict] | None = None) -> str:
    """Ask the local model a coding question and return its reply.

    Never raises: Ollama failures become a friendly message.
    """
    history = history or []
    messages = [{"role": "system", "content": CODING_SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": question})

    print("(thinking...)")
    try:
        return ai_engine.chat(messages)
    except ai_engine.OllamaError as exc:
        logger.warning("Coding question failed: %s", exc.__class__.__name__)
        return str(exc)
    except Exception as exc:  # safety net: never show a traceback
        logger.exception("Unexpected coding error: %s", exc.__class__.__name__)
        return "Something went wrong while thinking about that. Please try again."


def list_generated_code() -> list[str]:
    """Return names of files already saved in generated_code/."""
    code_dir = config.GENERATED_CODE_DIR
    if not code_dir.is_dir():
        return []
    return sorted(p.name for p in code_dir.iterdir() if p.is_file())


def save_code_snippet(filename: str, code: str, confirm: bool = True) -> str:
    """Save a code snippet to generated_code/.

    Requires confirmation. The file must live inside generated_code/ and that
    directory must be an approved directory (see config.APPROVED_DIRECTORIES).
    Never runs the saved code.
    """
    if confirm and security.requires_confirmation("save_generated_code"):
        if not security.confirm_action("save code", filename):
            return f"Cancelled: not saving {filename}."

    code_dir = config.GENERATED_CODE_DIR
    code_dir.mkdir(parents=True, exist_ok=True)

    # generated_code must be an approved directory for writes to be allowed.
    if not security.is_approved_directory(code_dir):
        return (
            f"Cannot save {filename}: generated_code/ is not an approved directory. "
            f"Add '{code_dir}' to approved_directories in config.json, then try again."
        )

    target = code_dir / filename
    try:
        resolved = security.validate_file_path(target, must_exist=False)
    except security.SecurityError as exc:
        return str(exc)

    # Block path traversal via filename like "../evil.py".
    if resolved.parent != code_dir.resolve():
        return f"Refusing to save {filename}: path escapes generated_code/."

    try:
        resolved.write_text(code, encoding="utf-8")
        logger.info("Saved code snippet: %s", resolved)
        return f"Saved {filename} to generated_code/."
    except OSError as exc:
        logger.warning("Could not save %s: %s", filename, exc.__class__.__name__)
        return f"Could not save {filename}: {exc}."
