# Create a virtual environment on first run, install dependencies, then run the service.
# Usage: .\start.ps1 [serve|reset --yes|export-openapi] [--port N]
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
    python -m venv .venv
}
& $venvPython -m pip --disable-pip-version-check install -q -r requirements-dev.txt
& $venvPython -m browzine_mock @args
exit $LASTEXITCODE
