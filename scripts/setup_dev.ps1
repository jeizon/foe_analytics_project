<# 
FoE Python Analytics Dashboard - development environment setup.

Usage:
  powershell -ExecutionPolicy Bypass -File .\scripts\setup_dev.ps1

Options:
  -SkipToolInstall       Only verify external tools; do not install missing tools.
  -SkipDockerStart      Do not try to start Docker Desktop.
  -NoStartPostgres      Do not run docker compose up -d.
  -ReinstallPackages    Reinstall Python dependencies even when the venv exists.
#>

[CmdletBinding()]
param(
    [switch]$SkipToolInstall,
    [switch]$SkipDockerStart,
    [switch]$NoStartPostgres,
    [switch]$ReinstallPackages
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$VenvPath = Join-Path $ProjectRoot ".venv"
$RequirementsPath = Join-Path $ProjectRoot "requirements.txt"
$EnvPath = Join-Path $ProjectRoot ".env"
$MinimumPythonVersion = [version]"3.11.0"
$MaximumPythonVersionExclusive = [version]"3.14.0"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Ok {
    param([string]$Message)
    Write-Host "OK  $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "WARN $Message" -ForegroundColor Yellow
}

function Write-Fail {
    param([string]$Message)
    Write-Host "FAIL $Message" -ForegroundColor Red
}

function Test-Command {
    param([string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Refresh-EnvironmentPath {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machinePath;$userPath"
}

function Invoke-NativeQuiet {
    param(
        [string]$Command,
        [string[]]$Arguments = @()
    )

    $previousErrorActionPreference = $ErrorActionPreference
    $previousNativePreference = $null
    $hasNativePreference = $false

    if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -Scope Global -ErrorAction SilentlyContinue) {
        $hasNativePreference = $true
        $previousNativePreference = $global:PSNativeCommandUseErrorActionPreference
        $global:PSNativeCommandUseErrorActionPreference = $false
    }

    try {
        $ErrorActionPreference = "Continue"
        $output = & $Command @Arguments 2>$null
        return @{
            ExitCode = $LASTEXITCODE
            Output = $output
        }
    }
    catch {
        return @{
            ExitCode = 1
            Output = $null
        }
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
        if ($hasNativePreference) {
            $global:PSNativeCommandUseErrorActionPreference = $previousNativePreference
        }
    }
}

function Invoke-WingetInstall {
    param(
        [string]$PackageId,
        [string]$DisplayName
    )

    if ($SkipToolInstall) {
        throw "$DisplayName is missing. Run again without -SkipToolInstall or install it manually."
    }

    if (-not (Test-Command "winget")) {
        throw "winget is not available. Install App Installer from Microsoft Store, then run this script again."
    }

    Write-Step "Installing $DisplayName"
    winget install --id $PackageId --exact --source winget --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "winget failed to install $DisplayName."
    }
    Refresh-EnvironmentPath
}

function Test-CompatiblePythonVersion {
    param([version]$Version)
    return $Version -ge $MinimumPythonVersion -and $Version -lt $MaximumPythonVersionExclusive
}

function Get-PythonExecutableVersion {
    param(
        [string]$Command,
        [string[]]$Arguments = @()
    )

    $versionCheck = Invoke-NativeQuiet `
        -Command $Command `
        -Arguments @($Arguments + @("-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"))

    $versionLine = $versionCheck.Output | Select-Object -First 1
    if ($versionCheck.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace([string]$versionLine)) {
        return $null
    }

    return [version]([string]$versionLine).Trim()
}

function Get-PythonCommand {
    $candidates = @(
        @{ Command = "py"; Arguments = @("-3.12") },
        @{ Command = "py"; Arguments = @("-3.11") },
        @{ Command = "python"; Arguments = @() },
        @{ Command = "python3"; Arguments = @() }
    )

    foreach ($candidate in $candidates) {
        if (-not (Test-Command $candidate.Command)) {
            continue
        }

        $version = Get-PythonExecutableVersion -Command $candidate.Command -Arguments $candidate.Arguments
        if (-not $version) {
            continue
        }

        if (Test-CompatiblePythonVersion -Version $version) {
            return @{
                Command = $candidate.Command
                Arguments = $candidate.Arguments
                Version = $version.ToString()
            }
        }
    }

    return $null
}

function Ensure-Git {
    Write-Step "Checking Git"
    if (Test-Command "git") {
        $version = git --version
        Write-Ok $version
        return
    }

    Invoke-WingetInstall -PackageId "Git.Git" -DisplayName "Git"

    if (-not (Test-Command "git")) {
        throw "Git installation finished, but git is still not available in PATH. Open a new terminal and run again."
    }
    Write-Ok (git --version)
}

function Ensure-Python {
    Write-Step "Checking Python 3.11-3.13"
    $python = Get-PythonCommand
    if ($python) {
        Write-Ok "Python $($python.Version)"
        return $python
    }

    Invoke-WingetInstall -PackageId "Python.Python.3.12" -DisplayName "Python 3.12"
    $python = Get-PythonCommand
    if (-not $python) {
        throw "Python installation finished, but Python 3.11-3.13 is still not available. Open a new terminal and run again."
    }

    Write-Ok "Python $($python.Version)"
    return $python
}

function Ensure-Docker {
    Write-Step "Checking Docker"
    if (-not (Test-Command "docker")) {
        Invoke-WingetInstall -PackageId "Docker.DockerDesktop" -DisplayName "Docker Desktop"
    }

    if (-not (Test-Command "docker")) {
        throw "Docker installation finished, but docker is still not available in PATH. Open a new terminal and run again."
    }

    if (-not $SkipDockerStart) {
        Start-DockerDesktop
    }

    docker compose version | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose plugin is not available. Update Docker Desktop and run again."
    }
}

function Start-DockerDesktop {
    Write-Step "Checking Docker daemon"
    if (Test-DockerDaemon) {
        Write-Ok "Docker daemon is running"
        return
    }

    $dockerDesktopPath = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
    if (Test-Path $dockerDesktopPath) {
        Write-Warn "Starting Docker Desktop. This can take a minute."
        Start-Process -FilePath $dockerDesktopPath -WindowStyle Hidden
    }
    else {
        Write-Warn "Docker Desktop executable was not found. Start Docker Desktop manually if the next check times out."
    }

    $deadline = (Get-Date).AddMinutes(5)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 5
        if (Test-DockerDaemon) {
            Write-Ok "Docker daemon is running"
            return
        }
        Write-Host "." -NoNewline
    }

    Write-Host ""
    throw "Docker daemon did not become ready. Open Docker Desktop, finish any first-run prompts, then run this script again."
}

function Test-DockerDaemon {
    $result = Invoke-NativeQuiet -Command "docker" -Arguments @("info")
    return $result.ExitCode -eq 0
}

function Ensure-VirtualEnvironment {
    param([hashtable]$Python)

    Write-Step "Preparing Python virtual environment"
    $venvPython = Join-Path $VenvPath "Scripts\python.exe"

    if (Test-Path $venvPython) {
        $venvVersion = Get-PythonExecutableVersion -Command $venvPython
        if (-not $venvVersion -or -not (Test-CompatiblePythonVersion -Version $venvVersion)) {
            Write-Warn "Existing virtual environment is missing or uses an incompatible Python. Recreating .venv."
            Remove-Item -LiteralPath $VenvPath -Recurse -Force
        }
        else {
            Write-Ok "Virtual environment: $VenvPath (Python $venvVersion)"
            return $venvPython
        }
    }

    if (-not (Test-Path $venvPython)) {
        & $Python.Command @($Python.Arguments) -m venv $VenvPath
        if ($LASTEXITCODE -ne 0) {
            throw "Could not create Python virtual environment."
        }
    }

    Write-Ok "Virtual environment: $VenvPath"
    return $venvPython
}

function Install-PythonPackages {
    param([string]$VenvPython)

    Write-Step "Installing Python dependencies"
    & $VenvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) {
        throw "Could not upgrade pip."
    }

    if ($ReinstallPackages) {
        & $VenvPython -m pip install --upgrade --force-reinstall -r $RequirementsPath
    }
    else {
        & $VenvPython -m pip install --upgrade -r $RequirementsPath
    }

    if ($LASTEXITCODE -ne 0) {
        throw "Could not install Python dependencies."
    }

    Write-Ok "Python dependencies installed"
}

function Ensure-EnvFile {
    Write-Step "Checking .env"
    if (Test-Path $EnvPath) {
        Write-Ok ".env already exists"
        return
    }

    @"
POSTGRES_DB=foe_analytics
POSTGRES_USER=foe_analytics
POSTGRES_PASSWORD=foe_analytics_dev
POSTGRES_PORT=5432
DATABASE_URL=postgresql+asyncpg://foe_analytics:foe_analytics_dev@localhost:5432/foe_analytics
"@ | Set-Content -Path $EnvPath -Encoding UTF8

    Write-Ok ".env created"
}

function Start-Postgres {
    if ($NoStartPostgres) {
        Write-Warn "Skipping PostgreSQL startup because -NoStartPostgres was provided"
        return
    }

    Write-Step "Starting PostgreSQL with Docker Compose"
    Push-Location $ProjectRoot
    try {
        docker compose up -d postgres
        if ($LASTEXITCODE -ne 0) {
            throw "docker compose up failed."
        }
    }
    finally {
        Pop-Location
    }

    Write-Ok "PostgreSQL container requested"
}

function Test-ProjectCommands {
    param([string]$VenvPython)

    Write-Step "Verifying project commands"
    $scriptsPath = Join-Path $VenvPath "Scripts"
    $mitmproxy = Join-Path $scriptsPath "mitmproxy.exe"
    $streamlit = Join-Path $scriptsPath "streamlit.exe"

    if (-not (Test-Path $mitmproxy)) {
        throw "mitmproxy was not found in the virtual environment."
    }
    if (-not (Test-Path $streamlit)) {
        throw "streamlit was not found in the virtual environment."
    }

    & $VenvPython -c "import asyncpg, mitmproxy, sqlalchemy, streamlit; print('imports ok')"
    if ($LASTEXITCODE -ne 0) {
        throw "Python dependency import check failed."
    }

    Write-Ok "mitmproxy, Streamlit, SQLAlchemy and asyncpg are ready"
}

function Show-NextSteps {
    $activate = Join-Path $VenvPath "Scripts\Activate.ps1"
    $mitmproxy = Join-Path $VenvPath "Scripts\mitmproxy.exe"
    $streamlit = Join-Path $VenvPath "Scripts\streamlit.exe"
    Write-Host ""
    Write-Host "Development environment is ready." -ForegroundColor Green
    Write-Host ""
    Write-Host "Recommended commands:"
    Write-Host "  cd `"$ProjectRoot`""
    Write-Host "  powershell -ExecutionPolicy Bypass -File .\scripts\run_proxy.ps1"
    Write-Host "    CBG, player_core, wallet_tracker and game_state are enabled by default."
    Write-Host "  powershell -ExecutionPolicy Bypass -File .\scripts\run_dashboard.ps1"
    Write-Host "  powershell -ExecutionPolicy Bypass -File .\scripts\validate_capture.ps1"
    Write-Host "  powershell -ExecutionPolicy Bypass -File .\scripts\inspect_capture.ps1"
    Write-Host "  powershell -ExecutionPolicy Bypass -File .\scripts\reprocess_game_state.ps1"
    Write-Host "  powershell -ExecutionPolicy Bypass -File .\scripts\reprocess_consolidated.ps1"
    Write-Host "  powershell -ExecutionPolicy Bypass -File .\scripts\audit_game_data.ps1"
    Write-Host "  powershell -ExecutionPolicy Bypass -File .\scripts\reprocess_cbg.ps1"
    Write-Host ""
    Write-Host "If you prefer activating .venv manually:"
    Write-Host "  . `"$activate`""
    Write-Host "  `"$mitmproxy`" -s proxy_interceptor/mitm_addon.py"
    Write-Host "  `"$streamlit`" run dashboard_ui/main_app.py"
}

try {
    Write-Step "FoE Analytics setup started"
    Push-Location $ProjectRoot

    Ensure-Git
    $python = Ensure-Python
    Ensure-Docker
    Ensure-EnvFile
    $venvPython = Ensure-VirtualEnvironment -Python $python
    Install-PythonPackages -VenvPython $venvPython
    Start-Postgres
    Test-ProjectCommands -VenvPython $venvPython
    Show-NextSteps
}
catch {
    Write-Host ""
    Write-Fail $_.Exception.Message
    Write-Host "Setup did not finish. Fix the message above and run the script again." -ForegroundColor Yellow
    exit 1
}
finally {
    Pop-Location
}
