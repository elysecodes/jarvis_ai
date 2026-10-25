"""
JARVIS modules package.

Each module has one job:
  ai_engine       - talks to the local Ollama model
  speech          - speaks text out loud (pyttsx3)
  command_router  - decides what to do with what the user said
  voice           - listens with the microphone (Phase 2)
  computer_control- safe allowlisted PC actions (Phase 3)
  security        - path checks, confirmations, redaction (Phase 3)
  coding_assistant- coding help (Phase 4)
"""

__all__ = [
    "ai_engine",
    "command_router",
    "computer_control",
    "coding_assistant",
    "security",
    "speech",
    "voice",
]
