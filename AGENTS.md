# JARVIS AI: project rules

## About the user
- Beginner programmer on Windows 11. Explain things simply. Keep code clean, commented, and readable.
- Give run commands in Windows CMD syntax (not PowerShell, not Bash).

## Project
Local, privacy-first voice assistant in Python called JARVIS. Controls the Windows PC safely and helps with coding using a local Ollama model. No paid APIs, no API keys.

## Tech choices (fixed unless I approve a change)
- Python 3.10+ in a venv at `.venv`
- LLM: Ollama at http://localhost:11434 via `requests` (model name in config, default chosen by RAM, see below)
- Speech-to-text: offline Vosk (small English model) via `sounddevice`. Avoid PyAudio (hard to install on Windows). Make the STT engine swappable behind one interface.
- Text-to-speech: pyttsx3 (offline, Windows SAPI5)
- Config: `config.py` reading environment variables with defaults, plus optional `config.json`
- Tests: pytest
- Keep dependencies minimal. Ask before adding any library.

## Structure
jarvis-ai/
  main.py, config.py, requirements.txt, README.md, AGENTS.md
  modules/ (__init__, voice.py, speech.py, ai_engine.py, computer_control.py,
            coding_assistant.py, command_router.py, security.py)
  tests/
  logs/
  generated_code/

## Safety rules (non-negotiable)
- Never run AI-generated shell commands. The LLM may only *request* an action from a fixed allowlist of named actions; code validates and executes it.
- Never use `shell=True`. Use `subprocess.run([...list...])` or `os.startfile`.
- Apps: allowlist dict (name -> executable), e.g. notepad, calc, cmd, code.
- File access: resolve paths with `Path.resolve()` and require they sit inside approved directories listed in config. Block `..` tricks and symlink escapes.
- Confirmation required (typed or spoken yes/no) before: deleting, overwriting, moving files, saving generated code, running scripts, installing anything, changing settings.
- Python scripts: only from an approved scripts folder, run with a timeout, output captured.
- Logs must never contain passwords, keys, file contents, or raw audio. Log actions and errors only.
- Audio is processed locally and never saved to disk or sent anywhere. Say so in the README.

## Reliability rules
- Every external dependency (mic, Ollama, model, Vosk model, TTS) must fail with a clear, friendly message, never a traceback.
- Always provide a **text mode** (`python main.py --text`) so everything can be tested without a microphone.
- LLM calls need timeouts and a "Ollama not running / model missing" path that tells the user the exact command to fix it.

## Working rules for the agent
- Work in small phases. Finish and test one phase before starting the next.
- After writing code, run it: import checks, `pytest`, and `python main.py --text` smoke tests. Fix errors before moving on.
- Report honestly: mark each feature as **Tested by me**, **Needs manual test (mic/speakers)**, or **Not done**. Never claim something works if you did not run it.
- Before running any command that downloads something large or installs software, tell me the size and wait for approval.
- Do not leave stubs or fake implementations for core features.
- Keep README.md updated with exact CMD setup and troubleshooting steps.
