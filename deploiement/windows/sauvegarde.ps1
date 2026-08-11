# CV Agent Pro — sauvegarde d'un déploiement Windows.
#
# Détecte tout seul le mode en place :
#   - Docker Desktop : dump via le conteneur « db », fichiers via le conteneur « app » ;
#   - natif          : pg_dump local piloté par CV_AGENT_DB_URL.
#
# Produit un dossier horodaté contenant la base, les fichiers (cv_pdfs, logs) et
# la configuration. Sans CV_AGENT_SECRET, les mots de passe IMAP/SMTP du dump
# restent chiffrés en enc:v2 et sont IRRÉCUPÉRABLES : le script le rappelle et,
# en mode natif, écrit le secret dans un fichier dédié.
#
# USAGE :
#   powershell -ExecutionPolicy Bypass -File .\deploiement\windows\sauvegarde.ps1
#   powershell -ExecutionPolicy Bypass -File .\deploiement\windows\sauvegarde.ps1 -Destination D:\sauvegardes

param(
    [string]$Destination
)

$ErrorActionPreference = "Stop"

$Racine = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not $Destination) { $Destination = Join-Path $Racine "sauvegardes" }
$Horodatage = Get-Date -Format "yyyyMMdd-HHmmss"
$Dossier    = Join-Path $Destination "cv-agent-$Horodatage"

function Titre($t) { Write-Host ""; Write-Host "=== $t ===" -ForegroundColor Cyan }
function OK($m)    { Write-Host "  $m" -ForegroundColor Green }
function Avert($m) { Write-Host "  $m" -ForegroundColor Yellow }

Titre "Sauvegarde CV Agent Pro"
Write-Host "Destination : $Dossier" -ForegroundColor Gray

# ---- Détection du mode --------------------------------------------------------
$ModeDocker = $false
if (Get-Command docker -ErrorAction SilentlyContinue) {
    $db = docker ps --filter "name=cv-agent-pro-db-1" --format "{{.Names}}" 2>$null
    if ($db) { $ModeDocker = $true }
}
Write-Host ("Mode détecté : " + $(if ($ModeDocker) { "Docker" } else { "natif" })) -ForegroundColor Gray

New-Item -ItemType Directory -Path $Dossier -Force | Out-Null

if ($ModeDocker) {
    # ---- Mode Docker ----------------------------------------------------------
    Titre "1/3 Base PostgreSQL (conteneur)"
    Push-Location $Racine
    try {
        # -Fc : format « custom », compressé et restaurable sélectivement.
        # cmd /c pour rediriger le flux binaire sans que PowerShell n'y touche :
        # une redirection PowerShell réencoderait la sortie et corromprait le dump.
        cmd /c "docker compose -f docker-compose.yml exec -T db pg_dump -U cvagent -d cvagent -Fc > `"$Dossier\base.dump`""
        if ($LASTEXITCODE -ne 0) { throw "pg_dump a échoué (code $LASTEXITCODE)" }
        OK ("base.dump — {0:N1} Mo" -f ((Get-Item "$Dossier\base.dump").Length / 1MB))

        Titre "2/3 Fichiers /data (conteneur)"
        cmd /c "docker compose -f docker-compose.yml exec -T app tar czf - -C /data --exclude=./import . > `"$Dossier\data.tar.gz`""
        if ($LASTEXITCODE -ne 0) { Avert "Archive des fichiers non réalisée (conteneur app arrêté ?)" }
        else { OK ("data.tar.gz — {0:N1} Mo" -f ((Get-Item "$Dossier\data.tar.gz").Length / 1MB)) }

        Titre "3/3 Configuration"
        if (Test-Path (Join-Path $Racine ".env")) {
            Copy-Item (Join-Path $Racine ".env") (Join-Path $Dossier "env") -Force
            OK ".env sauvegardé (contient CV_AGENT_SECRET)"
        } else {
            Avert ".env INTROUVABLE — la sauvegarde sera inexploitable pour les secrets chiffrés"
        }
    } finally { Pop-Location }

} else {
    # ---- Mode natif -----------------------------------------------------------
    Titre "1/3 Base PostgreSQL (pg_dump local)"
    $DbUrl = [Environment]::GetEnvironmentVariable("CV_AGENT_DB_URL", "Machine")
    if (-not $DbUrl) { $DbUrl = $env:CV_AGENT_DB_URL }
    if (-not $DbUrl) { throw "CV_AGENT_DB_URL absente : impossible de localiser la base." }
    if (-not (Get-Command pg_dump -ErrorAction SilentlyContinue)) {
        throw "pg_dump introuvable dans le PATH. Ajoutez le dossier bin de PostgreSQL (ex. C:\Program Files\PostgreSQL\17\bin)."
    }
    # pg_dump accepte l'URL de connexion complète : ni parsing ni mot de passe en clair
    # sur la ligne de commande au-delà de ce qu'elle contient déjà.
    & pg_dump --dbname=$DbUrl -Fc -f (Join-Path $Dossier "base.dump")
    if ($LASTEXITCODE -ne 0) { throw "pg_dump a échoué (code $LASTEXITCODE)" }
    OK ("base.dump — {0:N1} Mo" -f ((Get-Item "$Dossier\base.dump").Length / 1MB))

    Titre "2/3 Fichiers"
    # En natif, DATA_DIR vaut CV_AGENT_DATA_DIR si défini, sinon le dossier du projet.
    $DataDir = [Environment]::GetEnvironmentVariable("CV_AGENT_DATA_DIR", "Machine")
    if (-not $DataDir) { $DataDir = $env:CV_AGENT_DATA_DIR }
    if (-not $DataDir) { $DataDir = $Racine }
    foreach ($sous in @("cv_pdfs", "logs")) {
        $src = Join-Path $DataDir $sous
        if (Test-Path $src) {
            Compress-Archive -Path $src -DestinationPath (Join-Path $Dossier "$sous.zip") -Force
            OK "$sous.zip"
        }
    }

    Titre "3/3 Configuration"
    $Secret = [Environment]::GetEnvironmentVariable("CV_AGENT_SECRET", "Machine")
    if (-not $Secret) { $Secret = $env:CV_AGENT_SECRET }
    if ($Secret) {
        Set-Content -Path (Join-Path $Dossier "cv-agent-secret.txt") -Value "CV_AGENT_SECRET=$Secret" -Encoding UTF8
        OK "CV_AGENT_SECRET sauvegardé"
    } else {
        Avert "CV_AGENT_SECRET absente : les secrets sont chiffrés en DPAPI (enc:v1),"
        Avert "déchiffrables UNIQUEMENT sur cette machine. Une restauration ailleurs"
        Avert "rendra les mots de passe IMAP/SMTP vides — à ressaisir."
    }
}

# ---- Bilan --------------------------------------------------------------------
$taille = (Get-ChildItem $Dossier -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1MB
Titre "Sauvegarde terminée"
Write-Host ("  $Dossier  ({0:N1} Mo)" -f $taille) -ForegroundColor Green
Write-Host ""
Write-Host "  Restauration :" -ForegroundColor White
Write-Host "    .\deploiement\windows\restauration.ps1 -Source `"$Dossier`"" -ForegroundColor Gray
Write-Host ""
Write-Host "  Ce dossier contient le secret de chiffrement : stockez-le comme un mot de passe." -ForegroundColor Yellow
