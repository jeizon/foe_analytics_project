<# Run the FoE Analytics mitmproxy addon from the project virtual environment. #>

[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$MitmproxyArguments = @()
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$PythonPath = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$MitmproxyLauncherPath = Join-Path $ProjectRoot "scripts\run_mitmproxy.py"
$AddonPath = Join-Path $ProjectRoot "proxy_interceptor\mitm_addon.py"

if (-not (Test-Path $PythonPath)) {
    throw "Python was not found in .venv. Run .\scripts\setup_dev.ps1 first."
}

Push-Location $ProjectRoot
try {
    & $PythonPath $MitmproxyLauncherPath -s $AddonPath @MitmproxyArguments
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
