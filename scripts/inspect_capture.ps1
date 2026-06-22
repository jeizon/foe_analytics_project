<# Inspect captured FoE traffic from the local PostgreSQL database. #>

[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Arguments
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$ScriptPath = Join-Path $ProjectRoot "scripts\inspect_capture.py"

if ($env:VIRTUAL_ENV) {
    $activePython = Join-Path $env:VIRTUAL_ENV "Scripts\python.exe"
    if (Test-Path $activePython) {
        $PythonPath = $activePython
    }
}

if (-not (Test-Path $PythonPath)) {
    throw "Python was not found in .venv. Run .\scripts\setup_dev.ps1 first."
}

try {
    & $PythonPath -c "import sys; print(sys.version)" *> $null
}
catch {
    throw "The selected Python cannot start: $PythonPath. Run .\scripts\setup_dev.ps1 to rebuild .venv."
}

Push-Location $ProjectRoot
try {
    & $PythonPath $ScriptPath @Arguments
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
