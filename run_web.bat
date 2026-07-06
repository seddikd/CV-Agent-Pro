@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat (
    echo Environnement virtuel introuvable. Lance d'abord l'installateur :
    echo   install.bat
    pause
    exit /b 1
)
call .venv\Scripts\activate.bat
python -m uvicorn webapp:app --host 0.0.0.0 --port 6060 --log-level info
