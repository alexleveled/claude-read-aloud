# Changelog

## 0.2.0

- Warm reader: a background process keeps the voice model loaded, so a read starts speaking in under a second instead of about four. It shuts down after 15 minutes without a read (`warm_minutes`, 0 turns it off) and starts again on the next one.
- The VS Code button talks to the warm reader directly, skipping process startup entirely.
- `stop` cuts off mid-sentence instead of finishing the current chunk.
- New `shutdown` command frees the memory right away.

## 0.1.0 (unreleased)

First public release.

- `/read-aloud:read` with `full`, `stop`, `setup`, `voices`, `voice`, `speed`, `mode`, `model`, `test`
- Guided setup that installs uv, downloads the voice model and tests audio
- VS Code / Cursor / Windsurf extension: status bar button, Ctrl+Alt+R / Ctrl+Alt+S, session picker
- Windows, macOS and Linux (macOS and Linux audio not yet confirmed by a listener)
