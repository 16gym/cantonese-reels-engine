# One-time setup. Calls no paid service. Safe to run again.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectRoot
try {
    $env:PYTHONUTF8 = '1'
    foreach ($tool in 'python', 'ffmpeg', 'ffprobe') {
        if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "$tool is not on PATH. Install it first." }
    }
    & python -c 'import sys; assert sys.version_info >= (3, 12), "Python 3.12 or newer is required"'
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 or newer is required' }
    if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
        # System packages stay visible so an existing faster-whisper install (the Cantonese listener) is reused.
        & python -m venv --system-site-packages .venv
        if ($LASTEXITCODE -ne 0) { throw 'Could not create .venv' }
    }
    & .venv/Scripts/python.exe -m pip install --quiet --disable-pip-version-check -e '.[dev]'
    if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }
    if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
    & .venv/Scripts/python.exe -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed. Do not use the engine until they pass.' }
    & .venv/Scripts/python.exe -c 'from reels import speech; print("Cantonese listener:", "installed" if speech.available() else "NOT installed (captions use planned timing; your ear checks the speech). To add it: .venv/Scripts/python.exe -m pip install faster-whisper")'
    if (-not (Get-Command higgsfield -ErrorAction SilentlyContinue)) { Write-Output 'Higgsfield CLI not found. Install it: npm install -g @higgsfield/cli   then: higgsfield auth login' }
    Write-Output 'Setup complete. Nothing was spent. Next: tools/reels.ps1 demo  (a free rehearsal of all five gates)'
} finally {
    Pop-Location
}
