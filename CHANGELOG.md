# Changelog

## 0.3.0

- VS Code picker always opens, so you can read any session in the folder, not just ones active in the last 30 minutes. Recent sessions come first with the newest preselected (Enter reads it), then the 10 most recent older ones under Older. Before, the picker only appeared when two or more sessions had been active in the last 30 minutes, and otherwise read the newest one without asking.
- New setting `picker_older` (default 10) sets how many older sessions the picker lists.
- Picker previews are cached, so long transcripts are only parsed once.
- VS Code extension 0.5.0 (reinstall it with `/read-aloud:read setup`, or `code --install-extension` on the bundled .vsix).

## 0.2.2

- Asking in plain words ("read that to me", "read it out loud") now reads Claude's previous reply, the same as `/read-aloud:read`. Before, the request itself counted as the newest message and there was nothing to read.

## 0.2.1

- Windows: starting the warm reader no longer opens an empty terminal window. uv's Python launcher started the real interpreter without a console to inherit, so Windows gave it a visible one.

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
