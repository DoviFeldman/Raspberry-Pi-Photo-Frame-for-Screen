#!/bin/bash
# Saves a wifi on the Pi so it joins it by itself whenever it's nearby.
# Run on the Pi:  sudo ./add-wifi.sh "Wifi name" [priority]
# It asks for the password (paste it; nothing shows while you type).
set -e
SSID="$1"
PRIO="${2:-5}"
if [ -z "$SSID" ]; then echo 'Usage: sudo ./add-wifi.sh "Wifi name" [priority]'; exit 1; fi
read -r -s -p "Password for \"$SSID\" (paste it, then press Enter): " PSK; echo
nmcli connection delete id "$SSID" >/dev/null 2>&1 || true
if [ -n "$PSK" ]; then
  nmcli connection add type wifi ifname wlan0 con-name "$SSID" ssid "$SSID" \
    connection.autoconnect yes connection.autoconnect-priority "$PRIO" connection.autoconnect-retries 0 \
    wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$PSK" >/dev/null
else
  nmcli connection add type wifi ifname wlan0 con-name "$SSID" ssid "$SSID" \
    connection.autoconnect yes connection.autoconnect-priority "$PRIO" connection.autoconnect-retries 0 >/dev/null
fi
echo "Saved \"$SSID\"."
