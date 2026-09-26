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
}

& $VenvPython -m pip install -e .
$RunArgs = @("-m", "freellm_gateway", "run", "--host", $HostAddress, "--port", "$Port")
if (-not $NoBrowser) {
    $RunArgs += "--open-browser"
}
& $VenvPython @RunArgs
