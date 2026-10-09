"""Where Read Aloud keeps its files, and its settings.

Everything lives under ~/.claude-voice (override with CLAUDE_VOICE_HOME). The folder is
shared with the Claude Done Alerts plugin: both use the same Kokoro model download and the
same playback lock, so an alert can slot in between sentences of a read instead of talking
over it.

    ~/.claude-voice/
        models/              Kokoro model + voices (downloaded once, shared)
        play.lock            held while any audio plays
        read-aloud/
            settings.json    voice, speed, default mode, model size
            reader.pid       PID of the playing worker (the VS Code button watches this)
            install.json     where the plugin is installed (written by the SessionStart hook)
            reader.log
"""
import json
import os
import time
from pathlib import Path

HOME = Path(os.environ.get("CLAUDE_VOICE_HOME") or Path.home() / ".claude-voice")
MODELS = HOME / "models"
PLAY_LOCK = HOME / "play.lock"
STATE = HOME / "read-aloud"
SETTINGS = STATE / "settings.json"
PID_FILE = STATE / "reader.pid"
INSTALL = STATE / "install.json"
LOG = STATE / "reader.log"

DEFAULTS = {
    "voice": "af_heart",   # see `reader.py voices`
    "speed": 1.15,
    "mode": "final",       # final = last message of the reply, full = every message in the turn
    "model": "int8",       # int8 (92 MB) | fp16 (177 MB) | full (326 MB)
    "picker_minutes": 30,  # VS Code: sessions active this recently show up in the picker
    "skip_sessions": [],   # never read sessions whose first lines contain any of these strings
    "warm_minutes": 15,    # keep the voice model loaded this long after the last read (0 = never)
}


def load_settings():
    s = dict(DEFAULTS)
    try:
        s.update(json.loads(SETTINGS.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return s


def save_settings(**changes):
    s = load_settings()
    s.update(changes)
    STATE.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(s, indent=2), encoding="utf-8")
    return s


def log(msg):
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        if LOG.exists() and LOG.stat().st_size > 512_000:
            LOG.write_text("", encoding="utf-8")
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except OSError:
        pass
