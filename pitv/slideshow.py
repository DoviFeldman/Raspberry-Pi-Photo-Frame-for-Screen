#!/usr/bin/env python3
"""Shows the photos full-screen on the HDMI TV by drawing straight to the
framebuffer (no desktop needed). Remembers where it was, and after a restart
picks up 5 photos before that spot. New uploads are shown right away."""
import os
import subprocess
import sys
import time

from PIL import Image, ImageChops, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

FB = os.environ.get("PITV_FB", "/dev/fb0")
FB_SYS = "/sys/class/graphics/" + os.path.basename(FB)
RESUME_BACK = 5
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def read_sys(name, default):
    try:
        with open(os.path.join(FB_SYS, name)) as f:
            return f.read().strip()
    except OSError:
        return default


def fb_geometry():
    w, h = (int(v) for v in read_sys("virtual_size", "1920,1080").split(","))
    bpp = int(read_sys("bits_per_pixel", "32"))
    stride = int(read_sys("stride", str(w * bpp // 8)))
    return w, h, bpp, stride


def to_fb_bytes(im, bpp):
    if bpp == 32:
        return im.tobytes("raw", "BGRX")
    if bpp == 24:
        return im.tobytes("raw", "BGR")
    # 16 bit RGB565, little endian: build the two bytes with Pillow channel maths.
    r, g, b = im.split()
    lo = ImageChops.add(g.point(lambda v: (v >> 2 & 7) << 5), b.point(lambda v: v >> 3))
    hi = ImageChops.add(r.point(lambda v: v >> 3 << 3), g.point(lambda v: v >> 5))
    return Image.merge("LA", (lo, hi)).tobytes()


def draw(im):
    w, h, bpp, stride = fb_geometry()
    if im.size != (w, h):
        im = im.resize((w, h), Image.BILINEAR)
    data = to_fb_bytes(im.convert("RGB"), bpp)
    row = w * bpp // 8
    try:
        with open(FB, "r+b" if os.path.exists(FB) else "wb") as f:
            if stride == row:
                f.write(data)
            else:
                for y in range(h):
                    f.seek(y * stride)
                    f.write(data[y * row:(y + 1) * row])
    except OSError as e:
        print("cannot draw to", FB, e, flush=True)


def font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        try:
            return ImageFont.load_default(size)
        except TypeError:  # Pillow older than 10.1
            return ImageFont.load_default()


def hotspot_ip():
    try:
        out = subprocess.run(["ip", "-4", "-o", "addr", "show", "wlan0"], capture_output=True,
                             text=True, timeout=5).stdout
        return out.split("inet ")[1].split("/")[0] if "inet " in out else None
    except (OSError, subprocess.TimeoutExpired, IndexError):
        return None


def welcome_screen():
    cfg = common.load_config()
    im = Image.new("RGB", (common.SCREEN_W, common.SCREEN_H), (29, 26, 47))
    d = ImageDraw.Draw(im)
    d.text((960, 250), "Family Photo TV", font=font(FONT_BOLD, 110), fill=(255, 179, 71), anchor="mm")
    d.text((960, 380), "No photos yet. Here's how to add some:", font=font(FONT, 48),
           fill=(185, 178, 214), anchor="mm")
    lines = ["1.  On your phone, join the wifi  “%s”" % cfg["ap_ssid"],
             "2.  A page pops up (or open  %s )" % common.AP_IP,
             "3.  Tap  Choose photos"]
    ip = hotspot_ip()
    if ip:
        lines.append("On the hotspot instead? Open  %s  or  pitv.local" % ip)
    for i, line in enumerate(lines):
        d.text((300, 520 + i * 110), line, font=font(FONT, 56), fill=(251, 247, 255))
    return im


class State:
    def __init__(self):
        self.current = common.read_json(common.STATE_PATH, {}).get("current")

    def save(self, photo_id):
        self.current = photo_id
        try:
            common.write_json(common.STATE_PATH, {"current": photo_id, "time": time.time()})
        except OSError:
            pass


def start_index(photos, current):
    """Where to begin after a restart: 5 before the last photo shown."""
    if not current:
        return 0
    # Photo ids sort by upload time, so even a deleted photo has a place.
    pos = sum(1 for p in photos if p < current)
    return max(0, pos - RESUME_BACK)


def main():
    common.ensure_dirs()
    # Hide the blinking text cursor on the TV.
    try:
        with open("/sys/class/graphics/fbcon/cursor_blink", "w") as f:
            f.write("0")
    except OSError:
        pass

    state = State()
    photos = common.display_photos()
    known = set(photos)
    index = start_index(photos, state.current) if photos else 0
    fresh = []  # just-uploaded photos jump the line
    welcome_drawn = 0

    while True:
        photos = common.display_photos()
        if not photos:
            # Redraw every minute in case the TV was plugged in later.
            if time.time() - welcome_drawn > 60:
                draw(welcome_screen())
                welcome_drawn = time.time()
            time.sleep(3)
            continue
        welcome_drawn = 0

        new = [p for p in photos if p not in known]
        known = set(photos)
        if new and len(new) < len(photos):
            fresh.extend(new)

        detour = bool(fresh)
        if detour:
            photo_id = fresh.pop(0)
            if photo_id not in known:
                continue
        else:
            index %= len(photos)
            photo_id = photos[index]
            index += 1

        started = time.time()
        try:
            with Image.open(os.path.join(common.DISPLAY, photo_id + ".jpg")) as im:
                draw(im)
        except OSError:
            continue  # deleted while we were looking at it
        if not detour:
            # Remember our place in the main loop (not the new-photo detour).
            state.save(photo_id)
        delay = common.load_config()["slide_seconds"]
        time.sleep(max(1, delay - (time.time() - started)))


if __name__ == "__main__":
    main()
