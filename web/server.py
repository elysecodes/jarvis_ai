"""
server.py - the local web interface for JARVIS.

A tiny HTTP server from the standard library (no Flask, nothing to install)
bound to 127.0.0.1 only, so nothing is reachable from the network.

The browser talks to it with JSON:

    GET  /api/system     real CPU / RAM / storage / Ollama state
    GET  /api/info       the settings worth showing (model, apps, folders)
    GET  /api/pending    a confirmation waiting for the user, if any
    POST /api/command    {"text": "hello"} -> JARVIS answer
    POST /api/confirm    {"yes": true}     -> answer a confirmation

The UI is fully separate from the AI: this file only calls command_router, and
command_router only calls the existing modules. Every safety rule still applies,
and a risky action asks the browser for a real Yes/No. Nobody answers in time ->
the answer is No.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import threading
import time
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import config
from modules import ai_engine, command_router, computer_control, security
from web import sysinfo

logger = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_DIR / "static"
DEFAULT_PORT = 8765
DEFAULT_HOST = "127.0.0.1"  # loopback only: the network can never reach JARVIS

# POST requests must carry this header. A random web page cannot add custom
# headers to a cross-origin request without a preflight, which we never allow,
# so this blocks drive-by requests from other sites.
CLIENT_HEADER = "X-Jarvis-Client"


# ---------------------------------------------------------------------------
# Confirmations: a risky action blocks until the browser answers
# ---------------------------------------------------------------------------
class ConfirmationGate:
    """Bridges security.confirm_action() to the browser's Yes/No dialog."""

    def __init__(self, timeout: float = 60.0):
        self.timeout = timeout
        self._event = threading.Event()
        self._answer = False
        self._pending: dict | None = None
        self._lock = threading.Lock()

    def ask(self, action: str, detail: str = "") -> bool:
        """Called from the command thread. Waits for the browser's answer."""
        with self._lock:
            self._pending = {"action": str(action), "detail": str(detail)}
            self._answer = False
            self._event.clear()

        answered = self._event.wait(self.timeout)

        with self._lock:
            self._pending = None
            answer = self._answer if answered else False

        if not answered:
            logger.info("Confirmation timed out; treated as No")
        return answer

    def pending(self) -> dict | None:
        with self._lock:
            return dict(self._pending) if self._pending else None

    def answer(self, yes: bool) -> bool:
        """Answer the waiting question. Returns False if nothing was pending."""
        with self._lock:
            if self._pending is None:
                return False
            self._answer = bool(yes)
        self._event.set()
        return True


# ---------------------------------------------------------------------------
# Cached system snapshot (so a fast browser cannot hammer the Windows API)
# ---------------------------------------------------------------------------
class SystemMonitor:
    def __init__(self, ollama_ttl: float = 5.0, temperature_ttl: float = 120.0):
        self.cpu = sysinfo.CpuSampler()
        self.ollama_ttl = ollama_ttl
        self.temperature_ttl = temperature_ttl
        self._ollama_cache: tuple[float, dict] | None = None
        self._temperature_cache: tuple[float, float | None] | None = None

    def _ollama_state(self) -> dict:
        now = time.monotonic()
        if self._ollama_cache and now - self._ollama_cache[0] < self.ollama_ttl:
            return self._ollama_cache[1]
        ok, message = ai_engine.ping(timeout=2)
        state = {"reachable": ok, "message": message, "model": config.OLLAMA_MODEL}
        self._ollama_cache = (now, state)
        return state

    def _temperature(self) -> float | None:
        now = time.monotonic()
        if self._temperature_cache and now - self._temperature_cache[0] < self.temperature_ttl:
            return self._temperature_cache[1]
        # PowerShell start-up is slow, so ask at most once every couple of minutes.
        value = sysinfo.temperature()
        self._temperature_cache = (now, value)
        return value

    def snapshot(self) -> dict:
        return {
            "time": time.strftime("%H:%M:%S"),
            "date": time.strftime("%A, %d %B %Y"),
            "cpu": self.cpu.sample(),
            "ram": sysinfo.memory(),
            "storage": sysinfo.storage(),
            "temperature": self._temperature(),
            "ollama": self._ollama_state(),
            "host": sysinfo.host(),
            # JARVIS never phones home, so we do not claim to know about the
            # internet. The tile says "local only" instead.
            "network": {"internet": None, "mode": "local only"},
        }


# ---------------------------------------------------------------------------
# A tiny request router
# ---------------------------------------------------------------------------
class JarvisRequestHandler(BaseHTTPRequestHandler):
    server_version = "JarvisHTTP/1.0"
    protocol_version = "HTTP/1.1"

    # -- plumbing -----------------------------------------------------------
    def log_message(self, fmt: str, *args) -> None:  # noqa: D401 - quiet by default
        logger.debug("%s - %s", self.address_string(), fmt % args)

    def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"ok": False, "error": message})

    def _read_json(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None
        if length <= 0 or length > 100_000:
            return None
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        return data if isinstance(data, dict) else None

    # -- routes -------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 - name required by http.server
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/system":
            return self._json(HTTPStatus.OK, {"ok": True, **self.server.monitor.snapshot()})
        if path == "/api/info":
            return self._json(HTTPStatus.OK, {"ok": True, **self._info()})
        if path == "/api/pending":
            return self._json(
                HTTPStatus.OK, {"ok": True, "pending": self.server.gate.pending()}
            )
        if path.startswith("/api/"):
            return self._error(HTTPStatus.NOT_FOUND, "Unknown API endpoint.")
        return self._serve_static(path)

    do_HEAD = do_GET

    def do_POST(self) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        if self.headers.get(CLIENT_HEADER) != "1":
            return self._error(HTTPStatus.FORBIDDEN, "Missing client header.")

        if path == "/api/command":
            data = self._read_json()
            if data is None or not str(data.get("text", "")).strip():
                return self._error(HTTPStatus.BAD_REQUEST, "Send {\"text\": \"...\"}.")
            return self._json(HTTPStatus.OK, self.server.backend.handle_command(str(data["text"])))

        if path == "/api/confirm":
            data = self._read_json() or {}
            accepted = self.server.gate.answer(bool(data.get("yes")))
            if not accepted:
                return self._error(HTTPStatus.CONFLICT, "Nothing is waiting for an answer.")
            return self._json(HTTPStatus.OK, {"ok": True, "answered": bool(data.get("yes"))})

        return self._error(HTTPStatus.NOT_FOUND, "Unknown API endpoint.")

    # -- helpers ------------------------------------------------------------
    def _info(self) -> dict:
        return {
            "name": config.ASSISTANT_NAME,
            "model": config.OLLAMA_MODEL,
            "ollama_url": config.OLLAMA_URL,
            "wake_word": config.WAKE_WORD,
            "tts_enabled": config.ENABLE_TTS,
            "apps": computer_control.list_allowed_apps(),
            "approved_directories": list(config.APPROVED_DIRECTORIES),
            "generated_code": [p.name for p in _safe_list(config.GENERATED_CODE_DIR)],
        }

    def _serve_static(self, path: str) -> None:
        relative = urllib.parse.unquote(path.lstrip("/")) or "index.html"
        if relative.endswith("/"):
            relative += "index.html"

        try:
            target = (STATIC_DIR / relative).resolve()
            target.relative_to(STATIC_DIR.resolve())  # blocks ../ escapes
        except (ValueError, OSError):
            return self._error(HTTPStatus.NOT_FOUND, "Not found.")

        if not target.is_file():
            return self._error(HTTPStatus.NOT_FOUND, "Not found.")

        content_type, _ = mimetypes.guess_type(str(target))
        if content_type is None:
            content_type = "application/octet-stream"
        if content_type.startswith("text/") or content_type in {
            "application/javascript",
            "application/json",
        }:
            content_type += "; charset=utf-8"

        try:
            body = target.read_bytes()
        except OSError:
            return self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "Could not read the file.")
        return self._send(HTTPStatus.OK, body, content_type)


def _safe_list(folder: Path) -> list[Path]:
    try:
        return sorted(p for p in folder.iterdir() if p.is_file())
    except OSError:
        return []


# ---------------------------------------------------------------------------
# The backend the UI talks to (kept separate from HTTP on purpose)
# ---------------------------------------------------------------------------
class JarvisBackend:
    """Runs commands through the existing router, one at a time."""

    def __init__(self):
        self.history: list[dict] = []
        self._lock = threading.Lock()

    def handle_command(self, text: str) -> dict:
        with self._lock:  # one command at a time keeps the history consistent
            response = command_router.route(text, list(self.history))
            if response.history:
                self.history = response.history
            return {
                "ok": True,
                "answer": response.text,
                "source": response.source,
                "exit": response.exit,
                "state": "ready",
            }


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------
class JarvisServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, backend: JarvisBackend, gate: ConfirmationGate, monitor: SystemMonitor):
        super().__init__(address, JarvisRequestHandler)
        self.backend = backend
        self.gate = gate
        self.monitor = monitor


def make_server(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    confirm_timeout: float = 60.0,
) -> JarvisServer:
    """Create the server (does not start it). Tests use port=0."""
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(
            "JARVIS only listens on this PC (127.0.0.1). Refusing to open it to the network."
        )
    gate = ConfirmationGate(timeout=confirm_timeout)
    server = JarvisServer((host, port), JarvisBackend(), gate, SystemMonitor())
    # Risky actions now ask the browser instead of the terminal.
    security.confirm_action = gate.ask  # type: ignore[assignment]
    return server


def serve(port: int = DEFAULT_PORT, open_browser: bool = True, host: str = DEFAULT_HOST) -> int:
    """Run the interface until Ctrl+C. Returns a process exit code."""
    server = make_server(host=host, port=port)
    url = f"http://{host}:{server.server_address[1]}/"

    print(f"[{config.ASSISTANT_NAME}] Interface: {url}")
    print("  This is a local page - it is not on the internet.")
    print("  Press Ctrl+C in this window to stop it.")

    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print(f"\n[{config.ASSISTANT_NAME}] Interface stopped.")
    finally:
        server.shutdown()
        server.server_close()
    return 0
