param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$qaifRoot = $PSScriptRoot
$qaifPython = Join-Path $qaifRoot '.venv\Scripts\python.exe'
$qaifData = Join-Path $qaifRoot 'data'
if (-not (Test-Path -LiteralPath $qaifPython)) { throw 'Run Setup-Qaif.ps1 first.' }
if (-not (Test-Path -LiteralPath (Join-Path $qaifRoot 'frontend\dist\index.html'))) { throw 'Frontend is missing. Run Setup-Qaif.ps1.' }
New-Item -ItemType Directory -Force -Path $qaifData | Out-Null
$qaifUrl = 'http://127.0.0.1:8765'
$qaifReady = $false
try {
  $qaifHealth = Invoke-RestMethod -Uri "$qaifUrl/api/health" -TimeoutSec 2
  if ($qaifHealth.app -ne 'QAIF') { throw 'Port 8765 is occupied by another application.' }
  $qaifReady = $true
} catch { if ($_.Exception.Message -like '*another application*') { throw } }
if (-not $qaifReady) {
  $qaifServer = Start-Process -FilePath $qaifPython -ArgumentList '-m','uvicorn','backend.app:app','--host','127.0.0.1','--port','8765' -WorkingDirectory $qaifRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $qaifData 'server.log') -RedirectStandardError (Join-Path $qaifData 'server-error.log') -PassThru
  $qaifServer.Id | Set-Content -LiteralPath (Join-Path $qaifData 'server.pid')
  for ($qaifAttempt=0; $qaifAttempt -lt 30; $qaifAttempt++) {
    Start-Sleep -Milliseconds 300
    try { $qaifHealth=Invoke-RestMethod -Uri "$qaifUrl/api/health" -TimeoutSec 1; if ($qaifHealth.app -eq 'QAIF') { $qaifReady=$true; break } } catch {}
  }
}
if (-not $qaifReady) { throw 'QAIF did not start. See data/server-error.log.' }
if (-not $NoBrowser) { Start-Process $qaifUrl }
Write-Output "QAIF is ready: $qaifUrl"
