param(
    [switch]$Debug
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Python) {
    throw "Python 3.10+ is required."
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "Node.js/npm is required."
}
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    throw "Rust stable/cargo is required."
}

Write-Host "[1/4] Building React/TypeScript admin..."
npm install --prefix web --no-audit --no-fund
npm run build --prefix web

Write-Host "[2/4] Building Python gateway sidecar..."
& $Python.Source -m pip install pyinstaller
$Work = Join-Path $env:TEMP "freellm-pyinstaller-build"
& $Python.Source -m PyInstaller --onedir --noconsole --name freellm-gateway --noconfirm --distpath desktop/sidecar --workpath $Work --specpath $Work --add-data "$Root\freellm_gateway\templates;freellm_gateway\templates" --add-data "$Root\freellm_gateway\static\admin;freellm_gateway\static\admin" --hidden-import uvicorn.loops.auto --hidden-import uvicorn.protocols.http.auto --hidden-import uvicorn.protocols.websockets.auto --hidden-import uvicorn.protocols.websockets.websockets_impl --hidden-import uvicorn.lifespan.on freellm_gateway/desktop_entry.py

Write-Host "[3/4] Syncing sidecar resources..."
$Target = Join-Path $Root "desktop\src-tauri\binaries\freellm-gateway"
if (Test-Path $Target) {
    Remove-Item $Target -Recurse -Force
}
Copy-Item (Join-Path $Root "desktop\sidecar\freellm-gateway") $Target -Recurse

Write-Host "[4/4] Building FreeLLM Studio..."
npm install --prefix desktop --no-audit --no-fund
if ($Debug) {
    npm run build:debug --prefix desktop
} else {
    npm run build --prefix desktop
}

Write-Host "Done."
