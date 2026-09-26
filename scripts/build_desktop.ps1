param(
    [switch]$Debug
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$SystemPython = Get-Command python -ErrorAction SilentlyContinue
if (-not $SystemPython) {
    throw "Python 3.10+ is required."
}
$Npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $Npm) {
    $Npm = Get-Command npm -ErrorAction SilentlyContinue
}
if (-not $Npm) {
    throw "Node.js/npm is required."
}
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    throw "Rust stable/cargo is required."
}

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    & $SystemPython.Source -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        throw "Creating the Python virtual environment failed with exit code $LASTEXITCODE."
    }
}
& $VenvPython -m pip install -U pip
if ($LASTEXITCODE -ne 0) { throw "Upgrading pip failed with exit code $LASTEXITCODE." }
& $VenvPython -m pip install -e . pyinstaller
if ($LASTEXITCODE -ne 0) { throw "Installing desktop build dependencies failed with exit code $LASTEXITCODE." }

Write-Host "[1/4] Building React/TypeScript admin..."
& $Npm.Source ci --prefix web --no-audit --no-fund
if ($LASTEXITCODE -ne 0) { throw "Installing React dependencies failed with exit code $LASTEXITCODE." }
& $Npm.Source run build --prefix web
if ($LASTEXITCODE -ne 0) { throw "Building the React admin failed with exit code $LASTEXITCODE." }

Write-Host "[2/4] Building Python gateway sidecar..."
$Work = Join-Path $env:TEMP "freellm-pyinstaller-build"
& $VenvPython -m PyInstaller --onedir --noconsole --name freellm-gateway --noconfirm --distpath desktop/sidecar --workpath $Work --specpath $Work --add-data "$Root\freellm_gateway\templates;freellm_gateway\templates" --add-data "$Root\freellm_gateway\static\admin;freellm_gateway\static\admin" --hidden-import uvicorn.loops.auto --hidden-import uvicorn.protocols.http.auto --hidden-import uvicorn.protocols.websockets.auto --hidden-import uvicorn.protocols.websockets.websockets_impl --hidden-import uvicorn.lifespan.on freellm_gateway/desktop_entry.py
if ($LASTEXITCODE -ne 0) { throw "Building the Python sidecar failed with exit code $LASTEXITCODE." }

Write-Host "[3/4] Syncing sidecar resources..."
$Target = Join-Path $Root "desktop\src-tauri\binaries\freellm-gateway"
if (Test-Path $Target) {
    Remove-Item $Target -Recurse -Force
}
Copy-Item (Join-Path $Root "desktop\sidecar\freellm-gateway") $Target -Recurse

Write-Host "[4/4] Building FreeLLM Studio..."
& $Npm.Source ci --prefix desktop --no-audit --no-fund
if ($LASTEXITCODE -ne 0) { throw "Installing desktop dependencies failed with exit code $LASTEXITCODE." }
if ($Debug) {
    & $Npm.Source run build:debug --prefix desktop
} else {
    & $Npm.Source run build --prefix desktop
}
if ($LASTEXITCODE -ne 0) { throw "Building FreeLLM Studio failed with exit code $LASTEXITCODE." }

Write-Host "Done."
