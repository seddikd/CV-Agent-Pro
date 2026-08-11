# CV Agent Pro — restauration d'une sauvegarde produite par sauvegarde.ps1.
#
# ATTENTION : opération DESTRUCTRICE. La base courante est écrasée par celle de
# la sauvegarde. Une confirmation explicite est exigée.
#
# Rappel : la base et le secret vont par paire. Restaurer un dump sans le
# CV_AGENT_SECRET d'origine laisse les mots de passe IMAP/SMTP chiffrés et
# illisibles — ils ressortiront vides, sans message d'erreur.
#
# USAGE :
#   powershell -ExecutionPolicy Bypass -File .\deploiement\windows\restauration.ps1 -Source .\sauvegardes\cv-agent-20260812-101500

param(
    [Parameter(Mandatory = $true)]
    [string]$Source
)

$ErrorActionPreference = "Stop"

$Racine = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

function Titre($t) { Write-Host ""; Write-Host "=== $t ===" -ForegroundColor Cyan }
function OK($m)    { Write-Host "  $m" -ForegroundColor Green }
function Avert($m) { Write-Host "  $m" -ForegroundColor Yellow }

if (-not (Test-Path $Source)) { throw "Dossier de sauvegarde introuvable : $Source" }
$Dump = Join-Path $Source "base.dump"
if (-not (Test-Path $Dump)) { throw "base.dump absent de $Source — sauvegarde invalide." }

Titre "Restauration CV Agent Pro"
Write-Host "Source : $Source" -ForegroundColor Gray

# ---- Détection du mode --------------------------------------------------------
$ModeDocker = $false
if (Get-Command docker -ErrorAction SilentlyContinue) {
    $db = docker ps --filter "name=cv-agent-pro-db-1" --format "{{.Names}}" 2>$null
    if ($db) { $ModeDocker = $true }
}
Write-Host ("Mode détecté : " + $(if ($ModeDocker) { "Docker" } else { "natif" })) -ForegroundColor Gray

# ---- Confirmation -------------------------------------------------------------
Write-Host ""
Write-Host "La base « cvagent » actuelle va être ÉCRASÉE." -ForegroundColor Red
Write-Host "Tous les candidats et réglages en place seront remplacés." -ForegroundColor Yellow
Write-Host ""
$reponse = Read-Host "Tapez exactement RESTAURER pour confirmer"
if ($reponse -cne "RESTAURER") {
    Write-Host "Annulé — rien n'a été modifié." -ForegroundColor Gray
    exit 0
}

if ($ModeDocker) {
    # ---- Mode Docker ----------------------------------------------------------
    Push-Location $Racine
    try {
        Titre "0/3 Configuration"
        # Restaurée EN PREMIER : l'application doit repartir avec le secret d'origine.
        $envSauve = Join-Path $Source "env"
        if (Test-Path $envSauve) {
            $envActuel = Join-Path $Racine ".env"
            if (Test-Path $envActuel) {
                Copy-Item $envActuel "$envActuel.avant-restauration" -Force
                Avert "Ancien .env conservé sous .env.avant-restauration"
            }
            Copy-Item $envSauve $envActuel -Force
            OK ".env restauré"
        } else {
            Avert "Pas de .env dans la sauvegarde — secret courant conservé"
        }

        Titre "1/3 Base PostgreSQL"
        # L'application doit être arrêtée : une écriture concurrente pendant le
        # rechargement laisserait la base dans un état incohérent.
        docker compose -f docker-compose.yml stop app | Out-Null
        docker compose -f docker-compose.yml up -d db | Out-Null
        for ($i = 0; $i -lt 30; $i++) {
            docker compose -f docker-compose.yml exec -T db pg_isready -U cvagent -d cvagent 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { break }
            Start-Sleep -Seconds 1
        }
        # --clean --if-exists : supprime les objets avant recréation (base non vide).
        cmd /c "docker compose -f docker-compose.yml exec -T db pg_restore -U cvagent -d cvagent --clean --if-exists --no-owner < `"$Dump`""
        if ($LASTEXITCODE -ne 0) { throw "pg_restore a échoué (code $LASTEXITCODE)" }
        OK "Base restaurée"

        Titre "2/3 Fichiers"
        $data = Join-Path $Source "data.tar.gz"
        if (Test-Path $data) {
            cmd /c "docker compose -f docker-compose.yml run --rm -T --entrypoint sh app -c `"tar xzf - -C /data`" < `"$data`""
            OK "Fichiers restaurés"
        } else { Avert "Pas de data.tar.gz — étape ignorée" }

        Titre "3/3 Redémarrage"
        docker compose -f docker-compose.yml up -d | Out-Null
        OK "Conteneurs redémarrés"
    } finally { Pop-Location }

} else {
    # ---- Mode natif -----------------------------------------------------------
    $DbUrl = [Environment]::GetEnvironmentVariable("CV_AGENT_DB_URL", "Machine")
    if (-not $DbUrl) { $DbUrl = $env:CV_AGENT_DB_URL }
    if (-not $DbUrl) { throw "CV_AGENT_DB_URL absente : impossible de localiser la base." }
    if (-not (Get-Command pg_restore -ErrorAction SilentlyContinue)) {
        throw "pg_restore introuvable dans le PATH. Ajoutez le dossier bin de PostgreSQL."
    }

    Titre "1/2 Base PostgreSQL"
    Avert "Arrêtez l'application avant de poursuivre (run_web.bat, tâche planifiée)."
    $ecoute = Get-NetTCPConnection -LocalPort 6060 -State Listen -ErrorAction SilentlyContinue
    if ($ecoute) { throw "Le port 6060 écoute encore : arrêtez l'application puis relancez." }

    & pg_restore --dbname=$DbUrl --clean --if-exists --no-owner $Dump
    # pg_restore renvoie 1 sur de simples avertissements (objets déjà absents) :
    # ce n'est pas un échec, d'où le seuil à 2.
    if ($LASTEXITCODE -gt 1) { throw "pg_restore a échoué (code $LASTEXITCODE)" }
    OK "Base restaurée"

    Titre "2/2 Fichiers et secret"
    $DataDir = [Environment]::GetEnvironmentVariable("CV_AGENT_DATA_DIR", "Machine")
    if (-not $DataDir) { $DataDir = $env:CV_AGENT_DATA_DIR }
    if (-not $DataDir) { $DataDir = $Racine }
    foreach ($sous in @("cv_pdfs", "logs")) {
        $zip = Join-Path $Source "$sous.zip"
        if (Test-Path $zip) {
            Expand-Archive -Path $zip -DestinationPath $DataDir -Force
            OK "$sous restauré"
        }
    }
    $secretFile = Join-Path $Source "cv-agent-secret.txt"
    if (Test-Path $secretFile) {
        Avert "La sauvegarde contient un CV_AGENT_SECRET."
        Avert "S'il diffère de celui de cette machine, reportez-le AVANT de démarrer :"
        Write-Host "    setx /M CV_AGENT_SECRET `"<valeur de $secretFile>`"" -ForegroundColor Gray
    }
}

Titre "Restauration terminée"
Write-Host "  Vérifiez le diagnostic :" -ForegroundColor White
Write-Host "    .\deploiement\windows\verifier-deploiement.ps1" -ForegroundColor Gray
