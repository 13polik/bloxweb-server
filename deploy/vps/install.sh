#!/usr/bin/env bash
# Installs or updates BloxWeb on the VPS next to the other apps, without touching them.
# Run as root from the folder holding the unpacked code:  bash deploy/vps/install.sh
# Layout: code in /opt/bloxweb/app, Python env in /opt/bloxweb/venv, data in /opt/bloxweb/data,
# settings in /etc/bloxweb/env, service "bloxweb" on 127.0.0.1:8094, Caddy site HOST below.
set -euo pipefail
HOST_NAME="${BLOXWEB_HOST:-bloxweb.158-220-75-118.sslip.io}"
SRC="$(cd "$(dirname "$0")/../.." && pwd)"

id bloxweb >/dev/null 2>&1 || useradd --system --home /opt/bloxweb --shell /usr/sbin/nologin bloxweb
install -d -o bloxweb -g bloxweb -m 755 /opt/bloxweb /opt/bloxweb/app /opt/bloxweb/data
install -d -m 750 -g bloxweb /etc/bloxweb

# Code: replace the app folder with the new version (data stays in /opt/bloxweb/data).
if [ "$SRC" != /opt/bloxweb/app ]; then
  rm -rf /opt/bloxweb/app.new && cp -a "$SRC" /opt/bloxweb/app.new
  rm -rf /opt/bloxweb/app.old && mv /opt/bloxweb/app /opt/bloxweb/app.old && mv /opt/bloxweb/app.new /opt/bloxweb/app
  chown -R bloxweb:bloxweb /opt/bloxweb/app
fi

# Python environment (Ubuntu 24.04 ships Python 3.12).
command -v python3 >/dev/null
dpkg -s python3-venv >/dev/null 2>&1 || apt-get install -y python3-venv
[ -x /opt/bloxweb/venv/bin/python ] || python3 -m venv /opt/bloxweb/venv
/opt/bloxweb/venv/bin/pip install --quiet --upgrade pip
/opt/bloxweb/venv/bin/pip install --quiet -r /opt/bloxweb/app/requirements.txt
chown -R bloxweb:bloxweb /opt/bloxweb/venv

# Settings: created once, never overwritten (secrets are added by hand).
if [ ! -f /etc/bloxweb/env ]; then
  cat > /etc/bloxweb/env <<ENV
HOST=127.0.0.1
PORT=8094
DATA_DIR=/opt/bloxweb/data
BEHIND_PROXY=1
BLOX_AI_URL=https://bloxweb-ai.krystianbryla636.workers.dev
# Without DATABASE_URL the server keeps its data in SQLite in /opt/bloxweb/data.
# DATABASE_URL=postgresql://...
# BLOX_AI_KEY=...
ENV
fi
chown root:bloxweb /etc/bloxweb/env && chmod 640 /etc/bloxweb/env

install -m 644 /opt/bloxweb/app/deploy/vps/bloxweb.service /etc/systemd/system/bloxweb.service
systemctl daemon-reload
systemctl enable --now bloxweb >/dev/null
systemctl restart bloxweb

# Caddy: add one site for BloxWeb (HTTPS certificate is automatic). Other sites are left as they are.
if ! grep -q "^$HOST_NAME " /etc/caddy/Caddyfile; then
  # The new config is checked as a copy first, so a mistake can never break the existing sites.
  cp /etc/caddy/Caddyfile "/etc/caddy/Caddyfile.before-bloxweb.$(date +%Y%m%d%H%M%S)"
  cp /etc/caddy/Caddyfile /tmp/Caddyfile.bloxweb
  printf '\n%s {\n    encode gzip\n    reverse_proxy 127.0.0.1:8094\n}\n' "$HOST_NAME" >> /tmp/Caddyfile.bloxweb
  caddy validate --config /tmp/Caddyfile.bloxweb --adapter caddyfile >/dev/null
  install -m 644 /tmp/Caddyfile.bloxweb /etc/caddy/Caddyfile && rm -f /tmp/Caddyfile.bloxweb
  systemctl reload caddy
fi
echo "BloxWeb installed: https://$HOST_NAME"
