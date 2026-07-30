param(
    [int]$BackendPort = 8002,
    [int]$FrontendPort = 5173,
    [switch]$NoOpen
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$FrontendDir = Join-Path $Root "frontend"
$BackendOut = Join-Path $Root "backend-dev-8002.out.log"
$BackendErr = Join-Path $Root "backend-dev-8002.err.log"
$FrontendOut = Join-Path $Root "frontend-dev-5173.out.log"
$FrontendErr = Join-Path $Root "frontend-dev-5173.err.log"
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

function Wait-Url {
    param(
        [string]$Url,
        [int]$Seconds = 60
    )

    for ($i = 0; $i -lt $Seconds; $i++) {
        try {
            Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2 | Out-Null
            return $true
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    return $false
}

function Ensure-BackendDeps {
    $check = 'import importlib.util,sys; missing=[m for m in ["fastapi","uvicorn","pydantic_settings","numpy","httpx","fitz"] if importlib.util.find_spec(m) is None]; print(",".join(missing)); sys.exit(1 if missing else 0)'
    $missing = (& py -3.11 -c $check) -join ""
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Installing backend dependencies: $missing"
        & py -3.11 -m pip install -e ".[rag,xfyun]"
        if ($LASTEXITCODE -ne 0) {
            throw "Backend dependency install failed."
        }
    }
}

function Ensure-LocalApiKey {
    $envPath = Join-Path $Root ".env"
    if (-not (Test-Path -LiteralPath $envPath)) {
        Copy-Item -LiteralPath (Join-Path $Root ".env.example") -Destination $envPath
    }
    $match = Select-String -LiteralPath $envPath -Pattern '^APP_API_KEY=(.+)$' |
        Select-Object -First 1
    $current = if ($match) { $match.Matches[0].Groups[1].Value.Trim() } else { "" }
    if (-not $current -or $current -eq "replace-with-a-long-local-token") {
        $bytes = New-Object byte[] 32
        $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
        $rng.GetBytes($bytes)
        $rng.Dispose()
        $current = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
        $content = Get-Content -LiteralPath $envPath
        if ($match) {
            $content = $content | ForEach-Object {
                if ($_ -match '^APP_API_KEY=') { "APP_API_KEY=$current" } else { $_ }
            }
            Set-Content -LiteralPath $envPath -Value $content -Encoding UTF8
        } else {
            Add-Content -LiteralPath $envPath -Value "`nAPP_API_KEY=$current" -Encoding UTF8
        }
        Write-Host "Generated a local APP_API_KEY in .env."
    }
    $env:APP_API_KEY = $current
    return $current
}

function Ensure-FrontendDeps {
    if (-not (Test-Path (Join-Path $FrontendDir "node_modules"))) {
        Write-Host "Installing frontend dependencies..."
        Push-Location $FrontendDir
        try {
            & npm install
            if ($LASTEXITCODE -ne 0) {
                throw "Frontend dependency install failed."
            }
        } finally {
            Pop-Location
        }
    }
}

Set-Location $Root

Write-Host "Preparing CS Gap Assist dev server..."
Ensure-BackendDeps
Ensure-FrontendDeps
$localApiKey = Ensure-LocalApiKey

Write-Host "Releasing ports $BackendPort and $FrontendPort..."
Stop-Port -Port $BackendPort
Stop-Port -Port $FrontendPort
Start-Sleep -Seconds 2

Remove-Item -LiteralPath $BackendOut, $BackendErr, $FrontendOut, $FrontendErr -ErrorAction SilentlyContinue

Write-Host "Starting backend on 127.0.0.1:$BackendPort..."
$backend = Start-Process `
    -FilePath "py" `
    -ArgumentList @("-3.11", "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "$BackendPort") `
    -WorkingDirectory $Root `
    -WindowStyle Hidden `
    -RedirectStandardOutput $BackendOut `
    -RedirectStandardError $BackendErr `
    -PassThru

Write-Host "Starting frontend on 127.0.0.1:$FrontendPort..."
$frontend = Start-Process `
    -FilePath "npm.cmd" `
    -ArgumentList @("run", "dev", "--", "--host", "127.0.0.1", "--port", "$FrontendPort") `
    -WorkingDirectory $FrontendDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput $FrontendOut `
    -RedirectStandardError $FrontendErr `
    -PassThru

@{
    backend = $backend.Id
    frontend = $frontend.Id
    backendPort = $BackendPort
    frontendPort = $FrontendPort
    url = "http://localhost:$FrontendPort/"
} | ConvertTo-Json | Set-Content -LiteralPath $PidFile -Encoding UTF8

$healthUrl = "http://127.0.0.1:$FrontendPort/api/v1/health/live"
if (-not (Wait-Url -Url $healthUrl -Seconds 90)) {
    Write-Host "Startup did not become healthy in time."
    Write-Host "Backend log:  $BackendErr"
    Write-Host "Frontend log: $FrontendOut"
    exit 1
}

$url = "http://localhost:$FrontendPort/"
Write-Host "Ready: $url"
Write-Host "Backend PID:  $($backend.Id)"
Write-Host "Frontend PID: $($frontend.Id)"
Write-Host "Local API Key (enter in the browser): $localApiKey"
Write-Host "Logs:"
Write-Host "  $BackendErr"
Write-Host "  $BackendOut"
Write-Host "  $FrontendErr"
Write-Host "  $FrontendOut"

if (-not $NoOpen) {
    Start-Process $url
}
