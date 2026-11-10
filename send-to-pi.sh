#!/bin/bash
# Copies this folder to the Pi and runs the installer. You type the Pi's
# password once; the other steps reuse that login.
set -e
PI="${1:-raspberry@pitv.local}"
O=(-o ControlMaster=auto -o ControlPath="$HOME/.ssh/cm-pitv" -o ControlPersist=30m)
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "Logging in to the Pi — type its password and press Enter (nothing shows while you type):"
ssh "${O[@]}" "$PI" true
echo "Copying the program…"
# Always lands in ~/PiPhotoTV on the Pi, whatever this folder is called here.
COPYFILE_DISABLE=1 tar czf - -C "$HERE" --exclude .git --exclude .DS_Store . 2>/dev/null |
  ssh "${O[@]}" "$PI" 'rm -rf ~/PiPhotoTV && mkdir ~/PiPhotoTV && tar xzf - -C ~/PiPhotoTV 2>/dev/null'
echo "Running the installer…"
ssh "${O[@]}" -t "$PI" 'cd ~/PiPhotoTV && sudo ./install.sh'
