"""Finding Claude's last reply in a Claude Code session transcript.

Claude Code writes each session to ~/.claude/projects/<folder>/<session-id>.jsonl, one JSON
entry per line. The format is internal to Claude Code and undocumented, so everything here
is defensive: unknown shapes are skipped, and TranscriptFormatError is raised when a file
has entries but none of them look like a conversation, so a format change shows up as a
clear message instead of reading the wrong text.
"""
import json
import os
import re
import time
from pathlib import Path


class TranscriptFormatError(Exception):
    pass


def projects_root():
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(base) if base else Path.home() / ".claude") / "projects"


# ---------------------------------------------------------------- locating transcripts

def _mangle(path):
    """Claude Code names a project folder after its path with every non-alphanumeric
    character replaced by '-'. Drive-letter case varies on Windows, so compare lowercased."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path)).lower()


def project_dirs(cwd):
    """Transcript folders for cwd and its ancestors. A session is filed under the folder it
    was started in, which can be a parent of the folder the editor has open. Never climbs to
    the home folder or above, where every session on the machine would match."""
    root = projects_root()
    if not root.is_dir():
        return []
    p = Path(cwd).resolve()
    floor = len(Path.home().parts)
    wanted = {_mangle(a) for a in [p, *p.parents] if len(a.parts) > floor}
    return [d for d in root.iterdir() if d.is_dir() and d.name.lower() in wanted]


def _head(f, lines=40):
    out = []
    try:
        with open(f, encoding="utf-8") as fh:
            for _, line in zip(range(lines), fh):
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    except OSError:
        pass
    return out


def is_skipped(f, skip=()):
    """Sessions nobody is listening to: ones run by `claude -p` or the Agent SDK, plus any
    whose opening lines contain one of the `skip_sessions` strings from settings (handy for
    an always-on background session). Otherwise a busy background loop in the same folder
    would always be the "newest" session."""
    head = _head(f)
    if any(str(e.get("entrypoint") or "").startswith("sdk") for e in head):
        return True
    if skip:
        raw = json.dumps(head, ensure_ascii=False)
        return any(s and s in raw for s in skip)
    return False


def find_transcript(session_id=None, cwd=None, skip=()):
    root = projects_root()
    if session_id and re.fullmatch(r"[0-9a-fA-F-]{8,}", session_id) and root.is_dir():
        hits = list(root.glob(f"*/{session_id}.jsonl"))
        if hits:
            return hits[0]
    if cwd:
        files = [f for d in project_dirs(cwd) for f in d.glob("*.jsonl")]
        files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        for f in files:
            if not is_skipped(f, skip):
                return f
    return None


# ---------------------------------------------------------------- reading a transcript

def load(path):
    entries = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if isinstance(e, dict):
                entries.append(e)
    return entries


def _content(e):
    return (e.get("message") or {}).get("content") if isinstance(e.get("message"), dict) else None


def prompt_text(e):
    c = _content(e)
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return " ".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    return ""


READ_COMMAND = re.compile(r"<command-name>/(?:[\w-]+:)?read</command-name>")
# The same request in plain words. Kept narrow on purpose: the whole message has to be the
# request, so "read this file and fix it" is still a real message.
READ_REQUEST = re.compile(
    r"^\W*(?:(?:hey|ok|okay|please|can you|could you|would you)[\s,]+)*"
    r"(?:read|say|speak)\s+(?:that|it|this|the last (?:one|reply|message|answer|response)"
    r"|your (?:last )?(?:reply|message|answer|response)|the (?:reply|answer|response))"
    r"(?:\s+(?:to me|for me|out loud|aloud|again|back))*[\s,]*(?:please|thanks)?\W*$", re.I)


def is_read_request(text):
    return bool(READ_COMMAND.search(text) or READ_REQUEST.match(text.strip()))
NOT_TYPED = ("<task-notification>", "Base directory for this skill", "<local-command-", "Caveat:")


def is_human(e):
    """A message the person actually typed: not a tool result, not a skill body Claude Code
    injected, not a background agent reporting back."""
    if e.get("type") != "user" or e.get("isMeta") or e.get("isSidechain"):
        return False
    c = _content(e)
    if isinstance(c, list):
        kinds = {b.get("type") for b in c if isinstance(b, dict)}
        if "tool_result" in kinds or "text" not in kinds:
            return False
    elif not isinstance(c, str):
        return False
    return not prompt_text(e).lstrip().startswith(NOT_TYPED)


def last_reply(entries, full=False):
    """Claude's reply to the person's most recent message that wasn't a /read.
    full=False: the final message only. full=True: every text message in that turn."""
    if entries and not any(e.get("type") in ("user", "assistant") for e in entries):
        raise TranscriptFormatError(
            "This transcript has no user or assistant entries. Claude Code may have changed "
            "its transcript format; please open an issue on the Read Aloud repo.")
    human = [i for i, e in enumerate(entries) if is_human(e)]
    asks = [i for i in human if not is_read_request(prompt_text(entries[i]))]
    if not asks:
        return ""
    start = asks[-1]
    end = next((i for i in human if i > start), len(entries))
    texts = []
    for e in entries[start + 1:end]:
        if e.get("type") != "assistant" or e.get("isSidechain"):
            continue
        for b in _content(e) or []:
            if isinstance(b, dict) and b.get("type") == "text" and (b.get("text") or "").strip():
                texts.append(b["text"])
    if not texts:
        return ""
    return "\n\n".join(texts) if full else texts[-1]


def session_info(f):
    """Project name and Claude's auto title for a transcript, for the VS Code picker."""
    cwd = title = None
    for e in load(f):
        cwd = e.get("cwd") or cwd
        title = e.get("aiTitle") or title
    return (Path(cwd).name if cwd else f.parent.name), (title or "")


def recent_sessions(cwd, minutes=30, skip=()):
    """Interactive sessions under cwd (or its ancestors) that changed in the last `minutes`,
    newest first. Returns (path, entries) pairs; the caller builds previews."""
    cutoff = time.time() - minutes * 60
    files = [f for d in project_dirs(cwd) for f in d.glob("*.jsonl") if f.stat().st_mtime >= cutoff]
    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return [f for f in files if not is_skipped(f, skip)]
