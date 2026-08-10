# Installateur CV Agent — crée l'environnement, installe les dépendances,
# initialise la base et crée le compte administrateur. Idempotent (ré-exécutable).
#
# USAGE (double-clic sur install.bat) ou en PowerShell :
#   powershell -ExecutionPolicy Bypass -File .\install.ps1

$ErrorActionPreference = "Stop"

# Racine = dossier de ce script (le projet peut donc être déplacé/copié n'importe où).
$Root   = $PSScriptRoot
$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
$Req    = Join-Path $Root "requirements.txt"

Write-Host ""
Write-Host "=== Installation de CV Agent ===" -ForegroundColor Cyan
Write-Host "Dossier : $Root" -ForegroundColor Gray
Write-Host ""

# ---- 1. Trouver un interpréteur Python -------------------------------------
function Find-Python {
    foreach ($cmd in @("py -3", "python", "python3")) {
        $parts = $cmd.Split(" ")
        $exe = (Get-Command $parts[0] -ErrorAction SilentlyContinue)
        if ($exe) {
            try {
                $v = & $parts[0] $parts[1..($parts.Length-1)] --version 2>&1
                if ($LASTEXITCODE -eq 0) { return $cmd }
            } catch {}
        }
    }
    return $null
}

$py = Find-Python
if (-not $py) {
    Write-Host "ERREUR : Python 3 introuvable." -ForegroundColor Red
    Write-Host "Installe Python 3.11+ depuis https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "en cochant 'Add python.exe to PATH', puis relance ce script." -ForegroundColor Yellow
    exit 1
}
$pyParts = $py.Split(" ")
Write-Host "[1/4] Python détecté : " -NoNewline
& $pyParts[0] $pyParts[1..($pyParts.Length-1)] --version

# ---- 2. Environnement virtuel ----------------------------------------------
if (Test-Path $VenvPy) {
    Write-Host "[2/4] Environnement virtuel déjà présent (.venv)" -ForegroundColor Gray
} else {
    Write-Host "[2/4] Création de l'environnement virtuel (.venv)..." -ForegroundColor White
    & $pyParts[0] $pyParts[1..($pyParts.Length-1)] -m venv (Join-Path $Root ".venv")
    if ($LASTEXITCODE -ne 0) { Write-Host "ERREUR : échec de création du venv." -ForegroundColor Red; exit 1 }
}

# ---- 3. Dépendances --------------------------------------------------------
Write-Host "[3/4] Installation des dépendances (pip)..." -ForegroundColor White
& $VenvPy -m pip install --upgrade pip --quiet
& $VenvPy -m pip install -r $Req
if ($LASTEXITCODE -ne 0) { Write-Host "ERREUR : échec de l'installation des dépendances." -ForegroundColor Red; exit 1 }
Write-Host "      Dépendances installées." -ForegroundColor Green

# ---- 4. Bootstrap (DB + settings + admin) ----------------------------------
Write-Host "[4/4] Initialisation de la base et du compte admin..." -ForegroundColor White
Write-Host ""
& $VenvPy (Join-Path $Root "bootstrap.py")
if ($LASTEXITCODE -ne 0) { Write-Host "ERREUR : échec du bootstrap." -ForegroundColor Red; exit 1 }

# ---- Fin -------------------------------------------------------------------
Write-Host ""
Write-Host "=== Installation terminée ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Démarrer l'application maintenant :" -ForegroundColor White
Write-Host "  .\run_web.bat" -ForegroundColor Gray
Write-Host "  puis ouvrir http://localhost:6060" -ForegroundColor Gray
Write-Host ""
Write-Host "Démarrage automatique au boot (PowerShell admin) :" -ForegroundColor White
Write-Host "  powershell -ExecutionPolicy Bypass -File .\install_autostart.ps1" -ForegroundColor Gray
Write-Host ""
