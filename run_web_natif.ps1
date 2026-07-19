# Lance CV Agent NATIVEMENT sous Windows, branché sur le PostgreSQL de Docker.
#
# Pourquoi ce script ? Le rangement des mails traités (« Ranger les traités », onglet
# Import Outlook) pilote Outlook via COM/win32com. Le conteneur applicatif tourne sous
# Linux : il n'a aucun accès à Outlook, et le bouton y est donc toujours grisé — que
# Outlook soit installé sur le poste ou non, puisque l'opération part du serveur.
#
# Ce script fait tourner l'app sur le poste Windows en gardant la base dans Docker.
# Il exige que le conteneur `app` soit arrêté : deux instances qui pollent la même
# boîte violeraient l'invariant « une seule instance » (APScheduler + candidate_counter).
#
# Prérequis : docker-compose.override.yml (publie la base sur 127.0.0.1:5432) et
#   docker compose up -d db
#
# À savoir : en natif, DATA_DIR est le dossier du projet et non le volume Docker. Les
# CV déjà téléchargés par le conteneur (cv_pdfs) ne seront donc pas visibles ici ; le
# dossier d'import, lui, pointe bien sur .\import (même dossier que le montage Docker).

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# --- Le conteneur app doit être arrêté (invariant « une seule instance ») -------------
$appUp = docker ps --filter "name=cv-agent-pro-app-1" --format "{{.Names}}" 2>$null
if ($appUp) {
    Write-Host "Le conteneur applicatif tourne encore : deux instances polleraient la meme boite." -ForegroundColor Red
    Write-Host "Arretez-le d'abord :  docker compose stop app" -ForegroundColor Yellow
    exit 1
}

# --- Identifiants repris du .env (memes valeurs que le conteneur) ---------------------
if (-not (Test-Path ".env")) { Write-Host ".env introuvable." -ForegroundColor Red; exit 1 }
$envVars = @{}
foreach ($line in Get-Content ".env") {
    if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$') {
        $envVars[$Matches[1]] = $Matches[2].Trim('"').Trim("'")
    }
}
foreach ($k in @("POSTGRES_PASSWORD", "CV_AGENT_SECRET")) {
    if (-not $envVars[$k]) { Write-Host "$k absent du .env." -ForegroundColor Red; exit 1 }
}

# La base doit etre joignable : sans docker-compose.override.yml, aucun port n'est publie.
# Port 5433 : le 5432 de l'hote est deja pris par un PostgreSQL natif, sans rapport avec
# ce projet. Ne pas viser 5432 ici, on tomberait sur la mauvaise base.
$probe = Test-NetConnection -ComputerName 127.0.0.1 -Port 5433 -InformationLevel Quiet -WarningAction SilentlyContinue
if (-not $probe) {
    Write-Host "PostgreSQL (Docker) injoignable sur 127.0.0.1:5433." -ForegroundColor Red
    Write-Host "Verifiez docker-compose.override.yml puis :  docker compose up -d db" -ForegroundColor Yellow
    exit 1
}

# CV_AGENT_SECRET doit etre IDENTIQUE a celui du conteneur : les secrets en base sont
# chiffres en enc:v2 (Fernet, cle derivee de ce secret). Un secret different rendrait
# les mots de passe IMAP/SMTP indechiffrables (ils ressortiraient vides, sans crash).
$env:CV_AGENT_DB_URL = "postgresql://cvagent:$($envVars['POSTGRES_PASSWORD'])@127.0.0.1:5433/cvagent"
$env:CV_AGENT_SECRET = $envVars["CV_AGENT_SECRET"]

Write-Host "CV Agent (natif Windows) -> http://127.0.0.1:6060/admin/import" -ForegroundColor Green
& ".\.venv\Scripts\python.exe" -m uvicorn webapp:app --host 127.0.0.1 --port 6060 --log-level info
