"""Kokoro model download, speech synthesis and playback.

Kokoro (https://github.com/thewh1teagle/kokoro-onnx) runs on the CPU, so nothing leaves the
machine. The model is downloaded once into ~/.claude-voice/models and checked against a
pinned SHA-256 before it is used.
"""
import hashlib
import os
import time
import urllib.request

from home import MODELS, PLAY_LOCK, log

RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
FILES = {
    "int8": ("kokoro-v1.0.int8.onnx", 92361271,
               "6e742170d309016e5891a994e1ce1559c702a2ccd0075e67ef7157974f6406cb"),
    "fp16": ("kokoro-v1.0.fp16.onnx", 177464787,
               "c1610a859f3bdea01107e73e50100685af38fff88f5cd8e5c56df109ec880204"),
    "full": ("kokoro-v1.0.onnx", 325532387,
               "7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5"),
    "voices": ("voices-v1.0.bin", 28214398,
               "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d"),
}

# Voice name prefix -> espeak language. a = American English, b = British English, etc.
LANGS = {"a": "en-us", "b": "en-gb", "e": "es", "f": "fr-fr", "h": "hi", "i": "it",
         "j": "ja", "p": "pt-br", "z": "cmn"}

ENGLISH_VOICES = {
    "af_heart": "American, female, warm (default)",
    "af_bella": "American, female, bright",
    "af_nicole": "American, female, soft",
    "am_michael": "American, male, steady",
    "am_fenrir": "American, male, deep",
    "am_puck": "American, male, lively",
    "bf_emma": "British, female, clear",
    "bf_isabella": "British, female, warm",
    "bm_george": "British, male, deep",
    "bm_fable": "British, male, storyteller",
    "bm_daniel": "British, male, calm",
}


def model_paths(size):
    name = FILES.get(size, FILES["int8"])[0]
    return MODELS / name, MODELS / FILES["voices"][0]


def missing(size):
    return [p for p in model_paths(size) if not p.exists()]


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _fetch(key):
    name, size, digest = FILES[key]
    dest = MODELS / name
    if dest.exists():
        return
    part = dest.with_suffix(dest.suffix + ".part")
    log(f"downloading {name} ({size / 1e6:.0f} MB)")
    req = urllib.request.Request(RELEASE + name, headers={"User-Agent": "claude-read-aloud"})
    with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as f:
        while True:
            block = r.read(1 << 20)
            if not block:
                break
            f.write(block)
    got = part.stat().st_size
    if got != size or (digest and _sha256(part) != digest):
        part.unlink(missing_ok=True)
        raise RuntimeError(f"{name}: download was corrupt ({got} bytes), try again")
    os.replace(part, dest)
    log(f"downloaded {name}")


def ensure_models(size):
    """Download whatever is missing. A file lock keeps two processes (a SessionStart prefetch
    and a first /read, say) from downloading the same file twice."""
    from filelock import FileLock

    if not missing(size):
        return
    MODELS.mkdir(parents=True, exist_ok=True)
    with FileLock(str(MODELS / ".download.lock")):
        for key in (size if size in FILES else "int8", "voices"):
            _fetch(key)


def load_kokoro(size):
    from kokoro_onnx import Kokoro

    ensure_models(size)
    model, voices = model_paths(size)
    return Kokoro(str(model), str(voices))


def lang_for(voice):
    return LANGS.get(voice[:1], "en-us")


def play(audio, sample_rate, cancel=None):
    """Play one chunk while holding the shared playback lock, so a Done Alerts notification
    waits for the end of this sentence instead of talking over it. `cancel` (an Event) stops
    the wait for the lock; sounddevice.stop() from another thread cuts the chunk short."""
    import sounddevice as sd
    from filelock import FileLock, Timeout

    lock = FileLock(str(PLAY_LOCK))
    while True:
        if cancel is not None and cancel.is_set():
            return
        try:
            lock.acquire(timeout=0.2)
            break
        except Timeout:
            time.sleep(0.05)
    try:
        sd.play(audio, sample_rate)
        sd.wait()
    finally:
        lock.release()
