<# Rebuild consolidated player identity and wallet tables from routed events. #>

[CmdletBinding()]
param(
    [switch]$KeepExisting
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$ScriptPath = Join-Path $ProjectRoot "scripts\reprocess_consolidated.py"

if (-not (Test-Path $PythonPath)) {
    throw "Python was not found in .venv. Run .\scripts\setup_dev.ps1 first."
}

$Arguments = @($ScriptPath)
if ($KeepExisting) {
    $Arguments += "--keep-existing"
}

Push-Location $ProjectRoot
try {
    & $PythonPath @Arguments
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
