$ErrorActionPreference='Stop'
$qaifPidFile=Join-Path $PSScriptRoot 'data\server.pid'
if (-not (Test-Path -LiteralPath $qaifPidFile)) { Write-Output 'No launcher-managed server found.'; exit }
& (Join-Path $PSScriptRoot '.venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'tools\stop_server.py')
if ($LASTEXITCODE) { throw 'Server identity could not be verified. Nothing was stopped.' }
