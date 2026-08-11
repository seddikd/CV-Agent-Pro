# CV Agent Pro — diagnostic d'un déploiement Windows.
#
# Contrôle, sans rien modifier, les points qui expliquent la quasi-totalité des
# incidents d'installation : Python, environnement virtuel, variables
# d'environnement, joignabilité de PostgreSQL, port applicatif, tâche planifiée,
# règle de pare-feu, journaux.
#
# USAGE (aucun droit administrateur requis) :
#   powershell -ExecutionPolicy Bypass -File .\deploiement\windows\verifier-deploiement.ps1

$ErrorActionPreference = "Continue"

# Racine du dépôt = deux niveaux au-dessus de ce script.
$Racine = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Port   = 6060
$Tache  = "CV-Agent-Web"

$script:Avertissements = 0
$script:Erreurs        = 0

function Titre($t) { Write-Host ""; Write-Host "=== $t ===" -ForegroundColor Cyan }
function OK($m)    { Write-Host "  [OK]    $m" -ForegroundColor Green }
function Avert($m) { Write-Host "  [AVERT] $m" -ForegroundColor Yellow; $script:Avertissements++ }
function Err($m)   { Write-Host "  [ERR]   $m" -ForegroundColor Red;    $script:Erreurs++ }
function Info($m)  { Write-Host "          $m" -ForegroundColor Gray }

Write-Host ""
Write-Host "Diagnostic CV Agent Pro" -ForegroundColor White
Write-Host "Dépôt : $Racine" -ForegroundColor Gray

# ---- 1. Python et environnement virtuel --------------------------------------
Titre "1. Python"
$VenvPy = Join-Path $Racine ".venv\Scripts\python.exe"
if (Test-Path $VenvPy) {
    OK "Environnement virtuel présent"
    Info (& $VenvPy --version 2>&1)
    # Dépendances critiques : une seule manquante empêche le démarrage.
    $manquants = @()
    foreach ($mod in @("fastapi", "uvicorn", "psycopg", "cryptography", "apscheduler")) {
        & $VenvPy -c "import $mod" 2>$null
        if ($LASTEXITCODE -ne 0) { $manquants += $mod }
    }
    if ($manquants.Count -eq 0) { OK "Dépendances critiques importables" }
    else {
        Err "Modules introuvables : $($manquants -join ', ')"
        Info "Correctif : .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
    }
} else {
    Err "Environnement virtuel absent (.venv)"
    Info "Correctif : double-clic sur install.bat"
}

# ---- 2. Variables d'environnement --------------------------------------------
Titre "2. Configuration"
$DbUrl = [Environment]::GetEnvironmentVariable("CV_AGENT_DB_URL", "Machine")
if (-not $DbUrl) { $DbUrl = $env:CV_AGENT_DB_URL }
if ($DbUrl) {
    # Ne jamais afficher le mot de passe contenu dans l'URL.
    OK "CV_AGENT_DB_URL définie"
    Info ($DbUrl -replace '://([^:]+):[^@]+@', '://$1:***@')
} else {
    Err "CV_AGENT_DB_URL absente — l'application refusera de démarrer"
    Info "PostgreSQL est obligatoire : il n'existe aucun repli SQLite."
}

$Secret = [Environment]::GetEnvironmentVariable("CV_AGENT_SECRET", "Machine")
if (-not $Secret) { $Secret = $env:CV_AGENT_SECRET }
if ($Secret) {
    OK "CV_AGENT_SECRET définie (chiffrement portable enc:v2)"
} else {
    Avert "CV_AGENT_SECRET absente — repli sur DPAPI (enc:v1), machine locale uniquement"
    Info "Obligatoire si plusieurs postes partagent la même base PostgreSQL."
}

$EnvFile = Join-Path $Racine ".env"
if (Test-Path $EnvFile) { Info ".env présent (utilisé par Docker et run_web_natif.ps1)" }

# ---- 3. PostgreSQL ------------------------------------------------------------
Titre "3. PostgreSQL"
if ($DbUrl -match '@([^:/]+):(\d+)/') {
    $hote = $Matches[1]; $portDb = [int]$Matches[2]
    $test = Test-NetConnection -ComputerName $hote -Port $portDb -InformationLevel Quiet -WarningAction SilentlyContinue
    if ($test) { OK "Base joignable sur ${hote}:${portDb}" }
    else {
        Err "Base INJOIGNABLE sur ${hote}:${portDb}"
        Info "Service natif arrêté, ou conteneur db non démarré (docker compose up -d db)."
    }
} elseif ($DbUrl) {
    Avert "Impossible d'extraire hôte/port de CV_AGENT_DB_URL"
}

# ---- 4. Application -----------------------------------------------------------
Titre "4. Application (port $Port)"
$ecoute = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($ecoute) {
    $pid0 = ($ecoute | Select-Object -First 1).OwningProcess
    $proc = Get-Process -Id $pid0 -ErrorAction SilentlyContinue
    OK "Port $Port en écoute (PID $pid0 — $($proc.ProcessName))"
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/login" -UseBasicParsing -TimeoutSec 5
        if ($r.StatusCode -eq 200) { OK "La page /login répond (HTTP 200)" }
        else { Avert "/login répond HTTP $($r.StatusCode)" }
    } catch {
        Err "Le port écoute mais /login ne répond pas : $($_.Exception.Message)"
    }
} else {
    Avert "Rien n'écoute sur le port $Port (application arrêtée)"
    Info "Démarrage : .\run_web.bat"
}

# ---- 5. Démarrage automatique -------------------------------------------------
Titre "5. Démarrage automatique"
$t = Get-ScheduledTask -TaskName $Tache -ErrorAction SilentlyContinue
if ($t) {
    $etat = ($t | Get-ScheduledTaskInfo)
    OK "Tâche planifiée « $Tache » installée (état : $($t.State))"
    Info "Dernière exécution : $($etat.LastRunTime) — code $($etat.LastTaskResult)"
} else {
    Info "Tâche « $Tache » non installée (démarrage manuel)"
    Info "Installation : PowerShell admin -> .\install_autostart.ps1"
}

# ---- 6. Pare-feu --------------------------------------------------------------
Titre "6. Pare-feu"
$regle = Get-NetFirewallRule -DisplayName "CV Agent Web (port $Port)" -ErrorAction SilentlyContinue
if ($regle) {
    OK "Règle entrante présente (activée : $($regle.Enabled), action : $($regle.Action))"
} else {
    Info "Aucune règle dédiée — accès LAN probablement bloqué (usage local uniquement)"
}

# ---- 7. Docker ----------------------------------------------------------------
Titre "7. Docker (si utilisé)"
if (Get-Command docker -ErrorAction SilentlyContinue) {
    $conteneurs = docker ps --filter "name=cv-agent" --format "{{.Names}} : {{.Status}}" 2>$null
    if ($conteneurs) { OK "Conteneurs actifs"; $conteneurs | ForEach-Object { Info $_ } }
    else { Info "Aucun conteneur cv-agent en cours" }
} else {
    Info "Docker non installé (sans objet en déploiement natif)"
}

# ---- 8. Journaux --------------------------------------------------------------
Titre "8. Journaux"
foreach ($j in @("logs\agent.log", "logs\web_startup.log")) {
    $chemin = Join-Path $Racine $j
    if (Test-Path $chemin) {
        $f = Get-Item $chemin
        Info "$j — $([math]::Round($f.Length/1KB)) Ko, modifié le $($f.LastWriteTime)"
    }
}

# ---- Bilan --------------------------------------------------------------------
Write-Host ""
if ($script:Erreurs -gt 0) {
    Write-Host "BILAN : $($script:Erreurs) erreur(s), $($script:Avertissements) avertissement(s)." -ForegroundColor Red
    exit 1
} elseif ($script:Avertissements -gt 0) {
    Write-Host "BILAN : aucune erreur, $($script:Avertissements) avertissement(s)." -ForegroundColor Yellow
    exit 0
} else {
    Write-Host "BILAN : déploiement conforme." -ForegroundColor Green
    exit 0
}
