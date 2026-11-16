# TESTING.md - How to test JARVIS

JARVIS uses **pytest**. All tests run offline - they mock Ollama, the microphone,
and the TTS engine, so you never need a microphone, speakers, or internet to run
the test suite.

## 1. Run the full test suite

```cmd
.venv\Scripts\activate
pytest
```

Expected result: all tests pass (about 130). One test is skipped on Windows
(symlink creation requires admin privileges).

## 2. Test files and what they cover

| Test file | What it tests | Needs mic? | Needs Ollama? |
|---|---|---|---|
| `tests\test_command_router.py` | Rule-based commands (time, date, greetings, exit, help), AI fallback with mocked Ollama, error handling, input length limit | No | No (mocked) |
| `tests\test_ai_engine.py` | Ollama chat, ping, list_models; friendly errors for connection, timeout, 404, bad JSON, empty answer | No | No (mocked) |
| `tests\test_voice.py` | Wake-word detection, command extraction, friendly mic/model errors, listener loop with fake audio | No | No |
| `tests\test_security.py` | Approved-directory checks, `..` and symlink escape blocking, confirm yes/no, redaction | No | No |
| `tests\test_computer_control.py` | Allowlisted app launch (no shell=True), script run with timeout, path validation, open file | No | No |
| `tests\test_coding_assistant.py` | Coding Q&A via mocked Ollama, save code snippet with confirmation, path traversal blocking, reading a file for review, size limit | No | No |
| `tests\test_main.py` | Command-line flags and the `--doctor` checks (all mocked) | No | No |
| `tests\test_web_server.py` | Web server: JSON endpoints, 403 without the client header, path-traversal blocking, confirmation gate (yes/no/timeout), loopback-only refusal | No | No (mocked) |

## 3. Manual smoke tests (text mode)

These work without a microphone or Ollama for rule-based commands:

```cmd
.venv\Scripts\activate
python main.py --text --no-voice
```

Try these commands:

| You type | Expected |
|---|---|
| `hello` | "Hello. JARVIS at your service..." |
| `what is the time` | "It is HH:MM PM." |
| `what is today` | "Today is Friday, 23 October 2026." |
| `who are you` | "I am JARVIS, your local assistant..." |
| `help` | Lists examples and exit words |
| `thank you` | "You are welcome." |
| `exit` or `goodbye jarvis` | "Goodbye. Shutting down JARVIS." |
| `x` repeated 600 times | "Your message is too long..." |

Coding assistant (needs Ollama):

| You type | Expected |
|---|---|
| `what is a python function` | a short explanation + an example |
| `write a function that adds two numbers` | a snippet |
| `save that as add.py` | `CONFIRM: save code (add.py)` - type `yes` |
| `list my code` | "Saved code: add.py." |
| `review add.py` | a short review of the saved file |

To test the AI fallback, you need Ollama running with a model:

```cmd
ollama serve
ollama pull llama3.2:3b
python main.py --text --no-voice
You: what is the capital of France?
```

## 4. Manual voice test (needs microphone)

```cmd
.venv\Scripts\activate
python main.py --list-devices
```

Pick your microphone number, then:

```cmd
python main.py --device 1
```

Say "hey jarvis" followed by a command (for example "what is the time").
JARVIS replies by voice and text. Say "stop listening" or "goodbye jarvis" to exit.

If the microphone doesn't work, JARVIS falls back to text mode automatically.

Use `python main.py --mic-test` for a 15-second live mic level display to
troubleshoot microphone issues.

## 5. Manual web interface test (browser)

The HUD is a local page served by Python on `127.0.0.1` only. Nothing extra to
install.

```cmd
.venv\Scripts\activate
python main.py --web
```

Open every sidebar item and check:

- [ ] **Dashboard** - rings rotate, the core pulses, status reads `READY FOR COMMAND`
- [ ] **AI Assistant** - typing `hello` adds a YOU line and a JARVIS reply
- [ ] **Voice Control** - engine/status text is truthful; "Listen once" asks for mic permission
- [ ] **System Monitor** - CPU, RAM and storage roughly match Task Manager; CPU TEMP hidden if no sensor
- [ ] **Applications** - cards appear only for allowlisted apps; clicking one opens the Yes/No dialog
- [ ] **Settings** - shows your model, Ollama URL and approved folders
- [ ] The clock in the top bar ticks every second
- [ ] `SYSTEM ONLINE` turns amber if you stop Ollama
- [ ] Typing `what is the time` answers even with Ollama off
- [ ] Closing the Python window (or Ctrl+C) stops the page; a reload then fails
- [ ] No red errors in the browser console (F12)

Risky command check: type `open notepad`, answer **No** first (nothing should
open), then repeat and answer **Yes** (Notepad opens). Leave the dialog alone
for 60 seconds and it closes itself with **no** action taken.

Speech check (needs a mic): press the mic button, say "what is the time", and
let the browser fill the box. If your browser has no speech recognition, the
page says so and typing still works.

**Privacy note:** Chrome and Edge speech recognition may send audio to their
cloud service. Typing is local; `python main.py` uses offline Vosk.

## 6. Test what to check before declaring done

- [ ] `pytest` passes (all green)
- [ ] `python main.py --text --no-voice` answers rule commands correctly
- [ ] `python main.py --list-devices` lists your microphone(s)
- [ ] `python main.py --mic-test` shows the level bar moving when you speak
- [ ] Voice mode answers a command end-to-end (needs mic + speakers)
- [ ] With Ollama running, `python main.py --text` answers an open question
- [ ] `save that as add.py` -> `yes` writes `generated_code\add.py`
- [ ] `review add.py` gives a sensible review
- [ ] `python main.py --doctor` shows no `[FAIL]` lines
- [ ] `python main.py --web` serves `http://127.0.0.1:8765/` and every sidebar view works
- [ ] The browser Yes/No dialog blocks `open notepad` until Yes; No or a timeout does nothing
- [ ] System tiles are close to Task Manager, and a missing CPU temperature hides the tile

## 7. Troubleshooting

| Problem | Fix |
|---|---|
| `pytest` not found | `.venv\Scripts\python.exe -m pip install pytest` |
| `Ollama: not running` | Run `ollama serve` (or start the Ollama app). Rule commands still work. |
| `The model 'X' is not installed` | Run `ollama pull X` (try `llama3.2:1b` for low RAM). |
| No microphone detected | Run `python main.py --list-devices`, then `--device N`; or use `--text`. |
| Speech is off / no sound | Add `--no-voice`; check Windows volume and default output device. |
| Setup failed in run_jarvis.bat | Run `.venv\Scripts\python.exe -m pip install -r requirements.txt` manually. |
| Port 8765 is already in use | Run `python main.py --web --port 8766`. |
| Web page says `SERVER OFFLINE` | The Python window was closed. Start it again: `python main.py --web`. |
| Microphone blocked in the page | Click the padlock icon in the address bar, allow the microphone, reload. |
| Browser has no speech recognition | Use Edge or Chrome, or type; offline Vosk is `python main.py`. |
| CPU TEMP card is missing | This PC exposes no temperature sensor. Expected - the tile hides itself. |

Logs are written to `logs\jarvis.log` (actions and errors only - never your
typed messages or audio).
