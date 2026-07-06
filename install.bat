@echo off
REM Installateur CV Agent — double-cliquez sur ce fichier.
REM Delegue le travail a install.ps1 (venv + dependances + bootstrap).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
echo.
pause
