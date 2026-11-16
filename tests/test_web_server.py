"""
Tests for web/server.py - the local web interface.

Nothing here needs a microphone, speakers, the internet, or Ollama. Ollama and
the temperature sensor are mocked, and every server runs on a free port in a
background thread, so the whole file finishes in a couple of seconds.
"""

from __future__ import annotations

import http.client
import json
import threading
import time

import pytest

import config
from modules import command_router, security
from web import server as web_server


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
@pytest.fixture
def live_server(monkeypatch):
    """A real server on port 0 (free port), running in a daemon thread."""
    original_confirm = security.confirm_action
    monkeypatch.setattr(
        web_server.ai_engine,
        "ping",
        lambda timeout=2: (True, "Ollama is ready (test)."),
    )
    monkeypatch.setattr(web_server.sysinfo, "temperature", lambda: None)

    srv = web_server.make_server(port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)
        security.confirm_action = original_confirm  # type: ignore[assignment]


def request(server, method, path, body=None, headers=None):
    """Send one raw request: returns (status, response_headers, parsed_body).

    Raw http.client is used on purpose so a path like /..%2fconfig.py reaches
    the server exactly as written (urllib would normalise it first).
    """
    host, port = server.server_address[:2]
    conn = http.client.HTTPConnection(host, port, timeout=5)
    payload = None if body is None else json.dumps(body).encode("utf-8")
    send_headers = dict(headers or {})
    if payload is not None:
        send_headers.setdefault("Content-Type", "application/json")
        send_headers["Content-Length"] = str(len(payload))
    try:
        conn.request(method, path, body=payload, headers=send_headers)
        response = conn.getresponse()
        status = response.status
        response_headers = dict(response.getheaders())
        raw = response.read()
    finally:
        conn.close()

    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        parsed = raw
    return status, response_headers, parsed


CLIENT_HEADER = {"X-Jarvis-Client": "1"}


# ---------------------------------------------------------------------------
# GET /api/system - real numbers, honest None values
# ---------------------------------------------------------------------------
def test_system_endpoint_returns_the_expected_shape(live_server):
    status, headers, data = request(live_server, "GET", "/api/system")

    assert status == 200
    assert headers["Content-Type"].startswith("application/json")
    assert data["ok"] is True
    for key in ("time", "date", "cpu", "ram", "storage", "temperature", "ollama", "host", "network"):
        assert key in data

    # CPU is either a real percentage or None - never a made-up number.
    assert data["cpu"] is None or 0.0 <= data["cpu"] <= 100.0
    # The fixture stubs temperature out, mirroring PCs without a sensor.
    assert data["temperature"] is None
    assert data["network"] == {"internet": None, "mode": "local only"}
    assert data["ollama"]["reachable"] is True
    assert data["host"]["hostname"]


def test_system_values_are_cached_for_a_moment(live_server):
    first = request(live_server, "GET", "/api/system")[2]
    second = request(live_server, "GET", "/api/system")[2]
    # The Ollama check is cached, so the model report is identical.
    assert first["ollama"] == second["ollama"]


# ---------------------------------------------------------------------------
# GET /api/info
# ---------------------------------------------------------------------------
def test_info_endpoint_describes_the_configuration(live_server):
    status, _, data = request(live_server, "GET", "/api/info")

    assert status == 200
    assert data["name"] == config.ASSISTANT_NAME
    assert data["model"] == config.OLLAMA_MODEL
    assert data["ollama_url"] == config.OLLAMA_URL
    assert data["wake_word"] == config.WAKE_WORD
    assert isinstance(data["apps"], list)
    assert isinstance(data["approved_directories"], list)
    assert isinstance(data["generated_code"], list)


# ---------------------------------------------------------------------------
# POST /api/command
# ---------------------------------------------------------------------------
def test_command_runs_through_the_existing_router(live_server, monkeypatch):
    calls = []

    def fake_route(text, history=None):
        calls.append((text, history))
        return command_router.Response(
            "It is a test.",
            source="rule",
            history=[{"role": "user", "content": text}],
        )

    monkeypatch.setattr(web_server.command_router, "route", fake_route)

    status, _, data = request(
        live_server,
        "POST",
        "/api/command",
        {"text": "what is the time"},
        CLIENT_HEADER,
    )

    assert status == 200
    assert data == {
        "ok": True,
        "answer": "It is a test.",
        "source": "rule",
        "exit": False,
        "state": "ready",
    }
    assert calls[0][0] == "what is the time"
    # The reply's history is remembered for the next command.
    assert live_server.backend.history == [{"role": "user", "content": "what is the time"}]


def test_command_works_without_the_client_header_is_refused(live_server):
    status, _, data = request(live_server, "POST", "/api/command", {"text": "hello"})

    assert status == 403
    assert data["ok"] is False


def test_command_rejects_empty_text(live_server):
    status, _, data = request(live_server, "POST", "/api/command", {"text": "   "}, CLIENT_HEADER)

    assert status == 400
    assert data["ok"] is False


# ---------------------------------------------------------------------------
# Static files and path safety
# ---------------------------------------------------------------------------
def test_index_page_is_served(live_server):
    status, headers, body = request(live_server, "GET", "/")

    assert status == 200
    assert headers["Content-Type"].startswith("text/html")
    assert b"J.A.R.V.I.S" in body


def test_unknown_api_endpoint_is_a_404(live_server):
    status, _, data = request(live_server, "GET", "/api/does-not-exist")

    assert status == 404
    assert data["ok"] is False


def test_path_traversal_is_blocked(live_server):
    # %2f keeps the ../ intact until the server decodes it.
    status, _, data = request(live_server, "GET", "/..%2fconfig.py")

    assert status == 404
    assert data["ok"] is False


def test_missing_static_file_is_a_404(live_server):
    status, _, _ = request(live_server, "GET", "/nope.js")

    assert status == 404


# ---------------------------------------------------------------------------
# Confirmation gate (the browser Yes/No dialog)
# ---------------------------------------------------------------------------
def test_gate_without_an_answer_times_out_as_no():
    gate = web_server.ConfirmationGate(timeout=0.15)

    started = time.monotonic()
    assert gate.ask("Delete a file", "notes.txt") is False
    assert time.monotonic() - started >= 0.1
    assert gate.pending() is None


def test_gate_returns_true_after_the_user_says_yes():
    gate = web_server.ConfirmationGate(timeout=5.0)
    results = []

    worker = threading.Thread(target=lambda: results.append(gate.ask("Save code", "add.py")))
    worker.start()
    try:
        deadline = time.monotonic() + 3
        while gate.pending() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert gate.pending() == {"action": "Save code", "detail": "add.py"}
        assert gate.answer(True) is True
    finally:
        worker.join(timeout=5)

    assert results == [True]


def test_gate_ignores_an_answer_when_nothing_is_asked():
    gate = web_server.ConfirmationGate(timeout=0.1)

    assert gate.answer(True) is False


def test_confirmation_endpoint_answers_the_waiting_question(live_server):
    results = []
    worker = threading.Thread(
        target=lambda: results.append(live_server.gate.ask("Open notepad", "notepad.exe"))
    )
    worker.start()
    try:
        deadline = time.monotonic() + 3
        pending = None
        while pending is None and time.monotonic() < deadline:
            pending = request(live_server, "GET", "/api/pending")[2]["pending"]
            time.sleep(0.01)
        assert pending == {"action": "Open notepad", "detail": "notepad.exe"}

        status, _, data = request(live_server, "POST", "/api/confirm", {"yes": True}, CLIENT_HEADER)
        assert status == 200
        assert data == {"ok": True, "answered": True}
    finally:
        worker.join(timeout=5)

    assert results == [True]

    # A second answer has nothing to answer.
    status, _, data = request(live_server, "POST", "/api/confirm", {"yes": True}, CLIENT_HEADER)
    assert status == 409
    assert data["ok"] is False


# ---------------------------------------------------------------------------
# Safety wiring
# ---------------------------------------------------------------------------
def test_server_refuses_to_listen_on_the_network():
    with pytest.raises(ValueError, match="only listens on this PC"):
        web_server.make_server(host="0.0.0.0", port=0)


def test_server_routes_confirmations_to_the_browser(live_server):
    # make_server must replace security.confirm_action, or a risky action would
    # fall back to input() in a hidden terminal.
    assert security.confirm_action.__self__ is live_server.gate
