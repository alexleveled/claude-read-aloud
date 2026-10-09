# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "kokoro-onnx>=0.4.7",
#     "sounddevice>=0.4.6",
#     "filelock>=3.12",
#     "psutil>=5.9",
# ]
# ///
"""Read Aloud: speaks Claude Code's last reply with Kokoro, a local voice model.

    reader.py read [--session ID] [--cwd DIR] [--transcript FILE] [--full]
    reader.py stop | status
    reader.py sessions [--cwd DIR] [--minutes N]      JSON list for the VS Code picker
    reader.py text FILE [--full]                      print the cleaned text (debug)
    reader.py settings [voice|speed|mode|model VALUE]
    reader.py voices
    reader.py test                                    speak one line and wait
    reader.py doctor                                  JSON health report for /read setup
    reader.py download                                fetch the voice model now
    reader.py session-start                           SessionStart hook (background)

Run it through uv (`uv run --script reader.py ...`), which installs the packages listed above
on first use. `read` returns at once: a detached worker does the talking, generating one
chunk ahead of playback so audio starts in about a second.
"""
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import home  # noqa: E402
import speech  # noqa: E402
import transcript  # noqa: E402

WINDOWS = os.name == "nt"


# ---------------------------------------------------------------- process control

def _spawn(args):
    """Start this script detached from the caller, so it outlives the /read command or
    the VS Code click that started it."""
    exe = Path(sys.executable)
    kw = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
              close_fds=True, cwd=str(HERE))
    if WINDOWS:
        pyw = exe.with_name("pythonw.exe")
        exe = pyw if pyw.exists() else exe
        kw["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    return subprocess.Popen([str(exe), str(Path(__file__).resolve()), *args], **kw)


def _worker_process():
    """The running worker, or None. Checks the command line too, so a recycled PID that now
    belongs to some other program is never mistaken for a read in progress."""
    import psutil

    try:
        pid = int(home.PID_FILE.read_text().strip())
        p = psutil.Process(pid)
        if p.is_running() and any("reader.py" in a for a in p.cmdline()):
            return p
    except (OSError, ValueError, psutil.Error):
        pass
    return None


def stop():
    import psutil

    p = _worker_process()
    if p:
        for c in p.children(recursive=True) + [p]:
            try:
                c.kill()
            except psutil.Error:
                pass
    home.PID_FILE.unlink(missing_ok=True)
    return p is not None


# ---------------------------------------------------------------- worker

def worker(job_path):
    import voice

    home.PID_FILE.write_text(str(os.getpid()))
    t0 = time.time()
    # The audio library takes most of a second to import; do it while the model loads.
    threading.Thread(target=lambda: __import__("sounddevice"), daemon=True).start()
    try:
        s = home.load_settings()
        chunks = speech.chunk(Path(job_path).read_text(encoding="utf-8"))
        k = voice.load_kokoro(s["model"])
        name = s["voice"]
        q = queue.Queue(maxsize=2)

        def produce():
            for i, c in enumerate(chunks):
                try:
                    q.put(k.create(c, voice=name, speed=float(s["speed"]), lang=voice.lang_for(name)))
                except Exception as e:  # one bad chunk shouldn't end the read
                    home.log(f"chunk {i} failed: {e!r}")
            q.put(None)

        threading.Thread(target=produce, daemon=True).start()
        first = True
        while (item := q.get()) is not None:
            if first:
                home.log(f"{len(chunks)} chunks, first audio after {time.time() - t0:.1f}s")
                first = False
            voice.play(*item)
    finally:
        try:
            if home.PID_FILE.read_text().strip() == str(os.getpid()):
                home.PID_FILE.unlink()
        except OSError:
            pass


def start(text):
    stop()
    home.STATE.mkdir(parents=True, exist_ok=True)
    job = home.STATE / "job.txt"
    job.write_text(text, encoding="utf-8")
    proc = _spawn(["worker", str(job)])
    home.PID_FILE.write_text(str(proc.pid))


# ---------------------------------------------------------------- commands

def cmd_read(opts):
    s = home.load_settings()
    path = opts.get("--transcript") or transcript.find_transcript(
        opts.get("--session"), opts.get("--cwd") or os.getcwd(), s["skip_sessions"])
    if not path:
        return "No Claude Code session found for this folder."
    raw = transcript.last_reply(transcript.load(path), "--full" in opts or s["mode"] == "full")
    text = speech.clean_for_speech(raw)
    if not text.strip():
        return "Nothing to read yet."
    start(text)
    words = len(text.split())
    mins = max(1, round(words / (160 * float(s["speed"]))))
    import voice
    if voice.missing(s["model"]):
        return (f"Downloading the voice model first (one time, {voice.FILES[s['model']][1] // 1_000_000} MB). "
                f"Reading {words} words after that.")
    return f"Reading {words} words (about {mins} min)."


def cmd_sessions(opts):
    out = []
    s = home.load_settings()
    minutes = int(opts.get("--minutes") or s["picker_minutes"])
    for f in transcript.recent_sessions(opts.get("--cwd") or os.getcwd(), minutes, s["skip_sessions"]):
        try:
            reply = transcript.last_reply(transcript.load(f))
        except (OSError, transcript.TranscriptFormatError):
            continue
        if not reply.strip():
            continue
        project, title = transcript.session_info(f)
        preview = re.sub(r"\s+", " ", speech.clean_for_speech(reply)).strip()
        out.append({
            "transcript": str(f),
            "project": project,
            "title": title,
            "age_seconds": int(time.time() - f.stat().st_mtime),
            "preview": preview[:110] + ("…" if len(preview) > 110 else ""),
        })
    return out


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
    elif key == "picker_minutes":
        value = int(value)
    else:
        return "Settings are voice, speed, mode, model and picker_minutes."
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
        if cmd == "worker":
            worker(args[1])
        elif cmd == "read":
            print(cmd_read(opts))
        elif cmd == "stop":
            print("Stopped reading." if stop() else "Nothing was playing.")
        elif cmd == "status":
            print("reading" if _worker_process() else "idle")
        elif cmd == "sessions":
            print(json.dumps(cmd_sessions(opts), ensure_ascii=False))
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
        if cmd == "worker":
            return
        print(f"Read Aloud error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
