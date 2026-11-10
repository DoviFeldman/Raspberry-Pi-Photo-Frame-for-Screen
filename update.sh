#!/bin/bash
# Update the program on an already-installed Pi without reinstalling or rebooting.
# Run on the Pi from this folder:   sudo ./update.sh
set -euo pipefail
if [ "$(id -u)" != 0 ]; then echo "Please run with sudo:  sudo ./update.sh"; exit 1; fi
HERE="$(cd "$(dirname "$0")" && pwd)"

cp -r "$HERE/pitv/." /opt/pitv/
cp "$HERE"/systemd/*.service /etc/systemd/system/
command -v heif-dec >/dev/null || apt-get install -y -q libheif-examples || true
if [ ! -f /etc/systemd/journald.conf.d/pitv.conf ]; then
  mkdir -p /var/log/journal /etc/systemd/journald.conf.d
  printf '[Journal]\nStorage=persistent\nSystemMaxUse=50M\n' > /etc/systemd/journald.conf.d/pitv.conf
  systemctl restart systemd-journald || true
fi
systemctl daemon-reload
# The website and slideshow restart in a second. The wifi part is left alone
# so nobody gets kicked off; it picks up changes at the next power-on.
systemctl restart pitv-web pitv-slideshow
echo "Updated. Website and slideshow restarted."
