param([switch]$ServerOnly)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'env.ps1')
$studioUrl = 'http://127.0.0.1:57846'
try {
    $response = Invoke-WebRequest "$studioUrl/api/state" -UseBasicParsing -TimeoutSec 2
    if ($response.StatusCode -eq 200) {
        $studioState = $response.Content | ConvertFrom-Json
        if ($studioState.active -or $studioState.global_busy -or $studioState.version -ge 52) { if (-not $ServerOnly) { Start-Process $studioUrl }; exit 0 }
        $oldStudioPid = [int](Get-Content (Join-Path $PSScriptRoot 'studio.pid') -Raw)
        $oldStudio = Get-CimInstance Win32_Process -Filter "ProcessId = $oldStudioPid"
        $expectedScript = Join-Path $PSScriptRoot 'studio.py'
        if ($oldStudio.CommandLine.Contains($expectedScript)) {
            & taskkill.exe /PID $oldStudioPid /T /F | Out-Null
        } else { throw 'Existing Studio identity does not match; restart was not attempted.' }
    }
} catch {}
$studioPython = Join-Path $PSScriptRoot 'runtime/envs/unified/Scripts/python.exe'
$studioProcess = Start-Process -FilePath $studioPython -ArgumentList '-B','-u',(Join-Path $PSScriptRoot 'studio.py') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot 'logs/studio.log') -RedirectStandardError (Join-Path $PSScriptRoot 'logs/studio.err.log') -PassThru
$studioProcess.Id | Set-Content (Join-Path $PSScriptRoot 'studio.pid')
for ($attempt=0; $attempt -lt 20; $attempt++) {
    Start-Sleep -Milliseconds 500
    try {
        $response=Invoke-WebRequest "$studioUrl/api/state" -UseBasicParsing -TimeoutSec 1
        if ($response.StatusCode -eq 200) { if (-not $ServerOnly) { Start-Process $studioUrl }; exit 0 }
    } catch {}
}
throw "Studio did not start. Check freevideo-trial/logs/studio.err.log."
