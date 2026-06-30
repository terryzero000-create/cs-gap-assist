$ErrorActionPreference = "SilentlyContinue"
$Root = $PSScriptRoot
$PidFile = Join-Path $Root ".dev-pids.json"

function Stop-Port {
    param([int]$Port)

    $pids = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalPort -eq $Port } |
        Select-Object -ExpandProperty OwningProcess -Unique

    foreach ($processId in $pids) {
        if ($processId -and $processId -ne $PID) {
            Stop-Process -Id $processId -ErrorAction SilentlyContinue
        }
    }
}

if (Test-Path $PidFile) {
    $data = Get-Content -Raw -LiteralPath $PidFile | ConvertFrom-Json
    Stop-Process -Id $data.backend -ErrorAction SilentlyContinue
    Stop-Process -Id $data.frontend -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $PidFile -ErrorAction SilentlyContinue
}

Stop-Port -Port 8002
Stop-Port -Port 5173
Write-Host "Stopped CS Gap Assist dev server."
