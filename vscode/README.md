# Claude Read Aloud

Adds a ▶ Read button to the VS Code status bar that reads Claude Code's last reply out loud. The voice is natural and runs locally (Kokoro), so nothing leaves your machine.

## Requires the Read Aloud Claude Code plugin

Install it from inside Claude Code:

```
/plugin marketplace add alexleveled/claude-plugins
/plugin install read-aloud@alexleveled
```

Then start a new Claude Code session once so the plugin can register itself.

## Usage

- Ctrl+Alt+R reads the last reply.
- Ctrl+Alt+S stops.
- Or click the ▶ Read button in the status bar.

If more than one Claude session in the open folder replied in the last 30 minutes, a picker lets you choose which one to read.

## Settings

- `claudeReadAloud.readerScript`: path to the reader script. Optional, normally empty.
- `claudeReadAloud.uvPath`: path to the uv executable. Optional, normally empty.

## Source

https://github.com/alexleveled/claude-read-aloud
