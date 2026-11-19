#!/bin/bash
# THIRD VERSION: home wifi + Tailscale, so family far away can add photos.
# Puts the Pi on your private Tailscale network. Anyone you share it with
# (they install the free Tailscale app) can open its website from anywhere.
# The address is NOT shown on the TV - only you get it, at the end.
#
# Run on the Pi:  sudo ./tailscale-setup.sh [name-in-tailscale]
# (install.sh --tailscale runs this for you.) Safe to run again.
set -euo pipefail
if [ "$(id -u)" != 0 ]; then echo "Please run with sudo:  sudo ./tailscale-setup.sh"; exit 1; fi
NAME="${1:-photo-tv}"

if ! command -v tailscale >/dev/null; then
  echo "==> Installing Tailscale (from tailscale.com)…"
  curl -fsSL https://tailscale.com/install.sh | sh
fi
systemctl enable --now tailscaled

if ! tailscale status >/dev/null 2>&1; then
  echo
  echo "==> Open the link below on your phone or computer and log in to YOUR"
  echo "    Tailscale account to add this Pi. (Waiting until you do…)"
fi
tailscale up --hostname="$NAME"

python3 - /var/lib/pitv/config.json <<'PY'
import json, sys
p = sys.argv[1]
try:
    c = json.load(open(p))
except (OSError, ValueError):
    c = {}
c["tailscale"] = True
json.dump(c, open(p, "w"))
PY

IP="$(tailscale ip -4)"
echo
echo "Tailscale is on. From anywhere, on a phone with the Tailscale app that"
echo "can see this Pi, open:   http://$IP"
echo
echo "Two things to do once at https://login.tailscale.com/admin/machines :"
echo " 1. On \"$NAME\" click ... > Disable key expiry (otherwise it stops"
echo "    working after 6 months)."
echo " 2. To let someone else in: ... > Share, and send them the link."
