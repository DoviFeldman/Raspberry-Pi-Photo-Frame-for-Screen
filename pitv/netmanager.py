#!/usr/bin/env python3
"""Runs the Pi's own open wifi ("raspberry pi tv") on a second virtual
interface (uap0) while wlan0 stays free to join your hotspot.

The Pi Zero W has one radio, so both have to share a channel: whenever wlan0
joins a network, the access point is moved onto that network's channel.
NetworkManager handles wlan0 (saved wifis, auto-connect); this handles uap0.
"""
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

AP = "uap0"
STA = "wlan0"
RUN = "/run/pitv"
DEFAULT_CHANNEL = 6


def sh(*cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def log(*args):
    print(*args, flush=True)


def sta_channel():
    """Channel of the wifi wlan0 is connected to, or None."""
    _, out = sh("iw", "dev", STA, "link")
    m = re.search(r"freq: (\d+)", out)
    if not m:
        return None
    freq = int(float(m.group(1)))
    if freq == 2484:
        return 14
    if 2412 <= freq <= 2472:
        return (freq - 2407) // 5
    return None  # 5 GHz: the Zero W can't do it, shouldn't happen


def ensure_ap_interface():
    if not os.path.exists("/sys/class/net/" + AP):
        code, out = sh("iw", "dev", STA, "interface", "add", AP, "type", "__ap")
        if code:
            log("could not create", AP, out.strip())
            return False
    sh("ip", "link", "set", AP, "up")
    _, out = sh("ip", "-4", "addr", "show", AP)
    if common.AP_IP not in out:
        sh("ip", "addr", "add", common.AP_IP + "/24", "dev", AP)
    return True


def write_hostapd_conf(channel):
    cfg = common.load_config()
    path = os.path.join(RUN, "hostapd.conf")
    with open(path, "w") as f:
        f.write("\n".join([
            "interface=" + AP,
            "driver=nl80211",
            "ssid=" + cfg["ap_ssid"],
            "utf8_ssid=1",
            "country_code=" + cfg["country"],
            "hw_mode=g",
            "channel=%d" % channel,
            "ieee80211n=1",
            "wmm_enabled=1",
            "auth_algs=1",
            "ignore_broadcast_ssid=0",   # visible network
            "max_num_sta=12",
            "",                          # no wpa lines = open, no password
        ]))
    return path


def write_dnsmasq_conf():
    path = os.path.join(RUN, "dnsmasq.conf")
    ip = common.AP_IP
    with open(path, "w") as f:
        f.write("\n".join([
            "interface=" + AP,
            "bind-interfaces",
            "listen-address=" + ip,
            "no-resolv",
            "no-hosts",
            "dhcp-range=192.168.4.10,192.168.4.250,255.255.255.0,12h",
            "dhcp-option=3," + ip,
            "dhcp-option=6," + ip,
            # RFC 8910: tells new phones straight away that there's a page to open.
            "dhcp-option=114,http://%s/" % ip,
            "dhcp-leasefile=" + os.path.join(RUN, "dnsmasq.leases"),
            # Every website name points at the Pi -> phones show the popup.
            "address=/#/" + ip,
            "",
        ]))
    return path


class Child:
    def __init__(self, name):
        self.name = name
        self.proc = None

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, cmd):
        self.stop()
        log("starting", self.name, " ".join(cmd))
        self.proc = subprocess.Popen(cmd)

    def stop(self):
        if self.alive():
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None


def main():
    os.makedirs(RUN, exist_ok=True)
    common.ensure_dirs()
    sh("rfkill", "unblock", "wlan")
    sh("iw", "dev", STA, "set", "power_save", "off")

    # Give NetworkManager a moment to join the hotspot first, so the access
    # point starts on the right channel instead of restarting right away.
    for _ in range(20):
        if sta_channel():
            break
        time.sleep(1)

    hostapd, dnsmasq = Child("hostapd"), Child("dnsmasq")
    ap_channel = None
    failures = 0
    try:
        while True:
            if ensure_ap_interface():
                ch = sta_channel()
                want = ch or ap_channel or DEFAULT_CHANNEL
                if not hostapd.alive() or want != ap_channel:
                    if ap_channel and want != ap_channel:
                        log("hotspot is on channel %d, moving the TV wifi there" % want)
                    hostapd.start(["hostapd", write_hostapd_conf(want)])
                    ap_channel = want
                    time.sleep(3)
                    if not hostapd.alive():
                        failures += 1
                        if failures >= 3:
                            # Recreating the virtual interface clears most driver hiccups.
                            log("hostapd keeps failing, recreating", AP)
                            sh("iw", "dev", AP, "del")
                            failures = 0
                        continue
                    failures = 0
                    sh("ip", "addr", "replace", common.AP_IP + "/24", "dev", AP)
                if not dnsmasq.alive():
                    dnsmasq.start(["dnsmasq", "--keep-in-foreground", "--conf-file=" + write_dnsmasq_conf()])
            time.sleep(5)
    finally:
        hostapd.stop()
        dnsmasq.stop()


if __name__ == "__main__":
    main()
