# Compile l'application desktop CV Agent en exécutable Windows autonome.
# Résultat : dist\CV-Agent\CV-Agent.exe (dossier autonome, rien à installer).
#
# USAGE : powershell -ExecutionPolicy Bypass -File .\build_exe.ps1

$ErrorActionPreference = "Stop"
$Root   = $PSScriptRoot
$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"

Write-Host ""
Write-Host "=== Build CV Agent (desktop .exe) ===" -ForegroundColor Cyan

if (-not (Test-Path $VenvPy)) {
    Write-Host "ERREUR : .venv introuvable. Lance d'abord install.bat" -ForegroundColor Red
    exit 1
}

# Nettoyage des builds précédents
foreach ($d in @("build", "dist")) {
    $p = Join-Path $Root $d
    if (Test-Path $p) { Remove-Item -Recurse -Force $p }
}

Write-Host "[1/2] Compilation PyInstaller..." -ForegroundColor White
& $VenvPy -m PyInstaller (Join-Path $Root "cv-agent.spec") --noconfirm --clean
if ($LASTEXITCODE -ne 0) { Write-Host "ERREUR : build PyInstaller échoué." -ForegroundColor Red; exit 1 }

$exe = Join-Path $Root "dist\CV-Agent\CV-Agent.exe"
Write-Host "[2/2] Vérification..." -ForegroundColor White
if (-not (Test-Path $exe)) { Write-Host "ERREUR : $exe non produit." -ForegroundColor Red; exit 1 }

$size = [math]::Round((Get-ChildItem -Recurse (Join-Path $Root "dist\CV-Agent") | Measure-Object Length -Sum).Sum / 1MB, 1)
Write-Host ""
Write-Host "=== Build terminé ===" -ForegroundColor Green
Write-Host "  Exécutable : $exe" -ForegroundColor Gray
Write-Host "  Taille dossier : $size Mo" -ForegroundColor Gray
Write-Host ""
Write-Host "Teste-le : double-clic sur CV-Agent.exe" -ForegroundColor White
Write-Host "Les données seront dans : %LOCALAPPDATA%\CV-Agent\" -ForegroundColor Gray
Write-Host ""
