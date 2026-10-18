@echo off
REM Votebot-Starter fuer Windows: legt beim ersten Start eine virtuelle
REM Umgebung an, installiert die Abhaengigkeiten und startet das Dashboard.
cd /d "%~dp0"

if not exist ".venv" (
  echo Erstelle virtuelle Umgebung ^(einmalig^)...
  python -m venv .venv
)

call ".venv\Scripts\activate.bat"

python -c "import uvicorn" >nul 2>&1
if errorlevel 1 (
  echo Installiere Abhaengigkeiten ^(einmalig, kann etwas dauern^)...
  python -m pip install --upgrade pip >nul
  pip install -r requirements.txt
)

echo Starte Votebot...
python run.py
pause
