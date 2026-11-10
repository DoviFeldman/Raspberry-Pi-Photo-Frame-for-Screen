"""Shared paths, settings and image processing for Pi Photo TV."""
import json
import os
import threading

DATA = os.environ.get("PITV_DATA", "/var/lib/pitv")
ORIGINALS = os.path.join(DATA, "originals")
DISPLAY = os.path.join(DATA, "display")      # TV-ready 1920x1080 JPEGs
THUMBS = os.path.join(DATA, "thumbs")        # small previews for the gallery
INCOMING = os.path.join(DATA, "incoming")    # partial uploads
CONFIG_PATH = os.path.join(DATA, "config.json")
STATE_PATH = os.path.join(DATA, "slideshow_state.json")
KEYS_PATH = os.path.join(DATA, "keys.json")

SCREEN_W, SCREEN_H = 1920, 1080
AP_IP = "192.168.4.1"

DEFAULTS = {
    "password": "laura",
    "slide_seconds": 8,
    "ap_ssid": "raspberry pi tv",
    "country": "US",
}

_lock = threading.Lock()


def ensure_dirs():
    for d in (DATA, ORIGINALS, DISPLAY, THUMBS, INCOMING):
        os.makedirs(d, exist_ok=True)


def read_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, value):
    """Atomic write so a power cut never leaves a half-written file."""
    tmp = path + ".tmp"
    with _lock:
        with open(tmp, "w") as f:
            json.dump(value, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)


def load_config():
    cfg = dict(DEFAULTS)
    cfg.update(read_json(CONFIG_PATH, {}))
    return cfg


def save_config(changes):
    cfg = read_json(CONFIG_PATH, {})
    cfg.update(changes)
    write_json(CONFIG_PATH, cfg)


def display_photos():
    """Photo ids in upload order (ids start with a millisecond timestamp)."""
    try:
        names = os.listdir(DISPLAY)
    except OSError:
        return []
    return sorted(n[:-4] for n in names if n.endswith(".jpg") and not n.startswith("."))


def heif_to_jpeg(src):
    """iPhone HEIC and AVIF photos: Pillow on the Pi can't read them, but
    libheif's heif-dec can (about 8 s for a 12MP photo on a Pi Zero)."""
    import subprocess
    out = os.path.join(INCOMING, os.path.basename(src) + ".heif.jpg")
    subprocess.run(["heif-dec", "--quality", "92", src, out], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=240)
    return out


def process_photo(photo_id, src):
    """Make the TV version (photo on a soft blurred backdrop) and a thumbnail."""
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    try:
        import pillow_heif  # optional: lets raw iPhone HEIC files work too
        pillow_heif.register_heif_opener()
    except ImportError:
        pass

    try:
        im = Image.open(src)
    except Exception:
        im = Image.open(heif_to_jpeg(src))
    # draft() makes the JPEG decoder skip detail we don't need: a 12MP photo
    # decodes several times faster, which matters a lot on a Pi Zero.
    im.draft("RGB", (SCREEN_W, SCREEN_W))
    im = ImageOps.exif_transpose(im).convert("RGB")

    fit = im.copy()
    fit.thumbnail((SCREEN_W, SCREEN_H), Image.LANCZOS if max(im.size) < 4000 else Image.BILINEAR)

    bg = ImageOps.fit(im, (96, 54), Image.BILINEAR)
    bg = bg.filter(ImageFilter.GaussianBlur(3))
    bg = ImageEnhance.Brightness(bg).enhance(0.45)
    bg = bg.resize((SCREEN_W, SCREEN_H), Image.BILINEAR)
    bg.paste(fit, ((SCREEN_W - fit.width) // 2, (SCREEN_H - fit.height) // 2))

    tmp = os.path.join(DISPLAY, "." + photo_id + ".jpg")
    bg.save(tmp, "JPEG", quality=88)
    thumb = fit.copy()
    thumb.thumbnail((360, 360))
    thumb.save(os.path.join(THUMBS, photo_id + ".jpg"), "JPEG", quality=78)
    # Rename last: the slideshow only ever sees finished files.
    os.replace(tmp, os.path.join(DISPLAY, photo_id + ".jpg"))
    converted = os.path.join(INCOMING, os.path.basename(src) + ".heif.jpg")
    if os.path.exists(converted):
        os.remove(converted)


def serve():
    """Helper mode for the web server: one photo per line ("id<TAB>path") in,
    "ok" or "error ..." out, until stdin closes."""
    import sys
    for line in sys.stdin:
        photo_id, path = line.rstrip("\n").split("\t", 1)
        try:
            process_photo(photo_id, path)
            print("ok", flush=True)
        except Exception as e:
            print("error %s" % str(e).replace("\n", " ")[:200], flush=True)


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["--serve"]:
        serve()
    else:
        process_photo(sys.argv[1], sys.argv[2])
