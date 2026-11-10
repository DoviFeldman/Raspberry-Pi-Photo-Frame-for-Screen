#!/bin/bash
# Pi Photo TV installer. Run on the Pi (needs internet once, e.g. via your hotspot):
#   sudo ./install.sh
set -euo pipefail

if [ "$(id -u)" != 0 ]; then echo "Please run with sudo:  sudo ./install.sh"; exit 1; fi
HERE="$(cd "$(dirname "$0")" && pwd)"
APP=/opt/pitv
DATA=/var/lib/pitv

echo "==> Installing packages (this takes a while on a Pi Zero)…"
apt-get update
apt-get install -y python3 python3-pil hostapd dnsmasq-base iw rfkill fonts-dejavu-core avahi-daemon
# heif-dec opens iPhone HEIC and AVIF photos (phones usually convert them first anyway).
apt-get install -y libheif-examples || true
# Keep logs across power cuts (capped at 50 MB) so problems can be looked at later.
mkdir -p /var/log/journal /etc/systemd/journald.conf.d
printf '[Journal]\nStorage=persistent\nSystemMaxUse=50M\n' > /etc/systemd/journald.conf.d/pitv.conf
systemctl restart systemd-journald || true
# We run our own hostapd/dnsmasq; make sure the stock services stay out of the way.
systemctl disable --now hostapd 2>/dev/null || true
systemctl disable --now dnsmasq 2>/dev/null || true

echo "==> Copying the app to $APP"
mkdir -p "$APP" "$DATA"
cp -r "$HERE/pitv/." "$APP/"
cp "$HERE"/systemd/*.service /etc/systemd/system/

echo "==> Wifi setup"
mkdir -p /etc/NetworkManager/conf.d
cat > /etc/NetworkManager/conf.d/pitv.conf <<'EOF'
[keyfile]
unmanaged-devices=interface-name:uap0
EOF
# Wifi is blocked until a country is set.
raspi-config nonint do_wifi_country US 2>/dev/null || iw reg set US || true
rfkill unblock wlan || true
# Easy name for phones on the hotspot: http://pitv.local
if [ "$(hostname)" != "pitv" ]; then
  raspi-config nonint do_hostname pitv 2>/dev/null || hostnamectl set-hostname pitv
fi

echo
echo "Which hotspot should the Pi join by itself? (it must be on 2.4 GHz —"
echo "on iPhone turn on 'Maximize Compatibility'). Nearby wifis:"
nmcli -t -f SSID device wifi list 2>/dev/null | sort -u | grep -v '^$' | sed 's/^/   /' || true
read -r -p "Hotspot name exactly as shown [press Enter to skip]: " SSID || SSID=""
if [ -n "$SSID" ]; then
  read -r -s -p "Hotspot password: " PSK || PSK=""; echo
  nmcli connection delete id "$SSID" >/dev/null 2>&1 || true
  if [ -n "$PSK" ]; then
    nmcli connection add type wifi ifname wlan0 con-name "$SSID" ssid "$SSID" \
      connection.autoconnect yes connection.autoconnect-priority 10 \
      wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$PSK" >/dev/null
  else
    nmcli connection add type wifi ifname wlan0 con-name "$SSID" ssid "$SSID" \
      connection.autoconnect yes connection.autoconnect-priority 10 >/dev/null
  fi
  echo "Saved \"$SSID\". You can add more wifis later on the Settings page."
fi

echo "==> TV screen setup"
BOOT=/boot/firmware; [ -d "$BOOT" ] || BOOT=/boot
CMDLINE="$BOOT/cmdline.txt"
cp -n "$CMDLINE" "$CMDLINE.before-pitv" || true
# Keep HDMI on even if the TV is plugged in after boot, hide boot text and the cursor.
for opt in "video=HDMI-A-1:1920x1080@60D" consoleblank=0 vt.global_cursor_default=0 logo.nologo quiet loglevel=3; do
  key="${opt%%=*}"
  if ! grep -qE "(^| )${key}(=| |$)" "$CMDLINE"; then
    sed -i "1 s|\$| $opt|" "$CMDLINE"
  fi
done
grep -q '^disable_splash=1' "$BOOT/config.txt" || echo 'disable_splash=1' >> "$BOOT/config.txt"
grep -q '^hdmi_force_hotplug=1' "$BOOT/config.txt" || echo 'hdmi_force_hotplug=1' >> "$BOOT/config.txt"
# The login prompt would draw over the photos.
systemctl disable getty@tty1 2>/dev/null || true

echo "==> Turning on the services"
systemctl daemon-reload
systemctl enable pitv-net pitv-web pitv-slideshow

# Starting the TV wifi live can drop this SSH session halfway, so we reboot
# instead: everything comes up cleanly together.
echo
echo "All set! Restarting the Pi in 10 seconds to finish (about 2 minutes)."
echo "Then on your phone join the wifi \"raspberry pi tv\" — a page pops up."
sleep 10
systemctl reboot
