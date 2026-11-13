#!/usr/bin/env bash
# Baut den Windows-Installer (dist/Tally-Setup-<Version>.exe) unter Linux.
#
# Inhalt: offizielles "embeddable" Python für Windows + alle Abhängigkeiten als
# Windows-Wheels + der Programmcode. Auf dem Zielrechner muss nichts weiter
# installiert sein. Es werden KEINE Zugangsdaten (config.json,
# service_account.json, app_credentials.json) eingepackt.
#
# Voraussetzungen: python3 mit pip, curl, unzip, makensis (Paket "nsis").
set -euo pipefail

PY_VERSION="3.13.17"
# SHA-256 von python-<Version>-embed-amd64.zip (python.org). Bei einem
# Versionswechsel neu eintragen.
PY_SHA256="9e35319bffedab8b36ad44d8f377cb4f1733bcec257a0b6d04d94f01486ddb38"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
BUILD="$ROOT/build/windows"
STAGE="$BUILD/stage"
CACHE="$BUILD/cache"
DIST="$ROOT/dist"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/votebot/__init__.py")"
PIP="${PIP:-python3 -m pip}"
[ -x "$ROOT/.venv/bin/python" ] && PIP="$ROOT/.venv/bin/python -m pip"

echo "== Tally $VERSION: Windows-Installer bauen =="
rm -rf "$STAGE"
mkdir -p "$STAGE/python" "$STAGE/app" "$CACHE" "$DIST"

# 1) Eingebettetes Python
ZIP="$CACHE/python-$PY_VERSION-embed-amd64.zip"
if [ ! -f "$ZIP" ]; then
  echo "-- Lade Python $PY_VERSION (embed, amd64)"
  curl -fL --retry 3 -o "$ZIP.part" "https://www.python.org/ftp/python/$PY_VERSION/python-$PY_VERSION-embed-amd64.zip"
  mv "$ZIP.part" "$ZIP"
fi
echo "$PY_SHA256  $ZIP" | sha256sum -c - >/dev/null || { echo "FEHLER: Prüfsumme des Python-Archivs stimmt nicht." >&2; exit 1; }
unzip -q "$ZIP" -d "$STAGE/python"

# Suchpfade des eingebetteten Pythons: eigene Pakete + Programmordner.
PTH="$(basename "$(ls "$STAGE"/python/python3*._pth)")"
printf '%s\r\n' "${PTH%._pth}.zip" "." "Lib\\site-packages" "..\\app" "import site" > "$STAGE/python/$PTH"

# 2) Abhängigkeiten als Windows-Wheels (nur Binär-Wheels, exakt gepinnt)
echo "-- Installiere Abhängigkeiten (win_amd64)"
$PIP install --quiet --disable-pip-version-check --no-deps \
  --target "$STAGE/python/Lib/site-packages" \
  --platform win_amd64 --python-version "${PY_VERSION%.*}" --implementation cp --abi "cp${PY_VERSION%%.*}$(echo "$PY_VERSION" | cut -d. -f2)" \
  --only-binary=:all: -r "$HERE/requirements-win.txt"
rm -rf "$STAGE/python/Lib/site-packages/bin"
find "$STAGE/python" -name '__pycache__' -type d -prune -exec rm -rf {} +

if find "$STAGE/python" \( -name '*.so' -o -name '*.so.*' \) | grep -q .; then
  echo "FEHLER: Linux-Binärdateien im Paket gefunden." >&2; exit 1
fi

# 3) Programmcode (ohne Zugangsdaten und Laufzeitdaten)
cp "$ROOT/run.py" "$HERE/tally_win.py" "$ROOT/README.md" "$STAGE/app/"
cp -r "$ROOT/votebot" "$STAGE/app/votebot"
find "$STAGE/app" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$STAGE/app" \( -name '*.json' -o -name '*.csv' \) -print -delete | sed 's/^/   entfernt: /'

# 4) Installer
OUT="$DIST/Tally-Setup-$VERSION.exe"
echo "-- Erzeuge Installer"
# Windows verlangt für die Datei-Version genau vier Zahlen (4.0 -> 4.0.0.0, 4.0.1 -> 4.0.1.0).
VIVERSION="$(echo "$VERSION.0.0.0" | cut -d. -f1-4)"
( cd "$HERE" && makensis -V2 -DVERSION="$VERSION" -DVIVERSION="$VIVERSION" -DSTAGE="$STAGE" -DOUTFILE="$OUT" tally.nsi )
echo "== Fertig: $OUT ($(du -h "$OUT" | cut -f1)) =="
