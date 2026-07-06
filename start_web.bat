@echo off
REM Silent startup wrapper used by the Windows Scheduled Task at boot.
REM Logs all output to logs\web_startup.log (rotating each boot via append).

setlocal
cd /d "%~dp0"

if not exist logs mkdir logs

set LOG=logs\web_startup.log

echo. >> "%LOG%"
echo === CV Agent Web boot start at %DATE% %TIME% === >> "%LOG%"

if not exist .venv\Scripts\python.exe (
    echo [FATAL] Environnement virtuel introuvable : .venv\Scripts\python.exe >> "%LOG%"
    echo Lance d'abord l'installateur : install.bat >> "%LOG%"
    exit /b 1
)

REM Launch uvicorn. --workers 1 because APScheduler + SQLite need single process.
.venv\Scripts\python.exe -m uvicorn webapp:app --host 0.0.0.0 --port 6060 --log-level info --workers 1 >> "%LOG%" 2>&1

echo === CV Agent Web exited at %DATE% %TIME% (code %ERRORLEVEL%) === >> "%LOG%"
exit /b %ERRORLEVEL%
