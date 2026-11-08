#!/usr/bin/env bash
# Install or update Veggohandla as a systemd service – e.g. on a Raspberry Pi.
#
#   ./deploy/install.sh                 install or update, then (re)start the service
#   ./deploy/install.sh --print-unit    only print the systemd unit that would be installed
#   PORT=8080 ./deploy/install.sh       use another port (default 8000)
#
# Run it from a clone of the repository as the user that should run the app (not root);
# sudo is used for the systemd part. To update later: git pull && ./deploy/install.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE="veggohandla"
PORT="${PORT:-8000}"
RUN_USER="$(id -un)"

unit() {
  cat <<EOF
[Unit]
Description=Veggohandla - weekly vegan meal planner and shopping list
Wants=network-online.target
After=network-online.target time-sync.target

[Service]
User=${RUN_USER}
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/.venv/bin/python manage.py serve --host 0.0.0.0 --port ${PORT}
Environment=PYTHONUNBUFFERED=1
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full

[Install]
WantedBy=multi-user.target
EOF
}

if [ "${1:-}" = "--print-unit" ]; then
  unit
  exit 0
fi

if [ "$(id -u)" -eq 0 ]; then
  echo "Kör skriptet som vanlig användare, inte som root (sudo används där det behövs)." >&2
  exit 1
fi
if ! command -v systemctl >/dev/null; then
  echo "Hittar inte systemd (systemctl). Kör appen med: uv run manage.py serve" >&2
  exit 1
fi

if ! command -v uv >/dev/null && [ ! -x "$HOME/.local/bin/uv" ]; then
  echo "==> Installerar uv (pakethanterare för Python)"
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
UV="$(command -v uv || echo "$HOME/.local/bin/uv")"

echo "==> Installerar Python och beroenden"
cd "$APP_DIR"
"$UV" sync --frozen --no-dev
"$APP_DIR/.venv/bin/python" manage.py check

echo "==> Installerar och startar tjänsten ${SERVICE}"
unit | sudo tee "/etc/systemd/system/${SERVICE}.service" >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE}" >/dev/null
sudo systemctl restart "${SERVICE}"

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
echo "Klart! Veggohandla körs och startar automatiskt när datorn startar."
echo "  Öppna:      http://$(hostname).local:${PORT}   eller   http://${IP:-<ip-adress>}:${PORT}"
echo "  Logg:       journalctl -u ${SERVICE} -f"
echo "  Uppdatera:  git pull && ./deploy/install.sh"
