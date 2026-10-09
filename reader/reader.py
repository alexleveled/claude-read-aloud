# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "kokoro-onnx>=0.4.7",
#     "sounddevice>=0.4.6",
#     "filelock>=3.12",
# ]
# ///
"""Read Aloud: speaks Claude Code's last reply with Kokoro, a local voice model.

    reader.py read [--session ID] [--cwd DIR] [--transcript FILE] [--full]
    reader.py stop | status | shutdown
    reader.py sessions [--cwd DIR] [--minutes N]      JSON list for the VS Code picker
    reader.py text FILE [--full]                      print the cleaned text (debug)
    reader.py settings [voice|speed|mode|model|warm_minutes VALUE]
    reader.py voices
    reader.py test                                    speak one line and wait
    reader.py doctor                                  JSON health report for /read setup
    reader.py download                                fetch the voice model now
    reader.py session-start                           SessionStart hook (background)
    reader.py serve                                   run the warm reader (started for you)

Run it through uv (`uv run --script reader.py ...`), which installs the packages listed above
on first use. `read`, `stop`, `status` and `sessions` are handled by the warm reader
(daemon.py), a background process that keeps the voice model loaded and starts itself on
the first read. It shuts down after `warm_minutes` (default 15) without a read.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import home  # noqa: E402
import speech  # noqa: E402
import daemon  # noqa: E402
import transcript  # noqa: E402

WINDOWS = os.name == "nt"


# ---------------------------------------------------------------- the warm reader

def _spawn(args):
    """Start this script detached from the caller, so it outlives the /read command or
    the VS Code click that started it."""
    exe = Path(sys.executable)
    kw = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
              close_fds=True, cwd=str(HERE))
    cmd = [str(exe), str(Path(__file__).resolve()), *args]
    if not WINDOWS:
        return subprocess.Popen(cmd, start_new_session=True, **kw)
    # In a uv environment python.exe / pythonw.exe are launchers that start the real
    # interpreter as a child. A child with no console to inherit pops up a terminal window,
    # so give the launcher a hidden console (CREATE_NO_WINDOW) for the child to inherit,
    # rather than none (DETACHED_PROCESS). Breaking away from the caller's job keeps the
    # reader alive when VS Code closes, where the job allows it.
    flags = 0x08000000 | 0x00000200  # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    try:
        return subprocess.Popen(cmd, creationflags=flags | 0x01000000, **kw)  # + CREATE_BREAKAWAY_FROM_JOB
    except OSError:
        return subprocess.Popen(cmd, creationflags=flags, **kw)


def ask(req, start=True, timeout=30):
    """Send a request to the warm reader, starting it first if it isn't running."""
    resp = daemon.request(req, timeout)
    if resp is not None or not start:
        return resp
    _spawn(["serve"])
    deadline = time.time() + 20
    while time.time() < deadline:
        time.sleep(0.1)
        resp = daemon.request(req, timeout)
        if resp is not None:
            return resp
    return {"ok": False, "message": "The reader didn't start. See ~/.claude-voice/read-aloud/reader.log."}


def cmd_settings(args):
    if len(args) < 2:
        return json.dumps(home.load_settings(), indent=2)
    key, value = args[0], args[1]
    import voice
    if key == "voice":
        if not re.fullmatch(r"[a-z]{2}_[a-z]+", value):
            return f"Unknown voice '{value}'. Run `voices` to list them."
    elif key == "speed":
        try:
            value = float(value)
        except ValueError:
            return "Speed must be a number, like 1.15."
        if not 0.5 <= value <= 2.0:
            return "Speed must be between 0.5 and 2.0."
    elif key == "mode":
        if value not in ("final", "full"):
            return "Mode is final or full."
    elif key == "model":
        if value not in ("int8", "fp16", "full"):
            return "Model is int8, fp16 or full."
    elif key in ("picker_minutes", "warm_minutes"):
        try:
            value = int(value)
        except ValueError:
            return f"{key} must be a whole number of minutes."
    else:
        return "Settings are voice, speed, mode, model, picker_minutes and warm_minutes."
    home.save_settings(**{key: value})
    extra = " It downloads on the next read." if key == "model" and voice.missing(value) else ""
    return f"{key} set to {value}.{extra}"


def cmd_test():
    import voice

    s = home.load_settings()
    k = voice.load_kokoro(s["model"])
    audio, sr = k.create("Read Aloud is working. This is how I'll sound reading Claude's replies.",
                         voice=s["voice"], speed=float(s["speed"]), lang=voice.lang_for(s["voice"]))
    voice.play(audio, sr)
    return f"Played a test line with {s['voice']} at {s['speed']}x."


def cmd_doctor():
    import voice

    s = home.load_settings()
    report = {
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "home": str(home.HOME),
        "settings": s,
        "model_missing": [p.name for p in voice.missing(s["model"])],
        "transcripts_dir": str(transcript.projects_root()),
        "transcripts_found": transcript.projects_root().is_dir(),
        "vscode_cli": shutil.which("code"),
        "warm_reader": daemon.request({"cmd": "status"}, timeout=5),
    }
    try:
        import sounddevice as sd
        dev = sd.query_devices(kind="output")
        report["audio_output"] = dev.get("name")
    except Exception as e:  # PortAudio missing on Linux, no output device, ...
        report["audio_output"] = None
        report["audio_error"] = str(e)
    try:
        report["install"] = json.loads(home.INSTALL.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        report["install"] = None
    return json.dumps(report, indent=2)


def cmd_session_start():
    """SessionStart hook (run in the background by run.sh): record where the plugin lives
    for the VS Code extension, then fetch the voice model if it isn't there yet."""
    import voice

    home.STATE.mkdir(parents=True, exist_ok=True)
    info = {"plugin_root": str(HERE.parent), "reader": str(Path(__file__).resolve()),
            "uv": os.environ.get("READ_ALOUD_UV") or shutil.which("uv"), "updated": int(time.time())}
    home.INSTALL.write_text(json.dumps(info, indent=2), encoding="utf-8")
    s = home.load_settings()
    if voice.missing(s["model"]):
        try:
            voice.ensure_models(s["model"])
        except Exception as e:
            home.log(f"model prefetch failed: {e!r}")


def main():
    if WINDOWS:
        sys.stdout.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    cmd = args[0] if args else "read"
    opts = {}
    i = 1
    while i < len(args):
        if args[i].startswith("--"):
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                opts[args[i]] = args[i + 1]
                i += 2
                continue
            opts[args[i]] = True
        i += 1

    try:
        if cmd == "serve":
            daemon.Daemon().serve()
        elif cmd == "read":
            req = {"cmd": "read", "full": "--full" in opts}
            for k in ("transcript", "session", "cwd"):
                if isinstance(opts.get(f"--{k}"), str):
                    req[k] = opts[f"--{k}"]
            req.setdefault("cwd", os.getcwd())
            resp = ask(req)
            print(resp["message"])
            if not resp["ok"]:
                sys.exit(1)
        elif cmd == "stop":
            resp = ask({"cmd": "stop"}, start=False)
            home.PID_FILE.unlink(missing_ok=True)
            print(resp["message"] if resp else "Nothing was playing.")
        elif cmd == "status":
            resp = ask({"cmd": "status"}, start=False)
            print(f"{resp['message']} (warm)" if resp else "idle (cold)")
        elif cmd == "shutdown":
            resp = ask({"cmd": "shutdown"}, start=False)
            print(resp["message"] if resp else "The warm reader wasn't running.")
        elif cmd == "sessions":
            req = {"cmd": "sessions", "cwd": opts.get("--cwd") or os.getcwd()}
            if opts.get("--minutes"):
                req["minutes"] = int(opts["--minutes"])
            resp = ask(req)
            print(json.dumps(resp.get("data") or [], ensure_ascii=False))
        elif cmd == "text":
            print(speech.clean_for_speech(transcript.last_reply(transcript.load(args[1]), "--full" in opts)))
        elif cmd == "settings":
            print(cmd_settings(args[1:]))
        elif cmd == "voices":
            import voice
            current = home.load_settings()["voice"]
            for v, d in voice.ENGLISH_VOICES.items():
                print(f"{'*' if v == current else ' '} {v:<12} {d}")
            print("\nKokoro has more voices and languages: https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md")
        elif cmd == "test":
            print(cmd_test())
        elif cmd == "doctor":
            print(cmd_doctor())
        elif cmd == "download":
            import voice
            voice.ensure_models(home.load_settings()["model"])
            print("Voice model ready.")
        elif cmd == "session-start":
            cmd_session_start()
        else:
            print(__doc__)
    except transcript.TranscriptFormatError as e:
        print(str(e))
        sys.exit(2)
    except Exception as e:
        home.log(f"{cmd} failed: {e!r}")
        if cmd == "serve":
            return
        print(f"Read Aloud error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
