#!/usr/bin/env bash
# Votebot-Starter für Linux/macOS: legt beim ersten Start eine virtuelle
# Umgebung an, installiert die Abhängigkeiten und startet das Dashboard.
set -e
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
VENV=".venv"

if [ ! -d "$VENV" ]; then
  echo "Erstelle virtuelle Umgebung (einmalig)..."
  "$PYTHON" -m venv "$VENV"
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"

# Abhängigkeiten installieren, falls uvicorn noch fehlt.
if ! python -c "import uvicorn" >/dev/null 2>&1; then
  echo "Installiere Abhängigkeiten (einmalig, kann etwas dauern)..."
  pip install --upgrade pip >/dev/null
  pip install -r requirements.txt
fi

echo "Starte Votebot..."
python run.py
