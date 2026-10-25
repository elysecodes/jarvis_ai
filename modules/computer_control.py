"""
computer_control.py - safe, allowlisted PC actions (Phase 3).

Safety rules from AGENTS.md:
  * Never run AI-generated shell commands. Code only *requests* an action from a
    fixed allowlist of named actions; it validates and executes it.
  * Never use shell=True. Use subprocess.run([...list...]) or os.startfile.
  * Apps: allowlist dict (name -> executable), e.g. notepad, calc, cmd, code.
  * Python scripts: only from an approved scripts folder, run with a timeout,
    output captured.
  * Confirmation required before running scripts or changing settings.

The router calls these functions by name. The AI never supplies a command
string - it can only pick from the allowlist below.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

import config
from modules import security

logger = logging.getLogger(__name__)

# Allowlist of apps JARVIS may launch. name -> executable (no shell args).
ALLOWED_APPS: dict[str, str] = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "command prompt": "cmd.exe",
    "cmd": "cmd.exe",
    "vscode": "code.exe",
    "code": "code.exe",
}

# Folder where approved Python scripts may live (set via config.json).
SCRIPTS_DIR = config.BASE_DIR / "scripts"


class ControlError(Exception):
    """Raised when a computer-control action is blocked or fails."""


def list_allowed_apps() -> list[str]:
    """Return the names of apps JARVIS is allowed to launch."""
    return sorted(ALLOWED_APPS.keys())


def launch_app(app_name: str, confirm: bool = True) -> str:
    """Launch an allowlisted app.

    `confirm` controls whether the user is asked for yes/no first. Returns a
    human-readable result message. Never uses shell=True.
    """
    key = app_name.strip().lower()
    if key not in ALLOWED_APPS:
        available = ", ".join(list_allowed_apps())
        raise ControlError(
            f"I don't know the app '{app_name}'. Allowed apps: {available}."
        )

    executable = ALLOWED_APPS[key]

    if confirm and security.requires_confirmation("launch_app"):
        if not security.confirm_action("launch app", app_name):
            return f"Cancelled: not launching {app_name}."

    try:
        # os.startfile is the safest way on Windows - no shell, no args.
        os.startfile(executable)
        logger.info("Launched app: %s (%s)", app_name, executable)
        return f"Launched {app_name}."
    except OSError as exc:
        logger.warning("Could not launch %s: %s", app_name, exc.__class__.__name__)
        return f"Could not launch {app_name}: {exc}."


def run_script(script_name: str, args: list[str] | None = None, confirm: bool = True) -> str:
    """Run an approved Python script from the scripts folder.

    The script must live inside the configured scripts directory. Runs with a
    timeout and captures output. Never uses shell=True.
    """
    args = args or []

    if confirm and security.requires_confirmation("run_script"):
        if not security.confirm_action("run script", script_name):
            return f"Cancelled: not running {script_name}."

    if Path(script_name).suffix.lower() != ".py":
        return f"Only Python scripts (.py) are allowed, not {script_name}."

    try:
        script_path = security.validate_file_path(
            SCRIPTS_DIR / script_name, must_exist=True
        )
    except security.SecurityError as exc:
        return str(exc)

    cmd = ["python", str(script_path)] + [str(a) for a in args]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.warning("Script timed out: %s", script_name)
        return f"Script {script_name} timed out after 30 seconds."
    except OSError as exc:
        logger.warning("Could not run script %s: %s", script_name, exc.__class__.__name__)
        return f"Could not run {script_name}: {exc}."

    output = result.stdout.strip()
    if result.returncode != 0:
        err = result.stderr.strip() or f"exit code {result.returncode}"
        logger.warning("Script %s failed: %s", script_name, err)
        return f"Script {script_name} failed: {err}."

    logger.info("Ran script: %s", script_name)
    return output or f"Script {script_name} ran successfully (no output)."


def open_file(file_path: str, confirm: bool = True) -> str:
    """Open a file with its default Windows app, if inside an approved directory.

    Uses os.startfile (no shell). Requires confirmation.
    """
    if confirm and security.requires_confirmation("open_file"):
        if not security.confirm_action("open file", file_path):
            return f"Cancelled: not opening {file_path}."

    try:
        resolved = security.validate_file_path(file_path, must_exist=True)
    except security.SecurityError as exc:
        return str(exc)

    try:
        os.startfile(str(resolved))
        logger.info("Opened file: %s", resolved)
        return f"Opened {resolved.name}."
    except OSError as exc:
        logger.warning("Could not open %s: %s", resolved, exc.__class__.__name__)
        return f"Could not open {resolved.name}: {exc}."
