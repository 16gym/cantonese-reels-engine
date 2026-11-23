#!/bin/sh
# One-time setup on macOS / Linux. Calls no paid service. Safe to run again.
set -e
cd "$(dirname "$0")/.."
export PYTHONUTF8=1
for tool in python3 ffmpeg ffprobe; do
  command -v "$tool" >/dev/null 2>&1 || { echo "$tool is not on PATH. Install it first (macOS: brew install python ffmpeg)."; exit 1; }
done
python3 -c 'import sys; assert sys.version_info >= (3, 12), "Python 3.12 or newer is required"'
# System packages stay visible so an existing faster-whisper install (the Cantonese listener) is reused.
[ -x .venv/bin/python ] || python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install --quiet --disable-pip-version-check -e '.[dev]'
[ -f .env ] || cp .env.example .env
.venv/bin/python -m pytest -q || { echo 'Tests failed. Do not use the engine until they pass.'; exit 1; }
.venv/bin/python -c 'from reels import speech; print("Cantonese listener:", "installed" if speech.available() else "NOT installed (captions use planned timing; your ear checks the speech). To add it: .venv/bin/python -m pip install faster-whisper")'
command -v higgsfield >/dev/null 2>&1 || echo 'Higgsfield CLI not found. Install it: npm install -g @higgsfield/cli   then: higgsfield auth login'
echo 'Setup complete. Nothing was spent. Next: tools/reels demo  (a free rehearsal of all five gates)'
