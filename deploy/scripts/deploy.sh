#!/usr/bin/env bash
set -euo pipefail

archive=${1:?Usage: deploy.sh RELEASE_TARBALL RELEASE_ID}
release_id=${2:?Usage: deploy.sh RELEASE_TARBALL RELEASE_ID}
release_dir="/opt/dzmmbot/releases/${release_id}"

test -f "$archive"
test ! -e "$release_dir"
install -d -o dzmmbot -g dzmmbot -m 0750 "$release_dir"
tar -xzf "$archive" -C "$release_dir"
chown -R dzmmbot:dzmmbot "$release_dir"
/opt/dzmmbot/venv/bin/pip install -r "$release_dir/source/requirements.txt"
PLAYWRIGHT_BROWSERS_PATH=/opt/dzmmbot/playwright /opt/dzmmbot/venv/bin/playwright install-deps chromium
PLAYWRIGHT_BROWSERS_PATH=/opt/dzmmbot/playwright /opt/dzmmbot/venv/bin/playwright install chromium
chown -R dzmmbot:dzmmbot /opt/dzmmbot/playwright
ln -sfn "$release_dir" /opt/dzmmbot/current.new
mv -Tf /opt/dzmmbot/current.new /opt/dzmmbot/current
systemctl restart dzmmbot-display dzmmbot-browser dzmmbot
