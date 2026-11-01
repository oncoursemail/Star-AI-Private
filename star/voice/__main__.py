"""Command line for STAR voice calls.

    python -m star.voice setup              download the voice model files (checked by size and SHA-256)
    python -m star.voice call               talk to Star with the microphone (Ctrl+C to hang up)
    python -m star.voice make-test-audio    synthesise the test questions for file-driven calls
    python -m star.voice file-call          run a scripted call from WAV files and print the latency table
    python -m star.voice say "Hello"        speak one line in the chosen voice
    python -m star.voice devices            list microphones and speakers

Server address and key come from STAR_SERVER_URL and STAR_SERVER_API_KEY. Model files are read from the
folder in STAR_VOICE_MODELS. See docs/STAR_VOICE_CALLS.md.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

from .settings import ASR_MODELS, CALL_MODES, ENDPOINTERS, OUTPUT_MODES, VoiceSettings

# The scripted caller. Short, natural questions; the third one is cut off by the fourth (barge-in test).
TEST_LINES = {
    "q1-greeting": "Hi Star, it's me. I just got home from school.",
    "q2-help": "I'm trying to make a shop in my Roblox game, but I don't know where to start.",
    "q3-long": "Can you explain how a remote event works, and tell me all the steps I need to do?",
    "q4-interrupt": "Wait, sorry, hold on. Can you say that in a much simpler way?",
    "q5-thanks": "Okay, thank you. I think I get it now.",
}
TEST_SCENARIO = {"steps": [
    {"say": "q1-greeting.wav"}, {"wait": "reply_done"},
    {"say": "q2-help.wav"}, {"wait": "reply_done"},
    {"say": "q3-long.wav"}, {"wait": "speaking", "then_seconds": 2.0},
    {"say": "q4-interrupt.wav"}, {"wait": "reply_done"},
    {"say": "q5-thanks.wav"}, {"wait": "reply_done"},
]}


def _settings(args) -> VoiceSettings:
    overrides = {k: v for k, v in vars(args).items() if k in asdict(VoiceSettings()) and v is not None}
    return VoiceSettings.from_mapping(overrides, base=VoiceSettings.from_env())


def _add_engine_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--voice", help="voice id from the audition page, e.g. heart or blend-heart-nicole")
    parser.add_argument("--speed", type=float)
    parser.add_argument("--asr-model", dest="asr_model", choices=ASR_MODELS)
    parser.add_argument("--device", choices=["auto", "cuda", "cpu"])
    parser.add_argument("--endpointer", choices=ENDPOINTERS)
    parser.add_argument("--output", choices=OUTPUT_MODES, help="speakers turns the echo gate on")
    parser.add_argument("--max-reply-tokens", dest="max_reply_tokens", type=int)
    parser.add_argument("--call-mode", dest="call_mode", choices=CALL_MODES, help="push-to-talk (default) or hands-free")
    parser.add_argument("--offline-brain", action="store_true",
                        help="use built-in scripted replies instead of the STAR Server (audio path test)")


def _brain(args, settings: VoiceSettings):
    from .brain import ScriptedBrain
    from .runtime import make_brain
    return ScriptedBrain() if args.offline_brain else make_brain(settings)


def cmd_make_test_audio(args) -> int:
    from . import engines
    from .filecall import write_wav
    out = Path(args.out)
    tts = engines.KokoroTTS(voice=args.caller_voice, speed=1.0, device=args.device or "auto")
    for name, text in TEST_LINES.items():
        pcm = b"".join(chunk for chunk, _rate in tts.synthesize(text))
        audio = engines.resample(engines.pcm16_to_float(pcm), tts.sample_rate, 16000)
        write_wav(out / f"{name}.wav", engines.float_to_pcm16(audio), 16000)
        print(f"{name}.wav  {len(audio) / 16000:.1f}s  {text}")
    (out / "scenario.json").write_text(json.dumps(
        {"note": f"Caller voice: Kokoro stock voice {args.caller_voice} (synthetic).", "lines": TEST_LINES,
         **TEST_SCENARIO}, indent=1), encoding="utf-8")
    print(f"Wrote {out / 'scenario.json'}")
    return 0


def cmd_file_call(args) -> int:
    from .filecall import FileCall
    from .runtime import Engines, build_session
    settings = _settings(args)
    scenario_path = Path(args.scenario)
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    engines = Engines.load(settings, progress=lambda m: print(f"  {m}...", flush=True))
    print("  load times (s):", engines.load_seconds, flush=True)
    brain = _brain(args, settings)

    def show(event: dict) -> None:
        kind = event["type"]
        if kind == "final_transcript":
            print(f"  you : {event['text']}", flush=True)
        elif kind == "assistant_sentence":
            print(f"  star: {event['text']}", flush=True)
        elif kind == "interrupted":
            print(f"  -- interrupted ({event['reason']}); heard: {event['heard_text']!r}", flush=True)
        elif kind == "error":
            print(f"  !! {event['message']}", flush=True)

    def make(speaker, on_event):
        def both(event):
            on_event(event)
            show(event)
        return build_session(settings, engines, speaker, brain=brain, on_event=both)

    call = FileCall(make, echo_db=args.echo_db, base_dir=scenario_path.parent, step_timeout=args.step_timeout)
    print(f"Running {scenario_path.name} (voice {settings.voice}, speech-to-text {engines.asr.model_name} on "
          f"{engines.asr.device}, voice engine on {engines.tts.device}, end of turn: {settings.endpointer})", flush=True)
    result = call.run(scenario)
    print()
    print(result.table())
    if args.out:
        result.save(args.out)
        print(f"\nSaved user.wav, star.wav, turns.json and latency.txt to {args.out}")
    if args.verify:
        heard = engines.asr.transcribe(result.star_audio, result.star_rate)
        print("\nStar's recorded audio, transcribed back:", heard)
    return 1 if result.timed_out else 0


def cmd_call(args) -> int:
    from .devices import Microphone, SoundSpeaker
    from .metrics import latency_summary, latency_table
    from .runtime import Engines, build_session
    settings = _settings(args)
    print("Getting ready (the first start downloads the speech recognition model)...", flush=True)
    engines = Engines.load(settings, progress=lambda m: print(f"  {m}...", flush=True))
    brain = _brain(args, settings)
    speaker = SoundSpeaker(sample_rate=getattr(engines.tts, "sample_rate", 24000),
                           device=settings.output_device or None)

    def show(event: dict) -> None:
        kind = event["type"]
        if kind == "state":
            print(f"[{event['state']}]", flush=True)
        elif kind == "final_transcript" and event["text"]:
            print(f"  you : {event['text']}", flush=True)
        elif kind == "assistant_sentence":
            print(f"  star: {event['text']}", flush=True)
        elif kind == "interrupted":
            print("  (you interrupted)", flush=True)
        elif kind == "error":
            print(f"  !! {event['message']}", flush=True)

    session = build_session(settings, engines, speaker, brain=brain, on_event=show)
    microphone = Microphone(device=settings.input_device or None)
    print("\nStar is listening. Say hello. Press Ctrl+C to hang up."
          + ("" if settings.output == "speakers" else " (Use headphones, or start with --output speakers.)"),
          flush=True)
    session.start()
    try:
        with microphone, speaker:
            for frame in microphone:
                session.feed(frame)
    except KeyboardInterrupt:
        pass
    finally:
        session.stop()
    if session.turns:
        print()
        print(latency_table(session.turns))
        statistics = latency_summary(session.turns)
        audio = statistics["latency"]["speech_end_to_audio_submitted"]
        if audio["n"]:
            print(f"First PCM submitted to speaker: p50={audio['p50_ms']:.1f} ms, "
                  f"p95={audio['p95_ms']:.1f} ms ({audio['n']} reliable turns; "
                  "not a measurement of physical speaker playback)")
        if statistics["invalid_clock_turns"] or statistics["errored_turns"]:
            print(f"Excluded from latency percentiles: "
                  f"{statistics['errored_turns']} errored, "
                  f"{statistics['invalid_clock_turns']} invalid clock")
    return 0


def cmd_say(args) -> int:
    from . import engines
    from .devices import SoundSpeaker
    settings = _settings(args)
    tts = engines.make_tts(settings.tts_engine, settings.voice, settings.speed, settings.device)
    with SoundSpeaker(sample_rate=tts.sample_rate, device=settings.output_device or None) as speaker:
        started = time.perf_counter()
        for pcm, rate in tts.synthesize(args.text):
            speaker.play(pcm, rate)
        print(f"synthesised in {time.perf_counter() - started:.2f}s on {tts.device}")
        while speaker.pending_seconds() > 0:
            time.sleep(0.05)
    return 0


def cmd_setup(_args) -> int:
    from .setup_models import download
    download()
    return 0


def cmd_devices(_args) -> int:
    from .devices import list_devices
    for item in list_devices():
        print(f"{item['index']:>3}  {item['kind']:<7} {item['name']}{'  (default)' if item['default'] else ''}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m star.voice", description="STAR voice calls")
    sub = parser.add_subparsers(dest="command", required=True)

    call = sub.add_parser("call", help="talk to Star with the microphone")
    _add_engine_options(call)
    call.add_argument("--input-device", dest="input_device")
    call.add_argument("--output-device", dest="output_device")
    call.set_defaults(run=cmd_call)

    audio = sub.add_parser("make-test-audio", help="synthesise the scripted caller's questions")
    audio.add_argument("--out", required=True)
    audio.add_argument("--caller-voice", default="am_michael", help="Kokoro stock voice for the pretend caller")
    audio.add_argument("--device", choices=["auto", "cuda", "cpu"])
    audio.set_defaults(run=cmd_make_test_audio)

    file_call = sub.add_parser("file-call", help="run a scripted call from WAV files")
    _add_engine_options(file_call)
    file_call.add_argument("--scenario", required=True)
    file_call.add_argument("--out", help="folder for user.wav, star.wav, turns.json, latency.txt")
    file_call.add_argument("--echo-db", dest="echo_db", type=float,
                           help="mix Star's audio into the microphone at this level, e.g. -15 (speaker simulation)")
    file_call.add_argument("--step-timeout", dest="step_timeout", type=float, default=120.0)
    file_call.add_argument("--verify", action="store_true", help="transcribe Star's recorded audio as a check")
    file_call.set_defaults(run=cmd_file_call)

    say = sub.add_parser("say", help="speak one line in the chosen voice")
    say.add_argument("text")
    say.add_argument("--voice")
    say.add_argument("--speed", type=float)
    say.add_argument("--device", choices=["auto", "cuda", "cpu"])
    say.add_argument("--output-device", dest="output_device")
    say.set_defaults(run=cmd_say)

    setup = sub.add_parser("setup", help="download the voice model files")
    setup.set_defaults(run=cmd_setup)

    devices = sub.add_parser("devices", help="list microphones and speakers")
    devices.set_defaults(run=cmd_devices)

    args = parser.parse_args(argv)
    try:
        return int(args.run(args) or 0)
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"Could not start: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
