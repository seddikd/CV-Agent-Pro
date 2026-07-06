# Install CV Agent Web as a Windows Scheduled Task that starts at boot.
# Also opens the LAN firewall port 6060.
#
# USAGE: Open PowerShell AS ADMINISTRATOR and run:
#   powershell -ExecutionPolicy Bypass -File D:\clab-labs\cv-agent\install_autostart.ps1

$ErrorActionPreference = "Stop"

# ---- Constants ---------------------------------------------------------------
$TaskName    = "CV-Agent-Web"
$ProjectPath = $PSScriptRoot   # dossier de ce script — projet relocalisable
$StartScript = Join-Path $ProjectPath "start_web.bat"
$Port        = 6060
$FwRuleName  = "CV Agent Web (port $Port)"

# ---- Admin check -------------------------------------------------------------
$identity  = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "ERREUR : ce script doit etre execute en administrateur." -ForegroundColor Red
    Write-Host "Clic droit sur PowerShell -> Executer en tant qu'administrateur." -ForegroundColor Yellow
    exit 1
}

# ---- Sanity checks -----------------------------------------------------------
if (-not (Test-Path $StartScript)) {
    Write-Host "ERREUR : $StartScript introuvable." -ForegroundColor Red
    exit 1
}
if (-not (Test-Path (Join-Path $ProjectPath ".venv\Scripts\python.exe"))) {
    Write-Host "AVERT : .venv n'existe pas encore. Cree-le d'abord :" -ForegroundColor Yellow
    Write-Host "  cd $ProjectPath" -ForegroundColor Gray
    Write-Host "  python -m venv .venv" -ForegroundColor Gray
    Write-Host "  .\.venv\Scripts\Activate.ps1" -ForegroundColor Gray
    Write-Host "  pip install -r requirements.txt" -ForegroundColor Gray
    Write-Host "  python bootstrap.py" -ForegroundColor Gray
    Write-Host "Puis relance ce script." -ForegroundColor Yellow
    exit 1
}

# ---- Remove existing task ----------------------------------------------------
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Tache existante detectee, suppression..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# ---- Build task definition ---------------------------------------------------
$action = New-ScheduledTaskAction -Execute $StartScript -WorkingDirectory $ProjectPath

$trigger = New-ScheduledTaskTrigger -AtStartup
$trigger.Delay = "PT1M"  # Wait 1 minute after boot (network ready)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -MultipleInstances IgnoreNew

# ---- Credentials -------------------------------------------------------------
Write-Host ""
Write-Host "Le service doit tourner sous un compte utilisateur (pas SYSTEM)" -ForegroundColor Cyan
Write-Host "pour acceder a Python installe dans AppData." -ForegroundColor Cyan
Write-Host ""
$defaultUser = "$env:USERDOMAIN\$env:USERNAME"
$account = Read-Host "Compte Windows [$defaultUser]"
if ([string]::IsNullOrWhiteSpace($account)) { $account = $defaultUser }

$securePwd = Read-Host "Mot de passe Windows pour $account" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePwd)
$plainPwd = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)

# ---- Register the task -------------------------------------------------------
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -User $account `
    -Password $plainPwd `
    -RunLevel Highest `
    -Description "Demarrage automatique de CV Agent Web a chaque boot" | Out-Null

$plainPwd = $null   # don't keep in memory
[GC]::Collect()

Write-Host ""
Write-Host "[OK] Tache planifiee installee : $TaskName" -ForegroundColor Green

# ---- Firewall rule -----------------------------------------------------------
$existingRule = Get-NetFirewallRule -DisplayName $FwRuleName -ErrorAction SilentlyContinue
if ($existingRule) {
    Write-Host "Regle pare-feu deja existante, mise a jour..." -ForegroundColor Yellow
    Remove-NetFirewallRule -DisplayName $FwRuleName
}

New-NetFirewallRule `
    -DisplayName $FwRuleName `
    -Description "Autorise les acces LAN au tableau de bord RH" `
    -Direction Inbound `
    -LocalPort $Port `
    -Protocol TCP `
    -Action Allow `
    -Profile Domain,Private | Out-Null

Write-Host "[OK] Regle pare-feu inbound TCP $Port ouverte (profils Domain+Private)" -ForegroundColor Green

# ---- Summary -----------------------------------------------------------------
Write-Host ""
Write-Host "=== Installation terminee ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Pour demarrer maintenant sans rebooter :" -ForegroundColor White
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'" -ForegroundColor Gray
Write-Host ""
Write-Host "Pour verifier l'etat :" -ForegroundColor White
Write-Host "  Get-ScheduledTask -TaskName '$TaskName' | Get-ScheduledTaskInfo" -ForegroundColor Gray
Write-Host ""
Write-Host "Acces depuis le LAN :" -ForegroundColor White
$ips = Get-NetIPAddress -AddressFamily IPv4 -PrefixOrigin Manual,Dhcp -ErrorAction SilentlyContinue |
       Where-Object { $_.IPAddress -notlike "169.254.*" -and $_.IPAddress -ne "127.0.0.1" }
foreach ($ip in $ips) {
    Write-Host "  http://$($ip.IPAddress):$Port" -ForegroundColor Gray
}
Write-Host ""
Write-Host "Logs : $ProjectPath\logs\web_startup.log" -ForegroundColor White
