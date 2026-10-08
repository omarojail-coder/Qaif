param([string]$Python='python')
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) { & $Python -m venv .venv; if ($LASTEXITCODE) { throw 'Python 3.12+ is required.' } }
& '.\.venv\Scripts\python.exe' -m pip install -r backend\requirements.txt
if ($LASTEXITCODE) { throw 'Python dependency installation failed.' }
if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
& npm.cmd --prefix frontend ci --cache (Join-Path $PSScriptRoot '.cache\npm') --no-audit --no-fund
if ($LASTEXITCODE) { throw 'Node dependency installation failed.' }
& npm.cmd --prefix frontend run build
if ($LASTEXITCODE) { throw 'Frontend build failed.' }
Write-Output 'Ready. Run Start-Qaif.ps1.'
