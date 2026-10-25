"""
JARVIS - entry point.

Run it in a Command Prompt (CMD):

    .venv\\Scripts\\activate
    python main.py            (voice mode: say "hey jarvis", then a command)
    python main.py --text     (keyboard mode: works without a microphone)

Flags:
    --text         talk to JARVIS with the keyboard (no microphone)
    --no-voice     do not speak answers out loud
    --model NAME   use a different Ollama model for this run
    --device N     use microphone number N (see --list-devices)
    --list-devices show the microphones Windows can see, then exit
"""

from __future__ import annotations

import argparse
import logging
import sys

import config
from modules import ai_engine, command_router
from modules.speech import Speaker


def setup_logging() -> None:
    """Write a simple log file. We log *actions* only - never user text or audio."""
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = config.LOG_DIR / "jarvis.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)  # less noise


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="jarvis",
        description="JARVIS - a local, privacy-first voice assistant for Windows.",
    )
    parser.add_argument(
        "--text",
        action="store_true",
        help="Talk to JARVIS with the keyboard (no microphone needed).",
    )
    parser.add_argument(
        "--no-voice",
        action="store_true",
        help="Do not speak answers out loud.",
    )
    parser.add_argument("--model", metavar="NAME", help="Use a different Ollama model.")
    parser.add_argument(
        "--device",
        metavar="N",
        help="Microphone to use: a device number from --list-devices, or part of its name.",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="List available microphones and exit.",
    )
    parser.add_argument(
        "--mic-test",
        action="store_true",
        help="Show live mic level and recognised words for 15 seconds, then exit.",
    )
    parser.add_argument(
        "--debug-voice",
        action="store_true",
        help="In voice mode, print the live mic level and every word recognised.",
    )
    return parser.parse_args(argv)


def run_mic_test(seconds: int = 15) -> int:
    """Show what the microphone actually hears - the first thing to try
    when 'hey jarvis' does nothing."""
    import array
    import time

    from modules import voice

    try:
        voice.check_microphone()
        stt = voice.VoskSTT()
    except voice.VoiceError as exc:
        print(f"[{config.ASSISTANT_NAME}] {exc}")
        return 1

    print(f"MIC TEST - speak now for {seconds} seconds. Try: 'hey jarvis what is the time'")
    print("The level bar shows how loud your microphone is. [                 ] = silence")
    print()

    with voice._import_sounddevice().RawInputStream(
        samplerate=voice.SAMPLE_RATE,
        blocksize=voice.BLOCK_SIZE,
        channels=1,
        dtype="int16",
        device=config.INPUT_DEVICE,
    ) as stream:
        deadline = time.monotonic() + seconds
        last_shown = 0.0
        while time.monotonic() < deadline:
            block, _ = stream.read(voice.BLOCK_SIZE)
            pcm = bytes(block)
            samples = array.array("h")
            samples.frombytes(pcm)
            peak = max((abs(v) for v in samples), default=0)

            text, is_final = stt.feed(pcm)
            now = time.monotonic()
            if now - last_shown > 0.5:
                filled = min(20, peak // 600)
                bar = "#" * filled + " " * (20 - filled)
                print(f"  level [{bar}] peak={peak}")
                last_shown = now
            if text:
                kind = "final  " if is_final else "partial"
                print(f"  {kind}: {text}")

    print()
    print("Results:")
    print("  - bar stays empty / peak under 100  -> Windows is not sending your audio")
    print("    (check Settings > System > Sound > Input, and try another --device N)")
    print("  - level moves but words are wrong   -> mic works; JARVIS can then listen")
    return 0


def show_devices() -> int:
    """Print the microphones Windows can see (used by --list-devices)."""
    from modules import voice

    try:
        devices = voice.list_input_devices()
    except voice.VoiceError as exc:
        print(f"[JARVIS] {exc}")
        return 1
    if not devices:
        print("[JARVIS] I could not find any microphone. Check that one is plugged in.")
        return 1
    print("Microphones (use the number with --device):")
    for index, name in devices:
        print(f"  {index}: {name}")
    return 0


def parse_device(value: str | None):
    """--device can be a number (1) or a name fragment (realtek)."""
    if value is None:
        return None
    text = value.strip()
    if text.lstrip("-").isdigit():
        return int(text)
    return text


def check_ollama(speaker: Speaker) -> None:
    """Friendly startup check. Rule-based commands still work if this fails."""
    ok, message = ai_engine.ping()
    if ok:
        print(f"[{config.ASSISTANT_NAME}] {message}")
    else:
        print(f"[{config.ASSISTANT_NAME}] {message}")
        logging.getLogger("jarvis").warning("Startup check: Ollama not ready")


def run_text_mode(speaker: Speaker, history: list[dict]) -> None:
    """Keyboard loop - also used as the fallback if the microphone fails."""
    while True:
        try:
            user_text = input("You: ")
        except (EOFError, KeyboardInterrupt):
            print()  # new line after Ctrl+C / Ctrl+Z
            return

        response = command_router.route(user_text, history)
        if response.history:
            history[:] = response.history
        print(f"{config.ASSISTANT_NAME}: {response.text}")
        speaker.say(response.text)
        logging.getLogger("jarvis").info(
            "Handled command (source=%s exit=%s)", response.source, response.exit
        )
        if response.exit:
            return


def run_voice_mode(speaker: Speaker, history: list[dict], device, debug: bool = False) -> None:
    """Wake word -> one command -> answer -> back to waiting."""
    from modules import voice

    log = logging.getLogger("jarvis")

    try:
        voice.check_microphone(device)
        listener = voice.VoiceListener(
            device=device,
            debug=debug,
            on_wake=lambda: print(f"\n[{config.ASSISTANT_NAME}] Yes?"),
        )
    except voice.VoiceError as exc:
        print(f"[{config.ASSISTANT_NAME}] {exc}")
        return run_text_mode(speaker, history)  # still usable: fall back to typing

    marker = f'"{listener.wake_word}"'
    print(f"[{config.ASSISTANT_NAME}] Listening. Say {marker} followed by your command.")
    print("  (say \"stop listening\" or \"goodbye jarvis\" to exit, Ctrl+C to quit)")
    if debug:
        print("  [debug] the bar is your mic level; [partial]/[final] is what I hear")

    while True:
        try:
            command = listener.listen_for_command()
        except KeyboardInterrupt:
            print()
            break
        except voice.VoiceError as exc:
            print(f"\n[{config.ASSISTANT_NAME}] {exc}")
            break

        if not command:
            continue  # quiet spell: nothing said, keep waiting

        print(f"You (voice): {command}")
        response = command_router.route(command, history)
        if response.history:
            history[:] = response.history
        print(f"{config.ASSISTANT_NAME}: {response.text}")
        speaker.say(response.text)
        log.info("Handled voice command (source=%s exit=%s)", response.source, response.exit)

        if response.exit:
            break

    listener.close()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging()
    log = logging.getLogger("jarvis")

    if args.list_devices:
        return show_devices()
    if args.mic_test:
        return run_mic_test()

    if args.model:
        config.OLLAMA_MODEL = args.model

    mode = "text" if args.text else "voice"
    print("=" * 60)
    print(f"  {config.ASSISTANT_NAME} - local voice assistant ({mode} mode)")
    print(f"  {config.describe()}")
    if args.text:
        print("  Type 'help' for examples, or 'exit' / 'goodbye jarvis' to stop.")
    print("=" * 60)

    speak = config.ENABLE_TTS and not args.no_voice
    speaker = Speaker(enabled=speak, rate=config.TTS_RATE, volume=config.TTS_VOLUME)
    if not speak:
        print("[speech] Voice replies are off for this run.")
    check_ollama(speaker)

    history: list[dict] = []
    exit_code = 0
    try:
        if args.text:
            run_text_mode(speaker, history)
        else:
            run_voice_mode(speaker, history, parse_device(args.device), debug=args.debug_voice)
    except Exception as exc:  # last-resort safety net: no tracebacks for the user
        log.exception("Unexpected error in main loop: %s", exc.__class__.__name__)
        print(
            f"\n[{config.ASSISTANT_NAME}] Something unexpected happened, so I stopped. "
            f"See logs\\jarvis.log for details."
        )
        exit_code = 1
    finally:
        speaker.shutdown()

    log.info("JARVIS stopped")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
