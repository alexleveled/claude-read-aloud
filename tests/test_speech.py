import re

import speech


def lines(md):
    return speech.clean_for_speech(md).splitlines()


def test_code_block_skipped():
    out = lines("before\n```python\nsecret_value = 42\n```\nafter")
    assert "Code block skipped." in out
    assert "secret" not in "\n".join(out)


def test_table_rows():
    assert "Name: a, Size: 1." in lines("| Name | Size |\n|---|---|\n| a | 1 |")


def test_links():
    assert "reader dot py" in speech.clean_for_speech("[reader.py](reader/reader.py)")
    assert "the docs" in lines("[the docs](https://x.com/a)")[0]
    assert "x.com" not in speech.clean_for_speech("[the docs](https://x.com/a)")


def test_bare_url():
    out = speech.clean_for_speech("see https://example.com/x now")
    assert "a link" in out
    assert "example" not in out


def test_inline_slash_command():
    assert "slash read stop" in speech.clean_for_speech("run `/read stop` please")


def test_bold_italic_markers():
    out = speech.clean_for_speech("a **bold** and _it_ word")
    assert "bold" in out and "it" in out
    assert "*" not in out and "_" not in out


def test_heading():
    assert lines("## Heading") == ["Heading."]


def test_numbered_and_bullets():
    assert lines("1. First") == ["First."]
    assert lines("- item") == ["item."]


def test_speaker_line_dropped():
    out = speech.clean_for_speech("\U0001F50A Summary for the ear\nReal text here.")
    assert "Summary" not in out
    assert "Real text here." in out


def test_emoji_removed():
    out = speech.clean_for_speech("Done ✅ and shipped")
    assert "✅" not in out
    assert "Done" in out


def test_every_line_ends_with_punctuation():
    md = "# Title\n\n- one\n- two\n\n1. first\n\nplain words\n\n| A | B |\n|--|--|\n| x | y |\n"
    for line in lines(md):
        assert line[-1] in ".!?:;,"


def test_chunk_first_is_short_and_cuts_at_comma():
    text = ("This is a very long opening sentence that keeps going for quite a while, "
            "and then it continues well past the ninety character mark without stopping.")
    chunks = speech.chunk(text)
    assert chunks[0].endswith("a while,")
    assert len(chunks[0]) < 90
    assert len(chunks) >= 2


def test_chunk_limit_and_words_preserved():
    text = " ".join(f"Sentence number {i} has a handful of ordinary words in it, honestly." for i in range(60))
    chunks = speech.chunk(text)
    assert all(len(c) <= 220 for c in chunks)
    assert " ".join(chunks).split() == text.split()



def test_chunk_long_first_sentence_without_commas_is_split():
    text = " ".join(["word"] * 200) + "."
    chunks = speech.chunk(text)
    assert all(len(c) <= 220 for c in chunks)
    assert len(chunks[0]) <= 120
    assert " ".join(chunks).split() == text.split()


def test_chunk_unbroken_first_token_loses_nothing():
    text = "x" * 300
    assert "".join(speech.chunk(text)) == text
