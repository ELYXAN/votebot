#!/usr/bin/env bash
# Richtet Votebot als systemd-User-Dienst ein, damit es dauerhaft im Hintergrund
# läuft (Dashboard immer unter http://localhost:17563 erreichbar) und nach einem
# Neustart automatisch wieder hochkommt.
#
#   ./install-service.sh            # installieren & starten
#   ./install-service.sh --remove   # Dienst entfernen
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
UNIT_DIR="$HOME/.config/systemd/user"
UNIT="$UNIT_DIR/votebot.service"

if [ "$1" = "--remove" ]; then
  systemctl --user disable --now votebot.service 2>/dev/null || true
  rm -f "$UNIT"
  systemctl --user daemon-reload
  echo "Votebot-Dienst entfernt."
  exit 0
fi

# Venv anlegen/Abhängigkeiten installieren, falls noch nicht geschehen.
if [ ! -x "$DIR/.venv/bin/python" ]; then
  echo "Erstelle virtuelle Umgebung und installiere Abhängigkeiten..."
  python3 -m venv "$DIR/.venv"
  "$DIR/.venv/bin/pip" install --upgrade pip >/dev/null
  "$DIR/.venv/bin/pip" install -r "$DIR/requirements.txt"
fi

mkdir -p "$UNIT_DIR"
cat > "$UNIT" <<UNIT
[Unit]
Description=Tally - Twitch Vote Tracker Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$DIR
ExecStart=$DIR/.venv/bin/python $DIR/run.py
Environment=PYTHONUNBUFFERED=1
Environment=VOTEBOT_NO_BROWSER=1
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
UNIT

systemctl --user daemon-reload
systemctl --user enable --now votebot.service

echo ""
echo "✓ Tally-Dienst installiert und gestartet (votebot.service)."
echo "  Dashboard:  http://localhost:17563"
echo "  Status:     systemctl --user status votebot"
echo "  Logs:       journalctl --user -u votebot -f"
echo "  Neustart:   systemctl --user restart votebot"
echo "  Stoppen:    systemctl --user stop votebot"
echo "  Entfernen:  ./install-service.sh --remove"
echo ""
echo "Damit der Dienst auch OHNE Login/nach Reboot läuft, einmalig ausführen:"
echo "  sudo loginctl enable-linger $USER"
