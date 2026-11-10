#!/usr/bin/env python3
"""Pi Photo TV web server: upload page, gallery, wifi settings, captive portal.

Standard library only (plus Pillow for image processing), so it runs on a
stock Raspberry Pi OS Lite with nothing from pip.
"""
import hashlib
import json
import os
import queue
import re
import secrets
import select
import shutil
import socket
import subprocess
import sys
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
from common import AP_IP, DISPLAY, INCOMING, KEYS_PATH, ORIGINALS, THUMBS  # noqa: E402

COMMON_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "common.py")
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
PORT = int(os.environ.get("PITV_PORT", "80"))
ID_RE = re.compile(r"^\d{13}-[0-9a-f]{6}$")
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
MIN_FREE_BYTES = 300 * 1024 * 1024

# Phones that tapped "Stay connected" on the popup. Their connectivity checks
# get a "you're online" answer so the popup goes away and the phone stays on.
accepted_clients = set()

keys_lock = threading.Lock()
uploads_active = 0          # uploads being received right now
last_upload_end = 0.0
work_queue = queue.Queue()


# ---------------------------------------------------------------- photos ---

def load_keys():
    return common.read_json(KEYS_PATH, {})


def new_photo_id():
    return "%013d-%s" % (int(time.time() * 1000), secrets.token_hex(3))


def original_path(photo_id):
    for name in os.listdir(ORIGINALS):
        if name.startswith(photo_id + "."):
            return os.path.join(ORIGINALS, name)
    return None


def forget_key(photo_id):
    with keys_lock:
        keys = load_keys()
        kept = {k: v for k, v in keys.items() if v != photo_id}
        if len(kept) != len(keys):
            common.write_json(KEYS_PATH, kept)


class PhotoPrep:
    """One long-running low-priority helper process that prepares photos.

    Starting Python and Pillow costs over a second on a Pi Zero, so we keep
    one helper alive instead of starting one per photo. It's still a separate
    process: some image libraries on the Zero crash outright on certain files
    (WebP hits an "illegal instruction"), and that must never take the website
    down. If the helper dies, that photo is dropped and a new helper starts."""

    def __init__(self):
        self.proc = None

    def start(self):
        self.proc = subprocess.Popen([sys.executable, COMMON_PY, "--serve"], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, text=True, bufsize=1,
                                     preexec_fn=lambda: os.nice(10))

    def run(self, photo_id, path):
        if self.proc is None or self.proc.poll() is not None:
            self.start()
        try:
            self.proc.stdin.write("%s\t%s\n" % (photo_id, path))
            self.proc.stdin.flush()
            ready, _, _ = select.select([self.proc.stdout], [], [], 300)
            reply = self.proc.stdout.readline().strip() if ready else "timeout"
        except (OSError, ValueError):
            reply = ""
        if reply != "ok":
            print("could not read %s (%s)" % (path, reply or "helper crashed"), flush=True)
            if self.proc.poll() is None and reply == "timeout":
                self.proc.kill()
        return reply == "ok"


def worker():
    """Turns uploads into TV-ready images in the background."""
    prep = PhotoPrep()
    while True:
        photo_id, path = work_queue.get()
        # The Zero has one small CPU core: while photos are still arriving,
        # receiving them comes first. The TV versions are made in the gaps.
        while uploads_active or time.time() - last_upload_end < 3:
            time.sleep(1)
        if not prep.run(photo_id, path):
            # Nothing could read it: drop it quietly so it never holds anything up.
            for leftover in (path, os.path.join(DISPLAY, "." + photo_id + ".jpg"),
                             os.path.join(THUMBS, photo_id + ".jpg")):
                if os.path.exists(leftover):
                    os.remove(leftover)
            forget_key(photo_id)
        work_queue.task_done()


def queue_unprocessed():
    done = set(common.display_photos())
    for name in sorted(os.listdir(ORIGINALS)):
        photo_id = name.split(".")[0]
        if ID_RE.match(photo_id) and photo_id not in done:
            work_queue.put((photo_id, os.path.join(ORIGINALS, name)))


def delete_photo(photo_id):
    for path in (os.path.join(DISPLAY, photo_id + ".jpg"), os.path.join(THUMBS, photo_id + ".jpg"),
                 original_path(photo_id)):
        if path and os.path.exists(path):
            os.remove(path)
    with keys_lock:
        keys = load_keys()
        keys = {k: v for k, v in keys.items() if v != photo_id}
        common.write_json(KEYS_PATH, keys)


# ------------------------------------------------------------------ wifi ---

def run(cmd, timeout=20):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "", str(e)


def split_terse(line):
    """Split one line of `nmcli -t` output (':' separated, '\\' escapes)."""
    out, cur, esc = [], "", False
    for ch in line:
        if esc:
            cur += ch
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return out


def wlan_ip():
    code, out, _ = run(["ip", "-4", "-o", "addr", "show", "wlan0"])
    m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", out) if code == 0 else None
    return m.group(1) if m else None


def wifi_status():
    cfg = common.load_config()
    status = {"ap_ssid": cfg["ap_ssid"], "ap_ip": AP_IP, "connected": None, "ip": None,
              "saved": [], "nearby": [], "nmcli": shutil.which("nmcli") is not None}
    if not status["nmcli"]:
        return status

    code, out, _ = run(["nmcli", "-t", "-f", "DEVICE,STATE,CONNECTION", "device"])
    for line in out.splitlines():
        dev, state, con = (split_terse(line) + ["", "", ""])[:3]
        if dev == "wlan0" and state.startswith("connected"):
            status["connected"] = con
            status["ip"] = wlan_ip()

    code, out, _ = run(["nmcli", "-t", "-f", "NAME,TYPE,AUTOCONNECT-PRIORITY", "connection", "show"])
    for line in out.splitlines():
        name, ctype, prio = (split_terse(line) + ["", "", ""])[:3]
        if ctype != "802-11-wireless":
            continue
        _, ssid, _ = run(["nmcli", "-g", "802-11-wireless.ssid", "connection", "show", name])
        status["saved"].append({"name": name, "ssid": ssid or name, "priority": prio})

    code, out, _ = run(["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list"])
    best = {}
    for line in out.splitlines():
        ssid, signal, security = (split_terse(line) + ["", "", ""])[:3]
        if not ssid or ssid == cfg["ap_ssid"]:
            continue
        sig = int(signal) if signal.isdigit() else 0
        if ssid not in best or sig > best[ssid]["signal"]:
            best[ssid] = {"ssid": ssid, "signal": sig, "secure": security not in ("", "--")}
    status["nearby"] = sorted(best.values(), key=lambda n: -n["signal"])
    return status


def wifi_add(ssid, password):
    if not ssid or len(ssid.encode()) > 32:
        return "Wifi name must be 1 to 32 characters."
    if password and not 8 <= len(password) <= 63:
        return "Wifi passwords are 8 to 63 characters."
    # Replace any older saved copy of the same network.
    run(["nmcli", "connection", "delete", "id", ssid])
    prio = "10" if ssid.lower().startswith("dovi") else "5"
    cmd = ["nmcli", "connection", "add", "type", "wifi", "ifname", "wlan0", "con-name", ssid,
           "ssid", ssid, "connection.autoconnect", "yes", "connection.autoconnect-priority", prio]
    if password:
        cmd += ["wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", password]
    code, _, err = run(cmd)
    if code != 0:
        return err or "Could not save that wifi."

    def connect_if_idle():
        # Give the browser time to get its answer first: switching networks
        # can make the Pi's own wifi blink for a few seconds.
        time.sleep(3)
        if not wifi_status()["connected"]:
            run(["nmcli", "connection", "up", "id", ssid], timeout=45)
    threading.Thread(target=connect_if_idle, daemon=True).start()
    return None


def wifi_remove(name):
    code, _, err = run(["nmcli", "connection", "delete", "id", name])
    return None if code == 0 else (err or "Could not remove that wifi.")


# ----------------------------------------------------------------- http ----

def auth_token():
    secret_path = os.path.join(common.DATA, "secret")
    if not os.path.exists(secret_path):
        with open(secret_path, "w") as f:
            f.write(secrets.token_hex(16))
    with open(secret_path) as f:
        secret = f.read().strip()
    return hashlib.sha256((secret + common.load_config()["password"]).encode()).hexdigest()[:32]


CAPTIVE_SUCCESS = {
    "/generate_204": (204, "text/plain", b""),
    "/gen_204": (204, "text/plain", b""),
    "/connecttest.txt": (200, "text/plain", b"Microsoft Connect Test"),
    "/ncsi.txt": (200, "text/plain", b"Microsoft NCSI"),
    "/success.txt": (200, "text/plain", b"success\n"),
}
APPLE_SUCCESS = b"<HTML><HEAD><TITLE>Success</TITLE></HEAD><BODY>Success</BODY></HTML>"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "PiPhotoTV"

    def log_message(self, fmt, *args):
        if os.environ.get("PITV_DEBUG"):
            super().log_message(fmt, *args)

    # -- helpers --
    def send(self, code, body=b"", ctype="text/plain; charset=utf-8", headers=None):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_json(self, value, code=200, headers=None):
        self.send(code, json.dumps(value), "application/json", headers)

    def send_file(self, path, ctype, cache=True):
        try:
            size = os.path.getsize(path)
            f = open(path, "rb")
        except OSError:
            return self.send(404, "not found")
        with f:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "private, max-age=31536000" if cache else "no-store")
            self.end_headers()
            if self.command != "HEAD":
                shutil.copyfileobj(f, self.wfile, 256 * 1024)

    def redirect(self, url):
        self.send(302, "", headers={"Location": url})

    def read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > 1_000_000:
            raise ValueError("too big")
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return {}

    def is_authed(self):
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        return "pitv" in cookie and secrets.compare_digest(cookie["pitv"].value, auth_token())

    def is_our_host(self):
        host = (self.headers.get("Host") or "").split(":")[0].lower()
        return (not host or re.match(r"^\d+\.\d+\.\d+\.\d+$", host) or host.endswith(".local")
                or "." not in host)

    # -- captive portal --
    def captive(self, path):
        """Phones check a known website to see if the wifi has internet. We
        answer every such check, which is what makes the popup appear."""
        client = client_ip(self)
        if client in accepted_clients:
            if path in CAPTIVE_SUCCESS:
                code, ctype, body = CAPTIVE_SUCCESS[path]
                return self.send(code, body, ctype)
            if "hotspot-detect" in path or path.startswith("/library/test/success"):
                return self.send(200, APPLE_SUCCESS, "text/html")
        return self.redirect("http://%s/?popup=1" % AP_IP)

    # -- routing --
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        url = urlparse(self.path)
        path = url.path
        if not self.is_our_host():
            return self.captive(path)
        if path in CAPTIVE_SUCCESS or "hotspot-detect" in path:
            return self.captive(path)

        if path in ("/", "/index.html"):
            return self.send_file(os.path.join(WEB_DIR, "index.html"), "text/html; charset=utf-8", cache=False)
        if path == "/api/status":
            return self.api_status()

        m = re.match(r"^/(thumbs|display|original)/([\w-]+?)(\.jpg)?$", path)
        if m:
            if not self.is_authed():
                return self.send(403, "password needed")
            kind, photo_id = m.group(1), m.group(2)
            if not ID_RE.match(photo_id):
                return self.send(404, "not found")
            if kind == "original":
                p = original_path(photo_id)
                if not p:
                    return self.send(404, "not found")
                return self.send_file(p, "application/octet-stream")
            return self.send_file(os.path.join(THUMBS if kind == "thumbs" else DISPLAY, photo_id + ".jpg"),
                                  "image/jpeg")

        if path == "/api/photos":
            if not self.is_authed():
                return self.send_json({"error": "password"}, 403)
            q = parse_qs(url.query)
            offset = int(q.get("offset", ["0"])[0])
            limit = min(int(q.get("limit", ["60"])[0]), 500)
            ids = common.display_photos()[::-1]
            return self.send_json({"total": len(ids), "photos": ids[offset:offset + limit]})

        if path == "/api/wifi":
            if not self.is_authed():
                return self.send_json({"error": "password"}, 403)
            return self.send_json(wifi_status())

        if path == "/favicon.ico":
            return self.send(204)
        # Anything else (a phone typing some other address) gets the app.
        return self.redirect("/")

    def do_PUT(self):
        if urlparse(self.path).path != "/api/upload":
            self.close_connection = True
            return self.send(404, "not found")
        self.api_upload()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/check":
            body = self.read_json()
            keys = load_keys()
            return self.send_json({"have": [k for k in body.get("keys", []) if k in keys]})

        if path == "/api/login":
            body = self.read_json()
            if str(body.get("password", "")).strip().lower() == common.load_config()["password"].lower():
                cookie = "pitv=%s; Path=/; Max-Age=31536000; HttpOnly; SameSite=Lax" % auth_token()
                return self.send_json({"ok": True}, headers={"Set-Cookie": cookie})
            return self.send_json({"ok": False, "error": "Wrong password"}, 403)

        if path == "/api/accept":
            self.read_json()
            accepted_clients.add(client_ip(self))
            return self.send_json({"ok": True})

        body = self.read_json()
        if not self.is_authed():
            return self.send_json({"error": "password"}, 403)

        if path == "/api/delete":
            photo_id = str(body.get("id", ""))
            if not ID_RE.match(photo_id):
                return self.send_json({"error": "bad id"}, 400)
            delete_photo(photo_id)
            return self.send_json({"ok": True})

        if path == "/api/wifi/add":
            err = wifi_add(str(body.get("ssid", "")), str(body.get("password", "")))
            return self.send_json({"ok": not err, "error": err}, 200 if not err else 400)

        if path == "/api/wifi/remove":
            err = wifi_remove(str(body.get("name", "")))
            return self.send_json({"ok": not err, "error": err}, 200 if not err else 400)

        if path == "/api/settings":
            secs = int(body.get("slide_seconds", 8))
            common.save_config({"slide_seconds": max(3, min(secs, 300))})
            return self.send_json({"ok": True})

        self.send_json({"error": "not found"}, 404)

    # -- endpoints --
    def api_status(self):
        cfg = common.load_config()
        free = shutil.disk_usage(common.DATA).free
        self.send_json({
            "photos": len(common.display_photos()),
            "processing": work_queue.unfinished_tasks,
            "free_gb": round(free / 1e9, 1),
            "authed": self.is_authed(),
            "slide_seconds": cfg["slide_seconds"],
            "ap_ssid": cfg["ap_ssid"],
            "accepted": client_ip(self) in accepted_clients,
        })

    def api_upload(self):
        length = self.headers.get("Content-Length")
        if length is None:
            self.close_connection = True
            return self.send_json({"error": "length required"}, 411)
        length = int(length)
        if length == 0:
            return self.send_json({"error": "That photo was empty."}, 400)
        if shutil.disk_usage(common.DATA).free - length < MIN_FREE_BYTES:
            self.close_connection = True
            return self.send_json({"error": "The Pi's memory card is full."}, 507)

        name = unquote(self.headers.get("X-Name", "photo.jpg"))[:200]
        key = unquote(self.headers.get("X-Key", ""))[:300]
        ext = os.path.splitext(name)[1].lower()
        if ext not in IMAGE_EXTS:
            ext = ".jpg"

        global uploads_active, last_upload_end
        uploads_active += 1
        try:
            return self.receive_upload(length, name, key, ext)
        finally:
            uploads_active -= 1
            last_upload_end = time.time()

    def receive_upload(self, length, name, key, ext):
        photo_id = new_photo_id()
        part = os.path.join(INCOMING, photo_id + ".part")
        remaining = length
        try:
            with open(part, "wb") as f:
                while remaining > 0:
                    chunk = self.rfile.read(min(remaining, 256 * 1024))
                    if not chunk:
                        break
                    f.write(chunk)
                    remaining -= len(chunk)
        except OSError:
            remaining = -1
        if remaining != 0:
            self.close_connection = True
            if os.path.exists(part):
                os.remove(part)
            return self.send_json({"error": "upload interrupted"}, 400)

        with keys_lock:
            keys = load_keys()
            if key and key in keys:  # same photo sent twice at once
                os.remove(part)
                return self.send_json({"ok": True, "id": keys[key], "duplicate": True})
            dest = os.path.join(ORIGINALS, photo_id + ext)
            os.replace(part, dest)
            if key:
                keys[key] = photo_id
                common.write_json(KEYS_PATH, keys)
        work_queue.put((photo_id, dest))
        self.send_json({"ok": True, "id": photo_id})


class DualStackServer(ThreadingHTTPServer):
    """Listens on IPv6 and IPv4 at once: phones on the hotspot often reach
    pitv.local over IPv6 first."""
    address_family = socket.AF_INET6
    request_queue_size = 64

    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


def client_ip(handler):
    ip = handler.client_address[0]
    return ip[7:] if ip.startswith("::ffff:") else ip


def main():
    common.ensure_dirs()
    for name in os.listdir(INCOMING):  # leftovers from a power cut
        os.remove(os.path.join(INCOMING, name))
    queue_unprocessed()
    threading.Thread(target=worker, daemon=True).start()
    try:
        server = DualStackServer(("::", PORT), Handler)
    except OSError:  # no IPv6 on this machine
        server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.daemon_threads = True
    print("Pi Photo TV web server on port %d, photos in %s" % (PORT, common.DATA), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
