PI PHOTO TV - a family photo slideshow on a Raspberry Pi
==========================================================

Send photos from any iPhone or Android to a TV. No app, no account, no
cloud. The Pi plugs into the TV with HDMI and plays all the photos as a
slideshow, forever.

THREE VERSIONS - pick one when you install
------------------------------------------
Both are in this same folder; the installer asks for one or the other.
You can switch later by running the installer again (photos are kept).

  1. HOME WIFI VERSION  (default - for any house that has wifi)
       sudo ./install.sh
     - The Pi joins the house wifi. Phones on that wifi open
       http://pitv.local  (the TV also shows the number address, like
       http://192.168.1.37, for phones where pitv.local doesn't work).
     - No extra wifi to join, and uploads go at the house wifi's speed.
     - It also joins your phone hotspot when the house wifi isn't there,
       for setup and troubleshooting. Once it's on the house wifi it stays
       on it.
     - "Add to Home Screen" on the phone gives a Photo TV icon that opens
       the page full screen, like an app. There's no install button or
       download anywhere.

  2. HOME WIFI + TAILSCALE VERSION  (family far away can add photos too)
       sudo ./install.sh --tailscale
     - Everything in the home wifi version, plus the Pi joins your free
       private Tailscale network. People you share it with install the
       Tailscale app once, and can then send photos from anywhere in the
       world to its Tailscale address (like http://100.101.102.103).
     - The Tailscale address is NOT shown on the TV (it only helps the
       people far away); the installer tells you, and you pass it on.
     - Already installed? Add it any time:  sudo ./tailscale-setup.sh

  3. OWN WIFI VERSION  (for a place with no wifi)
       sudo ./install.sh --own-wifi
     - The Pi makes its own open wifi called "raspberry pi tv" (no
       password). Join it and the upload page pops up by itself.
     - It also joins your phone hotspot, so people on the hotspot can open
       http://pitv.local too.
     - This was the first version (Pi Zero W, Nov 2026). The git tag
       "own-wifi-v1" is the code exactly as it was before the home wifi
       version was added.

Both versions
-------------
- Tap "Choose photos", pick as many as you like (100+ is fine), done.
  The page shows how many are sent, time left, time so far, speed, and
  the last 5 photos sent.
- Any photo type works: iPhone HEIC, JPEG, PNG, WebP, GIF, AVIF, TIFF,
  BMP. Photos that can't be opened (for example ones that are only in
  iCloud and not on the phone) are skipped quietly. Everything else
  still goes through.
- After a power cut the slideshow carries on 5 photos before where it
  stopped. New photos show up on the TV right away.
- Password (default "laura") is only needed to look at the photos on the
  phone and to change settings (wifis, seconds per photo). Uploading
  needs no password.
- Works on a Pi Zero W, Pi 3 (A+/B/B+), Zero 2 W, Pi 4.

The files in this folder
------------------------
README.txt                          this file
SETUP-FOR-HUMANS.txt                step by step setup, no tech knowledge needed
GUIDE-FOR-AI-AGENTS.txt             how an AI agent installs, runs, updates, debugs it
PROMPT-TO-BUILD-FROM-SCRATCH.txt    paste into an AI to rebuild the whole thing
HISTORY-PROBLEMS-AND-FIXES.txt      how we got here, what broke, how it was fixed

install.sh       first-time install, run on the Pi:  sudo ./install.sh
                 (home wifi version)   or   sudo ./install.sh --own-wifi
update.sh        update an installed Pi, run on the Pi:  sudo ./update.sh
send-to-pi.sh    run on a Mac: copies this folder to the Pi and installs
                 ./send-to-pi.sh raspberry@pitv.local  [--own-wifi]
tailscale-setup.sh  run on the Pi: adds Tailscale (version 2) to any install
add-wifi.sh      run on the Pi: save another wifi without the website
                 sudo ./add-wifi.sh "Wifi name" [priority]
pitv/            the program itself (Python + one web page)
systemd/         the three background services

Speed (own wifi version, measured on the real Pi Zero W over a phone hotspot)
-------------------------------------------------------------
100 full-size phone photos (358 MB) were sent in 40 seconds, because each
photo is shrunk to TV size on the phone first (44 MB total, JPEG quality
92%). The Pi then
gets each one ready for the TV in about 3 seconds, in the background.
