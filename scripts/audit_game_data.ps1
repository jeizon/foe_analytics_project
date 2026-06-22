<# Audit all captured FoE game data and list possible modules. #>

[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Arguments
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$ScriptPath = Join-Path $ProjectRoot "scripts\audit_game_data.py"

if ($env:VIRTUAL_ENV) {
    $activePython = Join-Path $env:VIRTUAL_ENV "Scripts\python.exe"
    if (Test-Path $activePython) {
        $PythonPath = $activePython
    }
}

if (-not (Test-Path $PythonPath)) {
    throw "Python was not found in .venv. Run .\scripts\setup_dev.ps1 first."
}

Push-Location $ProjectRoot
try {
    & $PythonPath $ScriptPath @Arguments
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}

