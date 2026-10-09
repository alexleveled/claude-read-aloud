# Read Aloud for Claude Code

Claude writes you a long answer. You'd rather listen to it while you get coffee.

Read Aloud reads Claude Code's last reply out loud in a natural voice. The voice is [Kokoro](https://github.com/thewh1teagle/kokoro-onnx), a small open model that runs on your CPU, so no text or audio ever leaves your machine. No API key, no account.

- `/read-aloud:read` or just tell Claude "read that to me"
- A ▶ Read button in VS Code (and Cursor / Windsurf), with Ctrl+Alt+R to read and Ctrl+Alt+S to stop
- It reads the way you'd want it read: code blocks get skipped, tables get read row by row, `src/app.py` becomes "app dot py", and links and markdown symbols disappear
- Several Claude sessions open in one folder? The VS Code button asks which one to read

https://github.com/user-attachments/assets/f265c10a-4cf2-4ddd-90b4-9d5b9ed0e09d

*Two Claude sessions open side by side. ▶ Read asks which one to read, then reads it.*

## Install

Paste this into Claude Code:

```
Install the read-aloud plugin from the alexleveled/claude-plugins marketplace, then run /read-aloud:read setup
```

Claude adds the marketplace, installs the plugin and walks you through setup. It asks before installing anything.

Or do it yourself:

```
/plugin marketplace add alexleveled/claude-plugins
/plugin install read-aloud@alexleveled
/read-aloud:read setup
```

Setup checks for [uv](https://docs.astral.sh/uv/) (the Python tool that runs the reader) and installs it if you say yes. It also downloads the voice model (92 MB, one time), plays a test line, and offers the VS Code button.

## Use

| You type | It does |
|---|---|
| `/read-aloud:read` | reads the final message of Claude's last reply |
| `/read-aloud:read full` | reads every message in that turn, progress updates included |
| `/read-aloud:read stop` | stops |
| `/read-aloud:read voices` | lists voices |
| `/read-aloud:read voice bm_daniel` | switches voice |
| `/read-aloud:read speed 1.3` | reading speed, 0.5 to 2.0 (default 1.15) |
| `/read-aloud:read test` | plays a test line |

Natural language works too: "read that out loud", "stop reading".

In VS Code: click ▶ Read in the status bar, or press Ctrl+Alt+R. Ctrl+Alt+S stops.

## Voices

The default is `af_heart` (American, female). A few others:

| Voice | Sound |
|---|---|
| `af_bella` | American, female, bright |
| `am_michael` | American, male, steady |
| `bf_emma` | British, female, clear |
| `bm_george` | British, male, deep |
| `bm_daniel` | British, male, calm |

Kokoro ships about 50 voices across several languages; see its [voice list](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md).

## Settings

Everything lives in `~/.claude-voice/read-aloud/settings.json`. The commands above edit it for you.

| Key | Default | |
|---|---|---|
| `voice` | `af_heart` | |
| `speed` | `1.15` | |
| `mode` | `final` | `full` makes every read include the whole turn |
| `model` | `int8` | `int8` 92 MB, `fp16` 177 MB, `full` 326 MB. Same speed; the bigger ones sound slightly cleaner |
| `warm_minutes` | `15` | how long the voice model stays loaded after a read. `0` loads it fresh every time |
| `skip_sessions` | `[]` | text from the first message of sessions to never read, like an always-on bot that would otherwise always be "newest" |

## How it works

When you ask for a read, the plugin finds the current session's transcript under `~/.claude/projects/`. It takes Claude's reply to your last message and cleans the markdown into speakable sentences. Then it hands the text to a background process that keeps the voice model loaded and generates each sentence while the previous one plays. With the model already loaded, the first word comes in under a second, even for a long reply.

That background process uses about 280 MB of memory while it's loaded. It shuts itself down after 15 minutes without a read, and the next read starts it again, which takes about five seconds that one time. Change the timeout with `warm_minutes`, or run `/read-aloud:read shutdown` to free the memory right away.

Claude Code's transcript format isn't a public API. If an update changes it, Read Aloud says so instead of reading the wrong thing. Please [open an issue](https://github.com/alexleveled/claude-read-aloud/issues) if you see that message.

The model comes from the [kokoro-onnx releases](https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0) and gets checked against a pinned SHA-256 before use.

## Platforms

Built and tested on Windows. macOS and Linux should work, and the tests run on all three in CI, but nobody has heard audio play on them yet. If you try it, an issue saying "works on my Mac" helps a lot. On Linux, audio needs PortAudio (`sudo apt install libportaudio2`); setup handles it.

## Also by me

**[Claude Done Alerts](https://github.com/alexleveled/claude-done-alerts)**: Claude tells you out loud when it finishes a task or needs your approval, with the project name and a one-line summary of how it went. Uses the same voice model, so it downloads once.

## Uninstall

```
/plugin uninstall read-aloud@alexleveled
```

Then delete `~/.claude-voice/` if you don't use Done Alerts, and uninstall the VS Code extension if you added it.

## License

MIT. Kokoro is Apache 2.0.
