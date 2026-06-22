<# Validate whether FoE Analytics is currently capturing game traffic. #>

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$ValidationScript = Join-Path $ProjectRoot "scripts\validate_capture.py"

if ($env:VIRTUAL_ENV) {
    $activePython = Join-Path $env:VIRTUAL_ENV "Scripts\python.exe"
    if (Test-Path $activePython) {
        $PythonPath = $activePython
    }
}

function Write-Check {
    param(
        [string]$Name,
        [bool]$Ok,
        [string]$Details = ""
    )

    if ($Ok) {
        Write-Host "OK   $Name $Details" -ForegroundColor Green
    }
    else {
        Write-Host "FAIL $Name $Details" -ForegroundColor Red
    }
}

function Test-TcpPort {
    param(
        [string]$HostName,
        [int]$Port,
        [int]$TimeoutMs = 1000
    )

    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $asyncResult = $client.BeginConnect($HostName, $Port, $null, $null)
        $connected = $asyncResult.AsyncWaitHandle.WaitOne($TimeoutMs, $false)
        if (-not $connected) {
            return $false
        }
        $client.EndConnect($asyncResult)
        return $true
    }
    catch {
        return $false
    }
    finally {
        $client.Close()
    }
}

function Test-VenvPython {
    if (-not (Test-Path $PythonPath)) {
        return $false
    }

    try {
        $previousErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        & $PythonPath -c "import sys; print(sys.version)" *> $null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

Write-Host ""
Write-Host "FoE Analytics capture validation" -ForegroundColor Cyan
Write-Host ""

$proxySettings = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
$proxyEnableValue = 0
if ($null -ne $proxySettings.ProxyEnable) {
    $proxyEnableValue = [int]$proxySettings.ProxyEnable
}
$proxyEnabled = $proxyEnableValue -eq 1
$proxyServer = [string]$proxySettings.ProxyServer
$proxyLooksRight = $proxyEnabled -and $proxyServer -match "127\.0\.0\.1(:|=)8080|http=127\.0\.0\.1:8080"

Write-Check "Windows proxy" $proxyLooksRight "enabled=$proxyEnabled server='$proxyServer'"
Write-Check "mitmproxy port 8080" (Test-TcpPort -HostName "127.0.0.1" -Port 8080)
Write-Check "PostgreSQL port 5432" (Test-TcpPort -HostName "127.0.0.1" -Port 5432)
Write-Check "Streamlit port 8501" (Test-TcpPort -HostName "127.0.0.1" -Port 8501)

$venvOk = Test-VenvPython
Write-Check ".venv Python" $venvOk $PythonPath

if (-not $venvOk) {
    Write-Host ""
    Write-Host "The virtual environment is broken or missing. Run:" -ForegroundColor Yellow
    Write-Host "  powershell -ExecutionPolicy Bypass -File .\scripts\setup_dev.ps1"
    exit 1
}

Write-Host ""
Write-Host "Database capture counters" -ForegroundColor Cyan
Push-Location $ProjectRoot
try {
    & $PythonPath $ValidationScript
    $dbExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

Write-Host ""
if (-not $proxyLooksRight) {
    Write-Host "Verdict: Chrome is not currently configured to send traffic to mitmproxy." -ForegroundColor Yellow
}
elseif (-not (Test-TcpPort -HostName "127.0.0.1" -Port 8080)) {
    Write-Host "Verdict: mitmproxy is not running on 127.0.0.1:8080." -ForegroundColor Yellow
}
elseif ($dbExitCode -ne 0) {
    Write-Host "Verdict: database validation failed." -ForegroundColor Yellow
}
else {
    Write-Host "Verdict: checks completed. See CAPTURE_STATUS above for database ingestion." -ForegroundColor Green
}
