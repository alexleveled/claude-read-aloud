"""The warm reader: a background process that keeps the voice model loaded.

Starting Python and loading Kokoro takes a few seconds, and doing it on every read is most
of the wait before the first word. The daemon pays that once, then answers requests from
`reader.py` (and from the VS Code extension directly) over a localhost socket, so a read
starts speaking in well under a second.

It shuts itself down after `warm_minutes` (default 15) with no reads, handing the memory
back. The next read starts it again. warm_minutes = 0 means it exits as soon as it finishes
speaking, which is the old cold behaviour.

Protocol: one JSON object per line in each direction. Every request carries the token from
daemon.json, so only processes that can read the user's ~/.claude-voice folder can use it.

    {"token": ..., "cmd": "read", "transcript"|"session"|"cwd": ..., "full": bool}
    {"token": ..., "cmd": "sessions", "cwd": ..., "minutes": n}
    {"token": ..., "cmd": "stop" | "status" | "ping" | "shutdown"}
    -> {"ok": true, "message": "...", "data": ...}
"""
import json
import os
import queue
import secrets
import socket
import threading
import time

import home
import speech
import transcript

DAEMON_FILE = home.STATE / "daemon.json"


class Speaker:
    """Plays one read at a time. A new read cancels the one in progress."""

    def __init__(self, daemon):
        self.daemon = daemon
        self.cancel = threading.Event()
        self.thread = None

    @property
    def speaking(self):
        return bool(self.thread and self.thread.is_alive())

    def stop(self):
        was = self.speaking
        self.cancel.set()
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass
        if self.thread:
            self.thread.join(timeout=5)
        self.thread = None
        home.PID_FILE.unlink(missing_ok=True)
        return was

    def start(self, text):
        self.stop()
        self.cancel = threading.Event()
        self.thread = threading.Thread(target=self._run, args=(text, self.cancel), daemon=True)
        self.thread.start()

    def _run(self, text, cancel):
        import voice

        # The VS Code button watches this file to flip between Read and Stop.
        home.PID_FILE.write_text(str(os.getpid()))
        t0 = time.time()
        try:
            k = self.daemon.kokoro()
            s = home.load_settings()
            name, speed = s["voice"], float(s["speed"])
            chunks = speech.chunk(text)
            q = queue.Queue(maxsize=2)

            def produce():
                for i, c in enumerate(chunks):
                    if cancel.is_set():
                        break
                    try:
                        q.put(k.create(c, voice=name, speed=speed, lang=voice.lang_for(name)))
                    except Exception as e:
                        home.log(f"chunk {i} failed: {e!r}")
                q.put(None)

            threading.Thread(target=produce, daemon=True).start()
            first = True
            while not cancel.is_set():
                item = q.get()
                if item is None:
                    break
                if first:
                    home.log(f"{len(chunks)} chunks, first audio after {time.time() - t0:.1f}s")
                    first = False
                voice.play(*item, cancel=cancel)
        except Exception as e:
            home.log(f"read failed: {e!r}")
        finally:
            if not cancel.is_set():
                home.PID_FILE.unlink(missing_ok=True)
            self.daemon.touch()


class Daemon:
    def __init__(self):
        self.token = secrets.token_hex(16)
        self.last_used = time.time()
        self.speaker = Speaker(self)
        self._model = None
        self._model_size = None
        self._model_lock = threading.Lock()
        self.running = True

    def touch(self):
        self.last_used = time.time()

    def kokoro(self):
        """Load the model once; reload only if the model size setting changed."""
        import voice

        size = home.load_settings()["model"]
        with self._model_lock:
            if self._model is None or self._model_size != size:
                self._model = voice.load_kokoro(size)
                self._model_size = size
            return self._model

    # ------------------------------------------------------------ requests

    def handle(self, req):
        cmd = req.get("cmd")
        self.touch()
        if cmd == "ping":
            return {"ok": True, "message": "pong"}
        if cmd == "status":
            return {"ok": True, "message": "reading" if self.speaker.speaking else "idle",
                    "data": {"warm": self._model is not None, "pid": os.getpid()}}
        if cmd == "stop":
            return {"ok": True, "message": "Stopped reading." if self.speaker.stop() else "Nothing was playing."}
        if cmd == "shutdown":
            self.speaker.stop()
            self.running = False
            DAEMON_FILE.unlink(missing_ok=True)  # stop new clients finding us right away
            return {"ok": True, "message": "Warm reader shut down."}
        if cmd == "sessions":
            return {"ok": True, "data": sessions(req.get("cwd") or os.getcwd(), req.get("minutes"))}
        if cmd == "read":
            return self.read(req)
        return {"ok": False, "message": f"Unknown command {cmd!r}"}

    def read(self, req):
        import voice

        s = home.load_settings()
        path = req.get("transcript") or transcript.find_transcript(
            req.get("session"), req.get("cwd") or os.getcwd(), s["skip_sessions"])
        if not path:
            return {"ok": True, "message": "No Claude Code session found for this folder."}
        try:
            raw = transcript.last_reply(transcript.load(path), bool(req.get("full")) or s["mode"] == "full")
        except transcript.TranscriptFormatError as e:
            return {"ok": False, "message": str(e)}
        text = speech.clean_for_speech(raw)
        if not text.strip():
            return {"ok": True, "message": "Nothing to read yet."}
        downloading = bool(voice.missing(s["model"]))
        self.speaker.start(text)
        words = len(text.split())
        if downloading:
            mb = voice.FILES[s["model"]][1] // 1_000_000
            return {"ok": True, "message": f"Downloading the voice model first (one time, {mb} MB). Reading {words} words after that."}
        mins = max(1, round(words / (160 * float(s["speed"]))))
        return {"ok": True, "message": f"Reading {words} words (about {mins} min)."}

    # ------------------------------------------------------------ server

    def serve(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        srv.listen(8)
        srv.settimeout(2.0)
        home.STATE.mkdir(parents=True, exist_ok=True)
        tmp = DAEMON_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"pid": os.getpid(), "port": srv.getsockname()[1], "token": self.token,
                                   "started": int(time.time())}), encoding="utf-8")
        os.replace(tmp, DAEMON_FILE)
        home.log(f"warm reader up on port {srv.getsockname()[1]}")
        # Load the model while waiting for the first request instead of on it.
        threading.Thread(target=self._preload, daemon=True).start()
        try:
            while self.running:
                try:
                    conn, _ = srv.accept()
                except socket.timeout:
                    if self._idle_expired():
                        home.log("warm reader idle, shutting down")
                        break
                    continue
                threading.Thread(target=self._client, args=(conn,), daemon=True).start()
        finally:
            self.speaker.stop()
            srv.close()
            try:
                if json.loads(DAEMON_FILE.read_text(encoding="utf-8")).get("pid") == os.getpid():
                    DAEMON_FILE.unlink()
            except (OSError, ValueError):
                pass

    def _preload(self):
        try:
            import sounddevice  # noqa: F401  (slow import, do it before the first read)
            import voice
            k = self.kokoro()
            # ONNX runtime's first inference is slower than the rest; get it out of the way.
            name = home.load_settings()["voice"]
            k.create("Ready.", voice=name, speed=1.0, lang=voice.lang_for(name))
        except Exception as e:
            home.log(f"model preload failed: {e!r}")

    def _idle_expired(self):
        if self.speaker.speaking:
            return False
        minutes = float(home.load_settings().get("warm_minutes", 15))
        return time.time() - self.last_used > minutes * 60

    def _client(self, conn):
        with conn:
            conn.settimeout(30)
            try:
                buf = b""
                while not buf.endswith(b"\n"):
                    part = conn.recv(65536)
                    if not part:
                        return
                    buf += part
                req = json.loads(buf.decode("utf-8"))
                if req.get("token") != self.token:
                    resp = {"ok": False, "message": "bad token"}
                else:
                    resp = self.handle(req)
            except Exception as e:
                home.log(f"request failed: {e!r}")
                resp = {"ok": False, "message": f"Read Aloud error: {e}"}
            try:
                conn.sendall((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
            except OSError:
                pass


def sessions(cwd, minutes=None):
    import re

    s = home.load_settings()
    minutes = int(minutes or s["picker_minutes"])
    out = []
    for f in transcript.recent_sessions(cwd, minutes, s["skip_sessions"]):
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


# ---------------------------------------------------------------- client side

def info():
    try:
        return json.loads(DAEMON_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def request(req, timeout=30):
    """Send one request to a running daemon. Returns the response, or None if none is up."""
    d = info()
    if not d:
        return None
    try:
        with socket.create_connection(("127.0.0.1", d["port"]), timeout=2) as c:
            c.settimeout(timeout)
            c.sendall((json.dumps({**req, "token": d["token"]}) + "\n").encode("utf-8"))
            buf = b""
            while not buf.endswith(b"\n"):
                part = c.recv(65536)
                if not part:
                    break
                buf += part
        return json.loads(buf.decode("utf-8"))
    except (OSError, ValueError, KeyError):
        return None
