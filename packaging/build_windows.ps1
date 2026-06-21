# Build aVs Windows installer (.exe) using PyInstaller + Inno Setup.
#
# Prerequisites:
#   pip install pyinstaller
#   choco install innosetup   (or download from jrsoftware.org)
#
# Run from project root:
#   .\packaging\build_windows.ps1
#
# Output: dist\aVs-<version>-Setup.exe

$ErrorActionPreference = "Stop"

# Always run from project root regardless of where script is invoked
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $projectRoot

$VERSION = python -c "from avs import __version__; print(__version__)"
Write-Host "==> Building aVs v$VERSION"

# ── 1. PyInstaller ────────────────────────────────────────────────────────────
Write-Host "==> Running PyInstaller..."
pyinstaller avs.spec --noconfirm

# ── 2. Inno Setup ─────────────────────────────────────────────────────────────
Write-Host "==> Running Inno Setup..."

# Prefer the standard install path; fall back to PATH (choco puts it there)
$isccPaths = @(
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
)
$iscc = $isccPaths | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { $iscc = "iscc" }   # rely on PATH

& $iscc "/DMyAppVersion=$VERSION" "packaging\avs.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed (exit $LASTEXITCODE)" }

Write-Host ""
Write-Host "==> Done: dist\aVs-$VERSION-Setup.exe"
