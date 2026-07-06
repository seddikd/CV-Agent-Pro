# Compile l'installeur Windows CV-Agent-Setup.exe via Inno Setup.
# Prérequis : dossier dist\CV-Agent produit par build_exe.ps1, et Inno Setup 6 installé.
#
# USAGE : powershell -ExecutionPolicy Bypass -File .\build_installer.ps1

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot

Write-Host ""
Write-Host "=== Build installeur CV Agent (Setup.exe) ===" -ForegroundColor Cyan

# 1. Le build de l'exe doit exister
$distApp = Join-Path $Root "dist\CV-Agent\CV-Agent.exe"
if (-not (Test-Path $distApp)) {
    Write-Host "ERREUR : dist\CV-Agent introuvable." -ForegroundColor Red
    Write-Host "Lance d'abord :  powershell -ExecutionPolicy Bypass -File .\build_exe.ps1" -ForegroundColor Yellow
    exit 1
}

# 2. Localiser ISCC.exe (compilateur Inno Setup)
$candidates = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 5\ISCC.exe"
)
$iscc = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
    $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($cmd) { $iscc = $cmd.Source }
}

if (-not $iscc) {
    Write-Host "ERREUR : Inno Setup (ISCC.exe) introuvable." -ForegroundColor Red
    Write-Host ""
    Write-Host "Installe-le une fois, puis relance ce script :" -ForegroundColor Yellow
    Write-Host "  winget install --id JRSoftware.InnoSetup -e" -ForegroundColor Gray
    Write-Host "  (ou télécharge : https://jrsoftware.org/isdl.php )" -ForegroundColor Gray
    exit 1
}

Write-Host "[1/2] Inno Setup : $iscc" -ForegroundColor White
Write-Host "[2/2] Compilation de l'installeur..." -ForegroundColor White
& $iscc (Join-Path $Root "installer.iss")
if ($LASTEXITCODE -ne 0) { Write-Host "ERREUR : compilation Inno Setup échouée." -ForegroundColor Red; exit 1 }

$setup = Join-Path $Root "dist\CV-Agent-Setup.exe"
if (Test-Path $setup) {
    $mb = [math]::Round((Get-Item $setup).Length / 1MB, 1)
    Write-Host ""
    Write-Host "=== Installeur prêt ===" -ForegroundColor Green
    Write-Host "  $setup  ($mb Mo)" -ForegroundColor Gray
    Write-Host "  Distribue ce fichier : double-clic = installation (sans droits admin)." -ForegroundColor Gray
} else {
    Write-Host "AVERT : Setup.exe non trouvé après compilation." -ForegroundColor Yellow
}
Write-Host ""
