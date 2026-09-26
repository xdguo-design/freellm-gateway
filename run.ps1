param(
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8765,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    $Python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $Python) {
        throw "Python 3.10+ is required. Install Python and make sure 'python' is on PATH."
    }
    & $Python.Source -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        throw "Creating the Python virtual environment failed with exit code $LASTEXITCODE."
    }
}

& $VenvPython -m pip install -e .
if ($LASTEXITCODE -ne 0) {
    throw "Installing FreeLLM Gateway failed with exit code $LASTEXITCODE."
}

$RunArgs = @("-m", "freellm_gateway", "run", "--host", $HostAddress, "--port", "$Port")
if (-not $NoBrowser) {
    $RunArgs += "--open-browser"
}
& $VenvPython @RunArgs
if ($LASTEXITCODE -ne 0) {
    throw "FreeLLM Gateway exited with code $LASTEXITCODE."
}
