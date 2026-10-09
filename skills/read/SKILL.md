---
name: read
description: Read Claude's last reply aloud with a local voice (Kokoro). Use when the user types /read-aloud:read, or says "read that to me", "read it out loud", "read the last reply", "stop reading". Arguments - none (read the final message), full (the whole last turn), stop, setup, status, voices, test, voice <name>, speed <n>, mode <final|full>, model <int8|fp16|full>.
argument-hint: "[full | stop | setup | voices | voice <name> | speed <n> | test]"
---

# Read Aloud

Every command below goes through one launcher. Write it out exactly, with the quotes:

```bash
sh "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" <command>
```

Pick the command from the user's arguments:

| User asked for | Command |
|---|---|
| nothing, or "read that" | `read --session "${CLAUDE_SESSION_ID}" --cwd "$PWD"` |
| `full` | `read --session "${CLAUDE_SESSION_ID}" --cwd "$PWD" --full` |
| `stop` | `stop` |
| `status` | `status` |
| `shutdown` | `shutdown` |
| `voices` | `voices` |
| `voice <name>` / `speed <n>` / `mode <final\|full>` / `model <int8\|fp16\|full>` | `settings <key> <value>` |
| `test` | `test` |
| `setup` | follow **Setup** below |

For `read`, `stop`, `full` and `test`: run the one command and reply with its one-line output, nothing more. The user wants to listen, not read more text. For `voices`, show the list and say how to pick one (`/read-aloud:read voice bm_daniel`).

If the output says uv is missing, or a read fails with an error, go to **Setup**.

## Setup

Walk the user through this one step at a time. Ask before installing anything.

1. Run `sh "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" doctor`.
   - **uv missing** (the launcher says so): uv is the Python tool that installs and runs the reader. Explain that, ask permission, then install it with the official installer:
     - Windows: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
     - macOS / Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`

     Run `doctor` again. The launcher also looks in `~/.local/bin`, so a new terminal isn't needed. The first run takes up to a minute while uv installs Python and the packages.
2. **`model_missing` not empty:** run `download`. Tell the user it's a one-time download of the voice model (92 MB for the default int8 model) from the kokoro-onnx GitHub release, and that it's checked against a pinned checksum.
3. **`audio_output` is null:**
   - Linux: PortAudio is usually missing. Ask, then install `libportaudio2` (Debian/Ubuntu: `sudo apt install libportaudio2`, Fedora: `sudo dnf install portaudio`).
   - Elsewhere: no output device was found. Ask the user to check that speakers or headphones are connected.
4. Run `test`. Ask the user whether they heard the voice. If not, show the `audio_error` from `doctor` and work through it with them.
5. **VS Code button:** if `vscode_cli` is set (or the user mentions Cursor or Windsurf), offer the companion extension. It adds a ▶ Read button to the status bar, Ctrl+Alt+R to read and Ctrl+Alt+S to stop, plus a session picker when several Claude sessions are running in the same folder. If the user wants it:

   ```bash
   code --install-extension "${CLAUDE_PLUGIN_ROOT}/vscode/claude-read-aloud.vsix" --force
   ```

   Use `cursor` or `windsurf` instead of `code` for those editors. Tell them to reload the window (Ctrl+Shift+P → "Developer: Reload Window").
6. **Voice and speed:** run `voices`. The default is af_heart (American, female) at 1.15x. Ask whether they want a different voice or speed and set it with `settings voice <name>` / `settings speed <n>`. Then run `test` once more so they hear the choice.

Finish with a short summary: how to read (`/read-aloud:read`, or "read that to me"), how to stop, and the VS Code shortcut if they installed it.

## Notes

- Reads go through a warm background reader that keeps the model loaded (about 280 MB) and shuts down after `warm_minutes` (default 15) without a read. `shutdown` frees it right away, and `settings warm_minutes 0` turns it off.
- Everything runs locally. Kokoro is a small open model that runs on the CPU, and no text or audio leaves the machine.
- Settings, the model and logs live in `~/.claude-voice/` (shared with the Claude Done Alerts plugin, so the model downloads once).
- To skip a background session that keeps showing up as "newest" (an always-on bot, for example), add a string from its first message to `skip_sessions` in `~/.claude-voice/read-aloud/settings.json`.
