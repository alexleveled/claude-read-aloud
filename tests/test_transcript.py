import json
import os
import pathlib
import re

import pytest

import transcript


def write(path, entries):
    path.write_text("\n".join(json.dumps(e) for e in entries) + ("\n" if entries else ""), encoding="utf-8")
    return path


def user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def user_blocks(text):
    return {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}}


def tool_result():
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}}


def asst(text, **extra):
    return {"type": "assistant", "message": {"role": "assistant",
                                             "content": [{"type": "text", "text": text}]}, **extra}


def roundtrip(tmp_path, entries):
    return transcript.load(write(tmp_path / "t.jsonl", entries))


def test_last_reply_final_text_only(tmp_path):
    e = roundtrip(tmp_path, [user("hi"), asst("working on it"), tool_result(), asst("all done")])
    assert transcript.last_reply(e) == "all done"


def test_last_reply_full_joins_turn(tmp_path):
    e = roundtrip(tmp_path, [user("hi"), asst("first"), tool_result(), asst("second")])
    assert transcript.last_reply(e, full=True) == "first\n\nsecond"


def test_list_content_prompt(tmp_path):
    e = roundtrip(tmp_path, [user("old"), asst("old reply"), user_blocks("new"), asst("new reply")])
    assert transcript.last_reply(e) == "new reply"


@pytest.mark.parametrize("cmd", ["/read", "/read-aloud:read"])
def test_read_command_skipped(tmp_path, cmd):
    e = roundtrip(tmp_path, [
        user("real question"), asst("real answer"),
        user(f"<command-name>{cmd}</command-name>"), asst("reading now"),
    ])
    assert transcript.last_reply(e) == "real answer"


@pytest.mark.parametrize("text", ["<task-notification>agent done</task-notification>",
                                  "Base directory for this skill: /x"])
def test_injected_user_text_not_a_turn(tmp_path, text):
    e = roundtrip(tmp_path, [user("question"), asst("part one"), user(text), asst("part two")])
    assert transcript.last_reply(e) == "part two"
    assert transcript.last_reply(e, full=True) == "part one\n\npart two"


def test_tool_result_not_a_turn(tmp_path):
    e = roundtrip(tmp_path, [user("q"), asst("a1"), tool_result(), asst("a2")])
    assert transcript.last_reply(e, full=True) == "a1\n\na2"


def test_sidechain_ignored(tmp_path):
    e = roundtrip(tmp_path, [user("q"), asst("main"), asst("subagent chatter", isSidechain=True)])
    assert transcript.last_reply(e) == "main"


def test_format_error_and_empty(tmp_path):
    e = roundtrip(tmp_path, [{"type": "summary"}, {"type": "summary"}])
    with pytest.raises(transcript.TranscriptFormatError):
        transcript.last_reply(e)
    assert transcript.last_reply([]) == ""


# ------------------------------------------------------------ find_transcript

@pytest.fixture
def env(tmp_path, monkeypatch):
    base = tmp_path.resolve()
    home = base / "home"
    cwd = home / "proj"
    cwd.mkdir(parents=True)
    cfg = base / "cfg"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: home))
    pdir = cfg / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(cwd))
    pdir.mkdir(parents=True)
    return cwd, pdir


def touch(f, t):
    os.utime(f, (t, t))


def test_find_newest(env):
    cwd, pdir = env
    a = write(pdir / "a.jsonl", [user("x")])
    b = write(pdir / "b.jsonl", [user("y")])
    touch(a, 1_000_000)
    touch(b, 2_000_000)
    assert transcript.find_transcript(cwd=str(cwd)) == b


def test_find_skips_sdk(env):
    cwd, pdir = env
    a = write(pdir / "a.jsonl", [user("x")])
    b = write(pdir / "b.jsonl", [{"type": "user", "entrypoint": "sdk-py",
                                  "message": {"role": "user", "content": "x"}}])
    touch(a, 1_000_000)
    touch(b, 2_000_000)
    assert transcript.find_transcript(cwd=str(cwd)) == a


def test_find_skips_by_string(env):
    cwd, pdir = env
    a = write(pdir / "a.jsonl", [user("normal")])
    b = write(pdir / "b.jsonl", [user("Session supervisor boot now")])
    touch(a, 1_000_000)
    touch(b, 2_000_000)
    assert transcript.find_transcript(cwd=str(cwd), skip=("Session supervisor boot",)) == a
    assert transcript.find_transcript(cwd=str(cwd)) == b


def test_find_by_session_id(env):
    cwd, pdir = env
    sid = "12345678-aaaa-bbbb-cccc-1234567890ab"
    target = write(pdir / f"{sid}.jsonl", [user("x")])
    newer = write(pdir / "b.jsonl", [user("y")])
    touch(target, 1_000_000)
    touch(newer, 2_000_000)
    assert transcript.find_transcript(session_id=sid, cwd=str(cwd)) == target


@pytest.mark.parametrize("text", ["read that to me", "Read it out loud", "can you read your answer?",
                                  "please read that aloud", "read the last reply", "ok, read it again please"])
def test_plain_read_requests_are_skipped(text):
    assert transcript.is_read_request(text)


@pytest.mark.parametrize("text", ["read this file and fix it", "read the README", "what did you read?",
                                  "I read that article yesterday"])
def test_real_messages_are_not_read_requests(text):
    assert not transcript.is_read_request(text)


def test_last_reply_skips_plain_read_request():
    entries = [user("explain it"), asst("Here is the explanation."), user("read that to me")]
    assert transcript.last_reply(entries) == "Here is the explanation."


def test_all_and_recent_sessions(env):
    import time
    cwd, pdir = env
    old = write(pdir / "old.jsonl", [user("x")])
    new = write(pdir / "new.jsonl", [user("y")])
    bot = write(pdir / "bot.jsonl", [user("Session supervisor boot now")])
    now = time.time()
    touch(old, now - 10 * 86400)
    touch(new, now - 60)
    touch(bot, now)
    skip = ("Session supervisor boot",)
    assert transcript.all_sessions(str(cwd), skip) == [new, old]
    assert transcript.recent_sessions(str(cwd), 30, skip) == [new]


def test_picker_lists_recent_then_older(env):
    import time
    import daemon
    cwd, pdir = env
    now = time.time()
    files = []
    for i, age in enumerate([30, 5 * 86400, 6 * 86400, 7 * 86400]):
        f = write(pdir / f"s{i}.jsonl", [user(f"q{i}"), asst(f"answer {i}")])
        touch(f, now - age)
        files.append(f)
    got = daemon.sessions(str(cwd), minutes=30, older=2)
    assert [g["transcript"] for g in got] == [str(f) for f in files[:3]]
    assert [g["recent"] for g in got] == [True, False, False]
    assert got[1]["preview"].startswith("answer 1")
