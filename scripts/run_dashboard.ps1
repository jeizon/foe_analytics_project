<# Run the FoE Analytics Streamlit dashboard from the project virtual environment. #>

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$DashboardPath = Join-Path $ProjectRoot "dashboard_ui\main_app.py"

if (-not (Test-Path $PythonPath)) {
    throw "Python was not found in .venv. Run .\scripts\setup_dev.ps1 first."
}

Push-Location $ProjectRoot
try {
    & $PythonPath -m streamlit run $DashboardPath
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
