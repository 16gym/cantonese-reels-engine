$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Run tools/setup.ps1 first.' }
$env:PYTHONUTF8 = '1'
& $pythonPath -m reels @args
exit $LASTEXITCODE
