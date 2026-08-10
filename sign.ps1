# Signe numériquement CV-Agent.exe et CV-Agent-Setup.exe avec un certificat .pfx.
#
# USAGE :
#   powershell -ExecutionPolicy Bypass -File .\sign.ps1 -Pfx "C:\chemin\cert.pfx" -Password "motdepasse"
#   (ou définis les variables d'env CV_SIGN_PFX et CV_SIGN_PASS puis lance sans arguments)
#
# NOTE : la signature nécessite un certificat de signature de code (OV ou EV) émis
# par une autorité reconnue. Un certificat auto-signé N'ÉLIMINE PAS l'alerte SmartScreen.

param(
    [string]$Pfx      = $env:CV_SIGN_PFX,
    [string]$Password = $env:CV_SIGN_PASS
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot

Write-Host ""
Write-Host "=== Signature CV Agent ===" -ForegroundColor Cyan

if (-not $Pfx -or -not (Test-Path $Pfx)) {
    Write-Host "ERREUR : certificat .pfx introuvable." -ForegroundColor Red
    Write-Host "Fournis -Pfx <chemin> -Password <mdp>, ou définis CV_SIGN_PFX / CV_SIGN_PASS." -ForegroundColor Yellow
    exit 1
}

# Localiser signtool.exe (Windows SDK)
$signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Filter signtool.exe -Recurse -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -match "x64" } |
    Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
if (-not $signtool) {
    $cmd = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($cmd) { $signtool = $cmd.Source }
}
if (-not $signtool) {
    Write-Host "ERREUR : signtool.exe introuvable (installe le Windows SDK)." -ForegroundColor Red
    Write-Host "  winget install --id Microsoft.WindowsSDK -e" -ForegroundColor Gray
    exit 1
}
Write-Host "signtool : $signtool" -ForegroundColor Gray

# Fichiers à signer (l'exe d'abord, puis l'installeur qui le contient)
$targets = @(
    (Join-Path $Root "dist\CV-Agent\CV-Agent.exe"),
    (Join-Path $Root "dist\CV-Agent-Setup.exe")
) | Where-Object { Test-Path $_ }

if (-not $targets) {
    Write-Host "ERREUR : rien à signer. Lance d'abord build_exe.ps1 / build_installer.ps1." -ForegroundColor Red
    exit 1
}

foreach ($t in $targets) {
    Write-Host "Signature : $t" -ForegroundColor White
    & $signtool sign /fd SHA256 /f $Pfx /p $Password `
        /tr http://timestamp.digicert.com /td SHA256 $t
    if ($LASTEXITCODE -ne 0) { Write-Host "ERREUR : signature échouée pour $t" -ForegroundColor Red; exit 1 }
}

Write-Host ""
Write-Host "[OK] Fichiers signés." -ForegroundColor Green
Write-Host "Vérifie avec :  `"$signtool`" verify /pa /v <fichier>" -ForegroundColor Gray
Write-Host ""
