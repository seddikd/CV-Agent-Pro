#Requires -RunAsAdministrator
<#
    Installation autonome de PostgreSQL 17 (secours / serveur dédié).

    L'installateur principal (..\Installer.ps1) installe déjà PostgreSQL. Ce
    script sert si vous voulez ne poser QUE la base (ex. sur un serveur dédié),
    ou si l'étape PostgreSQL de l'installateur principal a échoué.

    Il installe PostgreSQL 17 via winget en mode silencieux, avec un mot de passe
    superutilisateur généré (enregistré dans un fichier), puis crée le rôle et la
    base « cvagent ». Affiche la valeur à mettre dans CV_AGENT_DB_URL.

    Usage :  powershell -ExecutionPolicy Bypass -File .\Installer-PostgreSQL.ps1
#>
param(
    [string]$PasswordFile = "$env:USERPROFILE\cvagent-postgres.txt"
)
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path

function New-Password([int]$len = 24) {
    -join ((48..57) + (65..90) + (97..122) | Get-Random -Count $len | ForEach-Object {[char]$_})
}

# Installeur hors ligne fourni à côté de ce script (sinon repli winget).
$pgLocalExe = Get-ChildItem $Here -Filter "postgresql-*-windows-x64.exe" -ErrorAction SilentlyContinue |
              Sort-Object Name -Descending | Select-Object -First 1
if (-not $pgLocalExe -and -not (Get-Command winget -ErrorAction SilentlyContinue)) {
    throw "winget introuvable et aucun installeur postgresql-*-windows-x64.exe à côté de ce script. Installez « App Installer » depuis le Microsoft Store."
}

$pgBin = "C:\Program Files\PostgreSQL\17\bin"
if (-not (Test-Path "$pgBin\psql.exe")) {
    $superPw = New-Password 24
    if ($pgLocalExe) {
        Write-Host "[i] Installation de PostgreSQL depuis le support ($($pgLocalExe.Name), hors ligne)…" -ForegroundColor Cyan
        Start-Process -FilePath $pgLocalExe.FullName -Wait -ArgumentList @(
            "--mode", "unattended", "--unattendedmodeui", "minimal",
            "--superpassword", $superPw, "--serverport", "5432",
            "--enable-components", "server,commandlinetools")
    } else {
        Write-Host "[i] Installation de PostgreSQL 17 via winget…" -ForegroundColor Cyan
        winget install -e --id PostgreSQL.PostgreSQL.17 --accept-source-agreements --accept-package-agreements `
            --override "--mode unattended --unattendedmodeui minimal --superpassword `"$superPw`" --serverport 5432 --enable-components server,commandlinetools" | Out-Null
    }
    "superutilisateur postgres : $superPw" | Set-Content -Encoding UTF8 $PasswordFile
    Write-Host "[OK] PostgreSQL installé. Mot de passe superutilisateur -> $PasswordFile" -ForegroundColor Green
} else {
    Write-Host "[OK] PostgreSQL 17 déjà présent." -ForegroundColor Green
    $secure = Read-Host "Mot de passe du superutilisateur 'postgres'" -AsSecureString
    $superPw = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
}

$cvPw = New-Password 24
$env:PGPASSWORD = $superPw
$psql = "$pgBin\psql.exe"
if ((& $psql -U postgres -h localhost -tAc "SELECT 1 FROM pg_roles WHERE rolname='cvagent'") -ne "1") {
    & $psql -U postgres -h localhost -c "CREATE ROLE cvagent LOGIN PASSWORD '$cvPw'" | Out-Null
} else {
    & $psql -U postgres -h localhost -c "ALTER ROLE cvagent LOGIN PASSWORD '$cvPw'" | Out-Null
}
if ((& $psql -U postgres -h localhost -tAc "SELECT 1 FROM pg_database WHERE datname='cvagent'") -ne "1") {
    & $psql -U postgres -h localhost -c "CREATE DATABASE cvagent OWNER cvagent" | Out-Null
} else {
    & $psql -U postgres -h localhost -c "ALTER DATABASE cvagent OWNER TO cvagent" | Out-Null
}
& $psql -U postgres -h localhost -d cvagent -c "GRANT ALL ON SCHEMA public TO cvagent" | Out-Null
Remove-Item Env:\PGPASSWORD

Write-Host ""
Write-Host "[OK] Rôle et base 'cvagent' prêts." -ForegroundColor Green
Write-Host "     Utilisez cette URL de connexion (variable CV_AGENT_DB_URL) :" -ForegroundColor Green
Write-Host "     postgresql://cvagent:$cvPw@localhost:5432/cvagent" -ForegroundColor Yellow
