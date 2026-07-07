#Requires -RunAsAdministrator
<#
    Installateur CV Agent Pro — Windows 10 / 11 (déploiement natif).
    Met en place TOUS les prérequis et l'application :
      1. PostgreSQL 17 (via winget, installation silencieuse)
      2. Ollama (optionnel, LLM local) via winget
      3. Rôle + base « cvagent »
      4. Variables d'environnement machine (CV_AGENT_DB_URL, CV_AGENT_SECRET)
      5. Copie de l'application (exécutable) + raccourcis
      6. Lancement + ouverture de la page de création d'admin

    À lancer par CLIC DROIT -> « Exécuter avec PowerShell » (en administrateur),
    ou :  powershell -ExecutionPolicy Bypass -File .\Installer.ps1

    Options :
      -InstallDir  <chemin>   dossier d'installation (défaut C:\CV-Agent-Pro)
      -AppPort     <port>     port web (défaut 6060)
      -InstallOllama          installe aussi Ollama (LLM local gratuit)
#>
param(
    [string]$InstallDir = "C:\CV-Agent-Pro",
    [int]$AppPort = 6060,
    [switch]$InstallOllama
)

$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path

function Info($m) { Write-Host "[i]  $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "[OK] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "[!]  $m" -ForegroundColor Yellow }
function Step($m) { Write-Host "`n=== $m ===" -ForegroundColor White -BackgroundColor DarkBlue }

function New-Password([int]$len = 20) {
    # Mot de passe alphanumérique (pas de caractères réservés d'URL à encoder).
    -join ((48..57) + (65..90) + (97..122) | Get-Random -Count $len | ForEach-Object {[char]$_})
}

Write-Host @"
============================================================
   Installation de CV Agent Pro  (Windows 10 / 11)
============================================================
"@ -ForegroundColor Cyan

# ─── 0. Prérequis de base ────────────────────────────────────────────────────
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    throw "winget est introuvable. Installez « App Installer » depuis le Microsoft Store, puis relancez."
}

# ─── 1. PostgreSQL 17 ────────────────────────────────────────────────────────
Step "1/6  PostgreSQL"
$pgBin = "C:\Program Files\PostgreSQL\17\bin"
$pgSuperPw = $null

if (Test-Path "$pgBin\psql.exe") {
    Ok "PostgreSQL 17 déjà installé."
    $secure = Read-Host "Mot de passe du superutilisateur 'postgres' (pour créer la base)" -AsSecureString
    $pgSuperPw = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
} else {
    $pgSuperPw = New-Password 24
    Info "Installation silencieuse de PostgreSQL 17 (peut prendre quelques minutes)…"
    winget install -e --id PostgreSQL.PostgreSQL.17 --accept-source-agreements --accept-package-agreements `
        --override "--mode unattended --unattendedmodeui minimal --superpassword `"$pgSuperPw`" --serverport 5432 --enable-components server,commandlinetools" | Out-Null
    if (-not (Test-Path "$pgBin\psql.exe")) {
        throw "PostgreSQL ne s'est pas installé au chemin attendu ($pgBin). Installez-le manuellement puis relancez."
    }
    # Sauvegarde du mot de passe superutilisateur pour l'admin (fichier restreint).
    $pwFile = Join-Path $InstallDir "postgres-superuser-password.txt"
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    "Mot de passe du superutilisateur PostgreSQL 'postgres' :`r`n$pgSuperPw" | Set-Content -Encoding UTF8 $pwFile
    Ok "PostgreSQL installé. Mot de passe superutilisateur enregistré dans $pwFile"
}

# ─── 2. Ollama (optionnel) ───────────────────────────────────────────────────
Step "2/6  LLM local (Ollama)"
if ($InstallOllama) {
    Info "Installation d'Ollama…"
    winget install -e --id Ollama.Ollama --accept-source-agreements --accept-package-agreements | Out-Null
    Ok "Ollama installé. Pensez à télécharger un modèle : ollama pull qwen2.5:14b"
} else {
    Info "Ollama non installé (option -InstallOllama absente). Vous pourrez utiliser le cloud OpenRouter."
}

# ─── 3. Rôle + base cvagent ──────────────────────────────────────────────────
Step "3/6  Base de données cvagent"
$cvPw = New-Password 24
$env:PGPASSWORD = $pgSuperPw
$psql = "$pgBin\psql.exe"

$roleExists = (& $psql -U postgres -h localhost -tAc "SELECT 1 FROM pg_roles WHERE rolname='cvagent'") 2>$null
if ($roleExists -ne "1") {
    & $psql -U postgres -h localhost -c "CREATE ROLE cvagent LOGIN PASSWORD '$cvPw'" | Out-Null
    Ok "Rôle 'cvagent' créé."
} else {
    & $psql -U postgres -h localhost -c "ALTER ROLE cvagent LOGIN PASSWORD '$cvPw'" | Out-Null
    Warn "Rôle 'cvagent' déjà présent — mot de passe réinitialisé."
}
$dbExists = (& $psql -U postgres -h localhost -tAc "SELECT 1 FROM pg_database WHERE datname='cvagent'") 2>$null
if ($dbExists -ne "1") {
    & $psql -U postgres -h localhost -c "CREATE DATABASE cvagent OWNER cvagent" | Out-Null
    Ok "Base 'cvagent' créée."
} else {
    & $psql -U postgres -h localhost -c "ALTER DATABASE cvagent OWNER TO cvagent" | Out-Null
    Warn "Base 'cvagent' déjà présente — conservée."
}
& $psql -U postgres -h localhost -d cvagent -c "GRANT ALL ON SCHEMA public TO cvagent" | Out-Null
Remove-Item Env:\PGPASSWORD

# ─── 4. Variables d'environnement machine ────────────────────────────────────
Step "4/6  Configuration (variables d'environnement)"
$secret = -join ((1..64) | ForEach-Object { "{0:x}" -f (Get-Random -Max 16) })
$dbUrl = "postgresql://cvagent:$cvPw@localhost:5432/cvagent"
[Environment]::SetEnvironmentVariable("CV_AGENT_DB_URL", $dbUrl, "Machine")
[Environment]::SetEnvironmentVariable("CV_AGENT_SECRET", $secret, "Machine")
$env:CV_AGENT_DB_URL = $dbUrl      # pour le lancement immédiat ci-dessous
$env:CV_AGENT_SECRET = $secret
Ok "CV_AGENT_DB_URL et CV_AGENT_SECRET définis (niveau machine)."

# ─── 5. Application ──────────────────────────────────────────────────────────
Step "5/6  Application"
$appSrc = Join-Path $Here "Application\CV-Agent"
$appExe = Join-Path $InstallDir "CV-Agent.exe"
if (-not (Test-Path "$appSrc\CV-Agent.exe")) {
    throw "Application introuvable dans $appSrc. Vérifiez le contenu du dossier iso\Application."
}
Info "Copie de l'application vers $InstallDir…"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Copy-Item "$appSrc\*" -Destination $InstallDir -Recurse -Force
Ok "Application copiée."

# Raccourcis (Bureau + menu Démarrer).
$shell = New-Object -ComObject WScript.Shell
foreach ($dir in @([Environment]::GetFolderPath("CommonDesktopDirectory"),
                   (Join-Path $env:ProgramData "Microsoft\Windows\Start Menu\Programs"))) {
    $lnk = $shell.CreateShortcut((Join-Path $dir "CV Agent Pro.lnk"))
    $lnk.TargetPath = $appExe
    $lnk.WorkingDirectory = $InstallDir
    $lnk.Description = "CV Agent Pro — tri et extraction des CV"
    $lnk.Save()
}
Ok "Raccourcis créés (Bureau + menu Démarrer)."

# ─── 6. Lancement ────────────────────────────────────────────────────────────
Step "6/6  Démarrage"
Info "Lancement de CV Agent Pro (le schéma de base se crée au 1er démarrage)…"
# L'application (icône près de l'horloge) ouvre elle-même le navigateur sur la
# page de création d'admin, sur un port local libre choisi automatiquement.
Start-Process -FilePath $appExe -WorkingDirectory $InstallDir

Write-Host @"

============================================================
   Installation terminée.
============================================================
  - Application    : $InstallDir\CV-Agent.exe  (icône dans la zone de notification)
  - L'interface web s'ouvre automatiquement dans votre navigateur.
  - 1re étape      : créez le compte administrateur sur la page /setup
  - Paramètres     : Administration -> Paramètres (IMAP + Sécurité IMAP, LLM, SMTP)
  - Manuels        : dossier Manuels\ de ce support (Utilisateur / Déploiement)

  Pour un accès PARTAGÉ depuis d'autres postes du réseau (mode serveur LAN
  sur le port $AppPort), suivez le « Manuel de déploiement » -> section
  « Démarrage automatique » / exposition réseau.
============================================================
"@ -ForegroundColor Green
