PI PHOTO TV - a family photo slideshow on a Raspberry Pi Zero W
==================================================================

What it does
------------
- The Pi makes its own open wifi called "raspberry pi tv" (no password).
- Join it from any iPhone or Android phone and a page pops up by itself.
- Tap "Choose photos", pick as many as you like (100+ is fine), done.
  The page shows how many are sent, time left, time so far, speed, and
  the last 5 photos sent.
- Any photo type works: iPhone HEIC, JPEG, PNG, WebP, GIF, AVIF, TIFF,
  BMP. Photos that can't be opened (for example ones that are only in
  iCloud and not on the phone) are skipped quietly. Everything else
  still goes through.
- Plug the Pi into a TV with HDMI and it plays all the photos as a
  slideshow, forever. After a power cut it carries on 5 photos before
  where it stopped. New photos show up on the TV right away.
- The Pi also joins your phone hotspot by itself, so people on the
  hotspot can open http://pitv.local too. You can add more wifis on the
  Settings page.
- Password (default "laura") is only needed to look at the photos on the
  phone and to change settings. Uploading needs no password.

The files in this folder
------------------------
README.txt                          this file
SETUP-FOR-HUMANS.txt                step by step setup, no tech knowledge needed
GUIDE-FOR-AI-AGENTS.txt             how an AI agent installs, runs, updates, debugs it
PROMPT-TO-BUILD-FROM-SCRATCH.txt    paste into an AI to rebuild the whole thing
HISTORY-PROBLEMS-AND-FIXES.txt      how we got here, what broke, how it was fixed

install.sh       first-time install, run on the Pi:  sudo ./install.sh
update.sh        update an installed Pi, run on the Pi:  sudo ./update.sh
send-to-pi.sh    run on a Mac/PC: copies this folder to the Pi and installs
pitv/            the program itself (Python + one web page)
systemd/         the three background services

Speed (measured on the real Pi Zero W over a phone hotspot)
-------------------------------------------------------------
100 full-size phone photos (358 MB) were sent in 40 seconds, because each
photo is shrunk to TV size on the phone first (44 MB total, JPEG quality
92%). The Pi then
gets each one ready for the TV in about 3 seconds, in the background.
