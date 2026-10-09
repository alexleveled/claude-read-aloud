#!/bin/sh
# Finds uv and runs the reader through it. uv installs Python and the reader's packages
# on first use, so there is no virtualenv to manage.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

UV="$(command -v uv 2>/dev/null)"
for c in "$HOME/.local/bin/uv" "$HOME/.local/bin/uv.exe" "$HOME/.cargo/bin/uv" "$HOME/.cargo/bin/uv.exe" \
         /opt/homebrew/bin/uv /usr/local/bin/uv; do
  [ -z "$UV" ] && [ -x "$c" ] && UV="$c"
done

if [ -z "$UV" ]; then
  if [ "$1" = "session-start" ]; then
    echo "Read Aloud plugin: uv is not installed yet, so reading aloud won't work. If the user asks to read something aloud, offer to run /read-aloud:read setup."
    exit 0
  fi
  echo "Read Aloud needs uv (https://docs.astral.sh/uv/). Run /read-aloud:read setup and Claude will install it for you."
  exit 3
fi
export READ_ALOUD_UV="$UV"

if [ "$1" = "session-start" ]; then
  # Background it: the first run installs packages and may download the voice model,
  # and a SessionStart hook must never hold up the session.
  nohup "$UV" run --quiet --script "$ROOT/reader/reader.py" session-start >/dev/null 2>&1 &
  exit 0
fi
exec "$UV" run --quiet --script "$ROOT/reader/reader.py" "$@"
