# Remove the CV Agent Web Scheduled Task and the firewall rule.
#
# USAGE: Open PowerShell AS ADMINISTRATOR and run:
#   powershell -ExecutionPolicy Bypass -File D:\clab-labs\cv-agent\uninstall_autostart.ps1

$ErrorActionPreference = "Continue"

$TaskName   = "CV-Agent-Web"
$FwRuleName = "CV Agent Web (port 6060)"

$identity  = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "ERREUR : ce script doit etre execute en administrateur." -ForegroundColor Red
    exit 1
}

# Stop running instance
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    Write-Host "Arret de la tache si elle tourne..." -ForegroundColor Yellow
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    Write-Host "Suppression de la tache..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "[OK] Tache $TaskName supprimee" -ForegroundColor Green
} else {
    Write-Host "Aucune tache $TaskName trouvee." -ForegroundColor Gray
}

# Remove firewall rule
$rule = Get-NetFirewallRule -DisplayName $FwRuleName -ErrorAction SilentlyContinue
if ($rule) {
    Remove-NetFirewallRule -DisplayName $FwRuleName
    Write-Host "[OK] Regle pare-feu '$FwRuleName' supprimee" -ForegroundColor Green
} else {
    Write-Host "Aucune regle pare-feu trouvee." -ForegroundColor Gray
}

# Kill any orphan uvicorn / python process still listening
$pids = Get-NetTCPConnection -LocalPort 6060 -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
foreach ($processId in $pids) {
    try {
        Stop-Process -Id $processId -Force -ErrorAction Stop
        Write-Host "[OK] Processus PID $processId (port 6060) arrete" -ForegroundColor Green
    } catch {
        # ignore
    }
}

Write-Host ""
Write-Host "=== Desinstallation terminee ===" -ForegroundColor Cyan
