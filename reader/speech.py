"""Turning a markdown reply into something pleasant to listen to, and cutting it into chunks.

Code blocks are skipped (announced, not read), tables are read row by row, links become
their text, file paths become "name dot ext", slash commands become "slash name", and
markdown symbols and emoji are dropped. Every line ends up as its own sentence so headings
and bullets get a natural pause.
"""
import re

FILE_EXT = (r"(?:py|js|mjs|cjs|ts|tsx|jsx|json|md|txt|html|css|scss|sh|ps1|yml|yaml|toml|ini|cfg|"
            r"wav|mp3|mp4|png|jpg|jpeg|gif|svg|pdf|csv|db|sql|jsonl|env|cmd|bat|go|rs|rb|java|"
            r"kt|swift|c|h|cpp|hpp|cs|php|lock|vsix|zip)")


def speak_filename(name):
    name = name.rstrip("/\\").replace("\\", "/").split("/")[-1]
    name = re.sub(r":\d+(?:-\d+)?$", "", name)  # file.py:42 -> file.py
    base, dot, ext = name.rpartition(".")
    if dot and base:
        return f"{base.replace('_', ' ').replace('-', ' ')} dot {ext}"
    return name.replace("_", " ").replace("-", " ")


def _inline_code(m):
    code = m.group(1).strip()
    if re.fullmatch(r"/[\w:-]+(?: .{0,40})?", code):  # slash command, e.g. /read stop
        return "slash " + code[1:].replace("-", " ").replace(":", " ")
    if re.search(r"[/\\]", code) or re.fullmatch(rf"[\w.-]+\.{FILE_EXT}(?::\d+)?", code, re.I):
        return speak_filename(code)
    return code if len(code) <= 40 else "code"


def _table(rows):
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    cells = [r for r in cells if not all(re.fullmatch(r":?-{2,}:?", c or "-") for c in r)]
    if not cells:
        return ""
    header, body = cells[0], cells[1:]
    out = []
    for r in body:
        parts = [f"{h}: {v}" if h else v for h, v in zip(header, r) if v]
        if parts:
            out.append(", ".join(parts) + ".")
    return "\n".join(out)


def clean_for_speech(md):
    out, table, in_code = [], [], False
    for line in md.splitlines():
        s = line.strip()
        if s.startswith(("```", "~~~")):
            if not in_code:
                out.append("Code block skipped.")
            in_code = not in_code
            continue
        if in_code:
            continue
        if s.startswith("|"):
            table.append(s)
            continue
        if table:
            out.append(_table(table))
            table = []
        if s.startswith("🔊"):  # the spoken summary line Claude Done Alerts asks for
            continue
        out.append(line)
    if table:
        out.append(_table(table))

    t = "\n".join(out)
    t = re.sub(r"<!--.*?-->", "", t, flags=re.S)                                   # html comments
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", t)                                     # images
    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", lambda m: (
        speak_filename(m.group(1)) if re.search(rf"\.{FILE_EXT}(?::\d+(?:-\d+)?)?$|[/\\]", m.group(1), re.I)
        else m.group(1)), t)                                                       # links -> text
    t = re.sub(r"https?://\S+", "a link", t)
    t = re.sub(r"`([^`]+)`", _inline_code, t)
    t = re.sub(r"(?<![\w.])(?:[A-Za-z]:)?(?:[\w.~-]+[/\\])+[\w.-]+", lambda m: speak_filename(m.group(0)), t)
    t = re.sub(rf"\b([\w-]+)\.({FILE_EXT})\b", lambda m: f"{m.group(1)} dot {m.group(2)}", t, flags=re.I)
    t = re.sub(r"(?m)^\s{0,3}#{1,6}\s*(.+?)\s*#*\s*$", r"\1.", t)                 # headings
    t = re.sub(r"(?m)^\s*(?:[-*_]\s*){3,}$", "", t)                                # horizontal rules
    t = re.sub(r"(?m)^(\s*)[-*+]\s+(?:\[[ xX]\]\s+)?", r"\1", t)                    # bullets, checkboxes
    t = re.sub(r"(\*\*|__|\*|_|~~)(?=\S)(.+?)(?<=\S)\1", r"\2", t)                  # bold/italic
    t = re.sub(r"(?m)^\s*\d+[.)]\s+", "", t)                                       # numbered items
    t = re.sub(r"(?m)^\s*>\s?", "", t)                                             # quotes
    for a, b in (("→", " to "), ("←", " from "), ("≈", " about "), ("&", " and "), ("~", " about "),
                 ("×", " times "), ("—", ", "), ("–", " to "), ("…", "..."), ("≥", " at least "),
                 ("≤", " at most ")):
        t = t.replace(a, b)
    t = re.sub(r"[\U0001F000-\U0001FAFF☀-➿️■-◿⬀-⯿]", "", t)  # emoji
    t = re.sub(r"[*#|`<>]", "", t)

    sentences = []
    for line in t.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        if line[-1] not in ".!?:;,":
            line += "."
        sentences.append(line)
    return "\n".join(sentences)


def chunk(text, limit=220):
    """Sentence-sized pieces of at most `limit` characters. The first piece is kept short
    (cut at a comma if the first sentence is long) so audio starts in about a second, and
    the bigger chunks are generated while it plays."""
    parts = []
    for line in text.splitlines():
        parts.extend(p for p in re.split(r"(?<=[.!?;:])\s+", line) if p.strip())
    chunks, cur = [], ""
    if parts:
        p = parts.pop(0)
        cut = p.find(", ", 50, limit) if len(p) > 90 else -1
        if cut > 0:
            head, rest = p[:cut + 1], p[cut + 2:]
        elif len(p) > limit:  # long and no comma: cut at a word break instead
            space = p.rfind(" ", 50, 120)
            head, rest = (p[:space], p[space + 1:]) if space > 0 else (p[:120], p[120:])
        else:
            head, rest = p, ""
        if rest.strip():
            parts.insert(0, rest)
        chunks.append(head)
    for p in parts:
        while len(p) > limit:
            cut = p.rfind(", ", 0, limit)
            cut = cut + 1 if cut > 40 else limit
            chunks.append(p[:cut].strip())
            p = p[cut:].strip()
        if cur and len(cur) + len(p) + 1 > limit:
            chunks.append(cur)
            cur = p
        else:
            cur = f"{cur} {p}".strip()
    if cur:
        chunks.append(cur)
    return chunks
