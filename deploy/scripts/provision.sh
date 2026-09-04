#!/usr/bin/env bash
set -euo pipefail

if [[ ${1:-} != "--apply" ]]; then
  echo "Usage: sudo $0 --apply"
  exit 2
fi

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv nginx xvfb x11vnc novnc websockify ca-certificates

id dzmmbot >/dev/null 2>&1 || useradd --system --home /var/lib/dzmmbot --create-home --shell /usr/sbin/nologin dzmmbot
install -d -o dzmmbot -g dzmmbot -m 0750 /opt/dzmmbot/releases /var/lib/dzmmbot/data /var/log/dzmmbot
install -d -o root -g dzmmbot -m 0750 /etc/dzmmbot
python3 -m venv /opt/dzmmbot/venv
chown -R dzmmbot:dzmmbot /opt/dzmmbot/venv

echo "Provisioning complete. Install the environment file, systemd units and Nginx config next."
