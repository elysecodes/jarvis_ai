# JARVIS

A local, privacy-first voice assistant for Windows 11. It talks to a local
Ollama model for answers and controls a few safe things on your PC.
No paid APIs, no API keys, no cloud.

**Privacy:** everything runs on your own computer. Speech recognition (Phase 2)
works offline with Vosk. Audio is processed in memory and is never saved to disk
or sent anywhere. The optional browser interface (`--web`) listens on
`127.0.0.1` only, so nothing is reachable from the network. Its microphone
button uses the browser's speech recognition, and Chrome/Edge may send that
audio to their own cloud service - typing in the page is fully local. The only
part that will ever need the internet is opening a website or doing a web
search, and JARVIS will tell you when it does.

---

## What works right now

- **Voice mode** (default): say `hey jarvis` (or just `jarvis`), then your command
- **Text mode**: `python main.py --text` - works without a microphone
- `--doctor` checks everything in one go (Ollama, model, mic, speech model, TTS)
- **Holographic web interface**: `python main.py --web` opens a local
  Iron-Man-style HUD at `http://127.0.0.1:8765/`. Six working sections, live
  CPU/RAM/storage readings, a chat log, a click-to-launch app grid, and a
  browser Yes/No dialog for every risky action. It is a local page, not a
  website.
- Offline speech recognition with Vosk (no cloud, no API keys)
- Rule-based commands that always work, even if Ollama is off:
  - time, date, greetings, help, "who are you", thanks
  - exit with `exit`, `quit`, `bye`, `goodbye`, `goodbye jarvis`, `shutdown`,
    `stop`, `stop listening`
- Safe PC actions, from a fixed allowlist only: `open notepad`, `open calculator`,
  `open cmd`, `open code`, and "what apps can you open" - JARVIS asks for a
  typed `yes` first. It never builds or runs shell commands.
- Coding assistant (same local model, programming prompt):
  - ask coding questions: "what is a python function?"
  - "save that as hello.py" saves the last answer into `generated_code\`
    (asks for a typed `yes` first)
  - "list my code" shows what is saved
  - "review hello.py" reads a saved file and reviews it (folders must be approved)
- AI chat through your local Ollama model for anything else
- Text-to-speech replies with pyttsx3 (Windows SAPI5) - turn off with `--no-voice`
- `--list-devices` to see your microphones, `--device N` to pick one
- Friendly messages (never a traceback) when Ollama is off, a model is missing,
  or the microphone cannot be opened - voice mode then falls back to typing
- Tests with pytest (129 passing, 1 skipped, no microphone needed)

---

## 1. Setup (first time only)

Open a Command Prompt (Start menu, type `cmd`) and run these inside the project
folder `C:\Users\Students\OneDrive\Documents\001\001\jarvis_ai`:

```cmd
cd /d C:\Users\Students\OneDrive\Documents\001\001\jarvis_ai
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
```

## 2. Start Ollama

Ollama must be running for AI answers:

```cmd
ollama serve
```

(or just launch the Ollama desktop app). Check your models with:

```cmd
ollama list
```

## 3. Choose a model

This PC has about 8 GB of RAM, so a small 3B model is a good fit:

```cmd
ollama pull llama3.2:3b
```

Already installed have been `llama3.2:1b` and `gemma3:4b`. To use a different
model, edit `config.json` (see below) or pass `--model`:

```cmd
python main.py --text --model llama3.2:1b
```

## 4. Download the speech model (voice mode only, one time, about 40 MB)

JARVIS listens offline with a Vosk model that lives in the `models\` folder:

```cmd
mkdir models
curl -L -o vosk-model.zip https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
tar -xf vosk-model.zip -C models
del vosk-model.zip
```

You can also open that URL in your browser and unzip it into `models\` yourself
(a download manager helps if the connection is slow). The folder must end up as:

```
models\vosk-model-small-en-us-0.15\am\ ...
```

## 5. Run JARVIS

Voice mode (say "hey jarvis ..."):

```cmd
.venv\Scripts\activate
python main.py
```

Text mode (no microphone needed):

```cmd
python main.py --text
```

Or double-click **`run_jarvis.bat`** in Explorer (voice mode), which uses the
`.venv` for you. From a Command Prompt you can also pass flags to it:

```cmd
run_jarvis.bat --text
run_jarvis.bat --doctor
```

### Running in separate windows

Ollama and JARVIS each want their own Command Prompt window, so you can see
both: Ollama prints requests, JARVIS prints the conversation.

- **Window 1 - Ollama.** Only needed if you start it by hand with `ollama serve`.
  If you use the Ollama desktop app, it already runs in the background (tray)
  and you can skip this window.
- **Window 2 - JARVIS.** `run_jarvis.bat` (or `python main.py`).

To open both from one window, use `start`:

```cmd
start "Ollama" cmd /k ollama serve
start "JARVIS" cmd /k run_jarvis.bat
```

Close a window (or press Ctrl+C in it) to stop that program. Closing the JARVIS
window stops the assistant; Ollama keeps running until you close its window too.

Then type to chat, for example:

```
You: hello
You: what is the time
You: open notepad
You: explain what a Python list is
You: goodbye jarvis
```

Flags:

| Flag | Meaning |
|---|---|
| `--text` | use the keyboard instead of a microphone |
| `--no-voice` | do not speak answers out loud |
| `--model NAME` | use a different Ollama model for this run |
| `--doctor` | check Ollama, the model, your mic, the speech model and TTS, then exit |
| `--web` | open the futuristic HUD in your browser (local only) |
| `--port N` | port for `--web` (default `8765`) |
| `--no-browser` | with `--web`, do not open the browser automatically |
| `--list-devices` | list your microphones and exit |
| `--device N` | use microphone number N (from `--list-devices`), or part of its name |
| `--mic-test` | show live mic level and recognised words for 15 seconds |
| `--debug-voice` | in voice mode, print the mic level and every word heard |

---

## The futuristic interface (`--web`)

```cmd
.venv\Scripts\activate
python main.py --web
```

Your browser opens `http://127.0.0.1:8765/`. The Python window must stay open:
it *is* the server. Press **Ctrl+C** in that window to stop it (closing only the
tab leaves the server running).

Useful variants:

```cmd
python main.py --web --port 8800
python main.py --web --no-browser
```

| Section | What it shows / does |
|---|---|
| Dashboard | animated holographic core, assistant state, model, mic, exchange count |
| AI Assistant | the full transcript, with a badge showing whether a rule, the local model or a coding answer replied |
| Voice Control | mic status, live input meter, "Listen once" and wake-word buttons, spoken-reply switch |
| System Monitor | real CPU, RAM and storage graphs; CPU temperature only if Windows exposes a sensor |
| Applications | the allowlisted programs only - clicking one asks for confirmation first |
| Settings | read-only view of the model, Ollama URL and approved folders, plus a re-check button |

Honest limits, also stated inside the page:

- **Network** says "local only". JARVIS does not ping the internet, so it never
  pretends to know your connection speed.
- **CPU TEMP** is hidden when the motherboard does not publish a sensor. That is
  normal on many PCs, including this one.
- **Microphone** uses the browser's speech recognition. Chrome and Edge may send
  that audio to their own cloud service; the page says so. Typing is fully
  local, and `python main.py` (without `--web`) uses offline Vosk.
- **Confirmations** appear as a Yes/No dialog in the page. If nobody answers
  within 60 seconds, the answer is **No**.
- Every risky action still goes through the same Python allowlist and
  `security.py` checks; the page cannot run arbitrary shell commands.

The page and the AI are separate: the browser only exchanges JSON with
`web\server.py`, and that server calls the existing `command_router`. No new pip
packages are needed - it is all Python's standard library.

---

## Configuration

Settings come from, in priority order: environment variables, then
`config.json`, then the defaults in `config.py`.

Create `config.json` next to `main.py` (it is ignored by git) and only put in
what you want to change:

```json
{
  "ollama_model": "llama3.2:3b",
  "ollama_url": "http://localhost:11434",
  "request_timeout": 60,
  "enable_tts": true,
  "approved_directories": ["C:/Users/Students/OneDrive/Documents/001/001/jarvis_ai/generated_code"],
  "vosk_model_path": "C:/Users/Students/OneDrive/Documents/001/001/jarvis_ai/models/vosk-model-small-en-us-0.15",
  "input_device": null,
  "wake_word": "hey jarvis",
  "command_timeout": 6,
  "wake_timeout": 0
}
```

`approved_directories` is the list of folders JARVIS may read or write. Keep it
short: this project's `generated_code` folder is already approved, so saving and
reviewing snippets works. Add another folder only when you really need it.

| Key | Meaning |
|---|---|
| `input_device` | mic number or name fragment (`null` = Windows default) |
| `wake_word` | what makes JARVIS start listening (`"jarvis"` alone always works) |
| `command_timeout` | seconds to give you to say a command after the wake word |
| `wake_timeout` | seconds to wait for the wake word before going quiet (`0` = forever) |

Environment variables (CMD example):

```cmd
set JARVIS_OLLAMA_MODEL=llama3.2:1b
set JARVIS_ENABLE_TTS=false
set JARVIS_INPUT_DEVICE=1
```

---

## Tests

```cmd
.venv\Scripts\activate
pytest
```

The tests do not need Ollama, the internet, or a microphone; HTTP calls are
mocked.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Not sure what is broken | Run `python main.py --doctor` - it checks Ollama, the model, your mic, the speech model and TTS in one go. |
| `I cannot reach Ollama` | Start it: `ollama serve` (or open the Ollama app). Rule-based commands still work. |
| `The model 'X' is not installed` | Run `ollama pull X`, or set a model you have: `ollama list`. |
| `Ollama took longer than 60 seconds` | Use a smaller model (`llama3.2:1b`) or raise `request_timeout` in `config.json`. |
| `offline speech model was not found` | Unzip the Vosk model into `models\` (step 4 above). |
| `save that as x.py` says "not an approved directory" | Add the `generated_code` folder to `approved_directories` in `config.json` (the project ships it already). |
| `review x.py` cannot find the file | Save it first with "save that as x.py", or put it in `generated_code\` or `scripts\`. |
| `I could not use ... microphone` | Run `python main.py --list-devices`, then `--device N`; check Settings > Privacy > Microphone; or run `--text`. |
| Wake word never heard | Say it clearly and close to the mic: "Hey JARVIS". Try another mic with `--device N`. |
| Wrong words recognised | Normal in a noisy room; the small English model is not perfect. Text mode always works. |
| Speech is off / no sound | Check Windows volume and the default output device. Add `--no-voice` to run silently. |
| `pyttsx3 is not installed` | Run `pip install pyttsx3` inside the activated venv. |
| `python` not found | Install Python 3.10+ from python.org and tick "Add python.exe to PATH". |
| Ollama answers are slow | Only one model fits in RAM at a time here; close other apps or use a 1B model. |
| `I could not start the interface on port 8765` | Something else is using that port. Run `python main.py --web --port 8766`. |
| The page says `SERVER OFFLINE` | The Python window was closed. Start it again: `python main.py --web`. |
| Page is blank or will not load | Open `http://127.0.0.1:8765/` by hand; check the Python window for an error. |
| Mic button does nothing | Use Edge or Chrome. Firefox may not offer speech recognition - type instead, or run `python main.py` for offline Vosk. |
| `Microphone blocked` in the page | Click the padlock icon in the address bar, allow the microphone, then reload. |
| Browser speech says `network` | Chrome/Edge speech recognition needs their online service. Type instead, or use offline Vosk (`python main.py`). |
| CPU TEMP tile is missing | Windows does not expose a temperature sensor on this PC. Nothing is broken; the tile hides itself rather than inventing a number. |

Logs are written to `logs\jarvis.log`. They record actions and errors only -
never your typed messages, file contents, or audio.

---

## Project layout

```
jarvis_ai/
  main.py              entry point (voice mode + text mode)
  run_jarvis.bat       one-click start (double-click it in Explorer)
  config.py            settings + JARVIS personality prompt
  requirements.txt     Python packages
  conftest.py          helps pytest find the project
  pytest.ini           test settings
  modules\
    ai_engine.py       talks to Ollama, friendly errors
    speech.py          text-to-speech (pyttsx3)
    voice.py           wake word + offline speech recognition (Vosk)
    command_router.py  rules first, AI fallback
    security.py        path validation, confirmations, redaction (Phase 3)
    computer_control.py allowlisted app launching, script running (Phase 3)
    coding_assistant.py coding help via local Ollama model (Phase 4)
  web\
    server.py          local HTTP server + JSON API (127.0.0.1 only)
    sysinfo.py         real CPU / RAM / storage / temperature readings
    static\            index.html, styles.css, app.js - the HUD itself
  models\              offline speech model (not in git, ~40 MB)
  tests\               pytest tests
  logs\                jarvis.log
  generated_code\      saved code snippets (Phase 4)
```

## Roadmap

| Phase | Feature | Status |
|---|---|---|
| 1 | Foundation + text-mode assistant | done |
| 2 | Voice input (Vosk + sounddevice, wake word) | done - needs your mic test |
| 3 | Safe computer control (allowlisted apps, files) | done |
| 4 | Coding assistant | done |
| 5 | Hardening, `run_jarvis.bat`, TESTING.md | done |
| 6 | Holographic local web interface (`--web`) | done - needs your visual check |
