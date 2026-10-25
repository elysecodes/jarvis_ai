# JARVIS

A local, privacy-first voice assistant for Windows 11. It talks to a local
Ollama model for answers and (later) controls a few safe things on your PC.
No paid APIs, no API keys, no cloud.

**Privacy:** everything runs on your own computer. Speech recognition (Phase 2)
works offline with Vosk. Audio is processed in memory and is never saved to disk
or sent anywhere. The only part that will ever need the internet is opening a
website or doing a web search (Phase 3), and JARVIS will tell you when it does.

---

## What works right now (Phase 2)

- **Voice mode** (default): say `hey jarvis` (or just `jarvis`), then your command
- **Text mode**: `python main.py --text` - works without a microphone
- Offline speech recognition with Vosk (no cloud, no API keys)
- Rule-based commands that always work, even if Ollama is off:
  - time, date, greetings, help, "who are you", thanks
  - exit with `exit`, `quit`, `bye`, `goodbye`, `goodbye jarvis`, `shutdown`,
    `stop`, `stop listening`
- AI chat through your local Ollama model for anything else
- Text-to-speech replies with pyttsx3 (Windows SAPI5) - turn off with `--no-voice`
- `--list-devices` to see your microphones, `--device N` to pick one
- Friendly messages (never a traceback) when Ollama is off, a model is missing,
  or the microphone cannot be opened - voice mode then falls back to typing
- Tests with pytest (45 of them, no microphone needed)

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

Then type to chat, for example:

```
You: hello
You: what is the time
You: explain what a Python list is
You: goodbye jarvis
```

Flags:

| Flag | Meaning |
|---|---|
| `--text` | use the keyboard instead of a microphone |
| `--no-voice` | do not speak answers out loud |
| `--model NAME` | use a different Ollama model for this run |
| `--list-devices` | list your microphones and exit |
| `--device N` | use microphone number N (from `--list-devices`), or part of its name |

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
  "approved_directories": [],
  "vosk_model_path": "C:/Users/Students/OneDrive/Documents/001/001/jarvis_ai/models/vosk-model-small-en-us-0.15",
  "input_device": null,
  "wake_word": "hey jarvis",
  "command_timeout": 6,
  "wake_timeout": 0
}
```

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
| `I cannot reach Ollama` | Start it: `ollama serve` (or open the Ollama app). Rule-based commands still work. |
| `The model 'X' is not installed` | Run `ollama pull X`, or set a model you have: `ollama list`. |
| `Ollama took longer than 60 seconds` | Use a smaller model (`llama3.2:1b`) or raise `request_timeout` in `config.json`. |
| `offline speech model was not found` | Unzip the Vosk model into `models\` (step 4 above). |
| `I could not use ... microphone` | Run `python main.py --list-devices`, then `--device N`; check Settings > Privacy > Microphone; or run `--text`. |
| Wake word never heard | Say it clearly and close to the mic: "Hey JARVIS". Try another mic with `--device N`. |
| Wrong words recognised | Normal in a noisy room; the small English model is not perfect. Text mode always works. |
| Speech is off / no sound | Check Windows volume and the default output device. Add `--no-voice` to run silently. |
| `pyttsx3 is not installed` | Run `pip install pyttsx3` inside the activated venv. |
| `python` not found | Install Python 3.10+ from python.org and tick "Add python.exe to PATH". |
| Ollama answers are slow | Only one model fits in RAM at a time here; close other apps or use a 1B model. |

Logs are written to `logs\jarvis.log`. They record actions and errors only -
never your typed messages, file contents, or audio.

---

## Project layout

```
jarvis_ai/
  main.py              entry point (voice mode + text mode)
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
| 5 | Hardening, `run_jarvis.bat`, TESTING.md | not started |
