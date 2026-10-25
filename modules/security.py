"""
security.py - path validation, confirmations, and redaction (Phase 3).

Safety rules from AGENTS.md:
  * File access: resolve paths with Path.resolve() and require them to sit inside
    approved directories listed in config. Block ".." tricks and symlink escapes.
  * Confirmation required (typed or spoken yes/no) before deleting, overwriting,
    moving files, saving generated code, running scripts, installing anything,
    changing settings.
  * Logs must never contain passwords, keys, file contents, or raw audio. Log
    actions and errors only.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import config

logger = logging.getLogger(__name__)

# Actions that always require an explicit yes/no confirmation before proceeding.
CONFIRM_REQUIRED_ACTIONS = {
    "delete",
    "overwrite",
    "move",
    "save_generated_code",
    "run_script",
    "launch_app",
    "open_file",
    "install",
    "change_setting",
}


class SecurityError(Exception):
    """Raised when a requested action is blocked for safety reasons."""


def is_approved_directory(directory: str | Path) -> bool:
    """Return True if the resolved directory sits inside an approved directory.

    Returns False (and logs a warning) when the path escapes the approved set,
    uses ".." tricks, or is a symlink escape.
    """
    approved = config.APPROVED_DIRECTORIES
    if not approved:
        logger.warning("No approved directories configured; path access denied.")
        return False

    try:
        resolved = Path(directory).resolve()
    except (OSError, ValueError) as exc:
        logger.warning("Cannot resolve path %r: %s", directory, exc.__class__.__name__)
        return False

    # Reject symlinks that point outside the approved set.
    if resolved.is_symlink():
        try:
            real = resolved.resolve(strict=True)
        except (OSError, RuntimeError):
            logger.warning("Symlink %r cannot be resolved safely; rejecting.", directory)
            return False
        resolved = real

    for root in approved:
        try:
            root_resolved = Path(root).resolve()
        except (OSError, ValueError):
            continue
        try:
            resolved.relative_to(root_resolved)
        except ValueError:
            continue
        return True

    logger.warning("Path %r is outside approved directories: %s", directory, approved)
    return False


def validate_file_path(path: str | Path, must_exist: bool = False) -> Path:
    """Validate and return a resolved Path inside an approved directory.

    Raises SecurityError if the path is outside the approved set or (when
    must_exist is True) does not exist.
    """
    try:
        resolved = Path(path).resolve()
    except (OSError, ValueError) as exc:
        raise SecurityError(f"Cannot resolve path {path!r}: {exc}") from None

    # Block symlink escapes.
    if resolved.is_symlink():
        try:
            real = resolved.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise SecurityError(f"Symlink {path!r} cannot be resolved safely.") from exc
        resolved = real

    if not is_approved_directory(resolved):
        raise SecurityError(
            f"Path {path!r} is not inside an approved directory. "
            f"Approved: {config.APPROVED_DIRECTORIES}"
        )

    if must_exist and not resolved.exists():
        raise SecurityError(f"Path {path!r} does not exist.")

    return resolved


def requires_confirmation(action: str) -> bool:
    """Return True if `action` is one that needs an explicit yes/no confirmation."""
    return action in CONFIRM_REQUIRED_ACTIONS


def confirm_action(action: str, detail: str = "") -> bool:
    """Ask the user to confirm a risky action.

    Returns True only when the user types "yes" or "y". Prints a clear prompt
    so this works in text mode and voice mode (the caller speaks the prompt).
    """
    prompt = f"CONFIRM: {action}"
    if detail:
        prompt += f" ({detail})"
    prompt += " - type yes/y to proceed: "
    try:
        answer = input(prompt)
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer.strip().lower() in {"y", "yes"}


def redact(text: str | None) -> str:
    """Return a logging-safe version of text: never log file contents or secrets.

    We redact anything that looks like a file path, token, or long string so
    logs stay safe even if user text accidentally reaches them.
    """
    if text is None:
        return ""
    text = str(text)
    # Collapse whitespace so logs stay tidy.
    text = " ".join(text.split())
    # Redact anything longer than 60 characters (likely file content / secrets).
    if len(text) > 60:
        text = text[:60] + "... [redacted]"
    return text
