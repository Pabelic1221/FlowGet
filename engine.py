"""FlowGet engine: downloads, yt-dlp integration, settings, queue persistence, updates."""
import os, sys, re, json, time, threading, subprocess, zipfile, tempfile, shutil, hashlib, logging
import urllib.request, urllib.parse

APP_NAME = "FlowGet"
VERSION = "1.3.0"
GITHUB_REPO = "Pabelic1221/FlowGet"   # GitHub "user/repo" used for app updates

DATA = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), APP_NAME)
BIN = os.path.join(DATA, "bin")
os.makedirs(BIN, exist_ok=True)
YTDLP = os.path.join(BIN, "yt-dlp.exe")
FFMPEG = os.path.join(BIN, "ffmpeg.exe")
DENO = os.path.join(BIN, "deno.exe")
LOG_FILE = os.path.join(DATA, "flowget.log")
SETTINGS_FILE = os.path.join(DATA, "settings.json")
QUEUE_FILE = os.path.join(DATA, "queue.json")
YTDLP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
FFMPEG_URL = "https://github.com/yt-dlp/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-win64-gpl.zip"
DENO_URL = "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip"
YTDLP_API = "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest"
DENO_API = "https://api.github.com/repos/denoland/deno/releases/latest"
FFMPEG_API = "https://api.github.com/repos/yt-dlp/FFmpeg-Builds/releases/latest"
DEFAULT_DIR = os.path.join(os.path.expanduser("~"), "Downloads")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FlowGet"
NOWIN = 0x08000000 if os.name == "nt" else 0
FILE_EXTS = {"zip", "rar", "7z", "exe", "msi", "iso", "pdf", "mp3", "mp4", "mkv", "avi", "mov", "wav",
             "flac", "m4a", "webm", "jpg", "jpeg", "png", "gif", "doc", "docx", "xls", "xlsx", "ppt",
             "pptx", "apk", "dmg", "gz", "tar", "torrent", "txt", "csv", "bin"}

logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("flowget")
tools_ready = threading.Event()

# ---------------------------------------------------------------- settings
DEFAULTS = {"max_concurrent": 3, "connections": 8, "speed_kbps": 0, "folder": DEFAULT_DIR,
            "cookies_browser": "", "clipboard": True, "notify": True,
            "auto_engine_update": True, "tools_checked": 0, "ffmpeg_built": "", "theme": "dark"}
settings = dict(DEFAULTS)


def _write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def load_settings():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            settings.update(json.load(f))
    except Exception:
        pass


def save_settings():
    try: _write_json(SETTINGS_FILE, settings)
    except Exception: log.exception("save settings")


load_settings()


def fmt_size(n):
    n = float(n or 0)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {u}" if u != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} PB"


def safe_name(n):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", n).strip(" .")[:180]


def unique_path(p):
    base, ext = os.path.splitext(p)
    i = 1
    while os.path.exists(p):
        p = f"{base} ({i}){ext}"; i += 1
    return p


def fetch(url, dest, cb=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length", 0)); got = 0
        while True:
            b = r.read(131072)
            if not b:
                break
            f.write(b); got += len(b)
            if cb and total:
                cb(got / total)


# ---------------------------------------------------------------- tasks
PERSIST = ("url", "kind", "folder", "name", "size", "done", "status", "err", "quality", "fmt",
           "path", "ranged", "segs")


class Task:
    def __init__(s, url, kind, folder, quality="best", fmt=""):
        s.url, s.kind, s.folder, s.quality, s.fmt = url, kind, folder, quality, fmt  # kind: file|video|audio
        s.name = url[:70]; s.size = 0; s.done = 0; s.speed = 0; s.last = 0
        s.status = "Queued"; s.err = ""; s.path = None; s.ranged = False; s.segs = None
        s.stop = threading.Event(); s.lock = threading.Lock(); s.proc = None
        s.notified = False; s.active = 1

    def add(s, n):
        with s.lock:
            s.done += n

    def to_dict(s):
        return json.loads(json.dumps({k: getattr(s, k) for k in PERSIST}))

    @classmethod
    def from_dict(cls, d):
        t = cls(d["url"], d["kind"], d["folder"], d.get("quality", "best"), d.get("fmt", ""))
        for k in PERSIST:
            if k in d: setattr(t, k, d[k])
        if t.status in ("Downloading", "Queued"): t.status = "Queued"      # auto-resume after restart
        t.notified = t.status == "Completed"
        return t

    def start(s):
        s.stop.clear(); s.status = "Downloading"; s.err = ""
        threading.Thread(target=s._run, daemon=True).start()

    def _run(s):
        try:
            (run_http if s.kind == "file" else run_media)(s)
        except Exception as e:
            s.status, s.err = "Error", str(e)[:200]
            log.exception("task failed: %s", s.url)

    def pause(s):
        s.stop.set()
        if s.proc:
            try: s.proc.terminate()
            except Exception: pass
        if s.status in ("Downloading", "Queued"):
            s.status = "Paused"


def save_queue(tasks):
    try: _write_json(QUEUE_FILE, [t.to_dict() for t in tasks])
    except Exception: log.exception("save queue")


def load_queue():
    try:
        with open(QUEUE_FILE, encoding="utf-8") as f:
            return [Task.from_dict(d) for d in json.load(f)]
    except Exception:
        return []


# ---------------------------------------------------------------- direct (HTTP) downloads
def http_probe(t):
    req = urllib.request.Request(t.url, headers={"User-Agent": UA, "Range": "bytes=0-0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        cr = r.headers.get("Content-Range"); cd = r.headers.get("Content-Disposition", "")
        final = r.geturl()
        if r.status == 206 and cr:
            t.size = int(cr.split("/")[-1]); t.ranged = True
        else:
            t.size = int(r.headers.get("Content-Length", 0)); t.ranged = False
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)', cd)
    name = urllib.parse.unquote(m.group(1)) if m else urllib.parse.unquote(
        os.path.basename(urllib.parse.urlparse(final).path))
    t.name = safe_name(name) or "download"


def seg_worker(t, g):
    tries = 0
    while not t.stop.is_set() and not g["d"] and tries < 8:
        try:
            h = {"User-Agent": UA}
            if t.ranged:
                h["Range"] = f"bytes={g['p']}-{g['e']}"
            t0 = time.time(); sent = 0
            with urllib.request.urlopen(urllib.request.Request(t.url, headers=h), timeout=30) as r, \
                    open(t.path, "r+b") as f:
                f.seek(g["p"])
                while not t.stop.is_set():
                    b = r.read(65536)
                    if not b:
                        if g["e"] < 0 or g["p"] > g["e"]:
                            g["d"] = True
                            return
                        raise IOError("truncated")
                    f.write(b); g["p"] += len(b); t.add(len(b)); tries = 0
                    lim = settings["speed_kbps"] * 1024
                    if lim:                                       # global limit shared across segments
                        sent += len(b)
                        wait = sent / (lim / max(1, t.active)) - (time.time() - t0)
                        if wait > 0: time.sleep(min(wait, 1))
        except Exception as e:
            tries += 1; log.warning("segment retry (%s): %s", tries, e)
            t.stop.wait(min(2 * tries, 10))


def run_http(t):
    conns = max(1, int(settings["connections"]))
    if t.segs and (not t.path or not os.path.exists(t.path)):
        t.segs = None                                              # file was deleted -> restart
    if not t.segs:
        http_probe(t)
        os.makedirs(t.folder, exist_ok=True)
        if t.size and shutil.disk_usage(t.folder).free < t.size + 50 * 1024 * 1024:
            raise RuntimeError("Not enough free disk space")
        t.path = unique_path(os.path.join(t.folder, t.name)); t.name = os.path.basename(t.path)
        with open(t.path, "wb") as f:
            if t.size: f.truncate(t.size)
        if t.ranged and t.size > 2 * 1024 * 1024 and conns > 1:
            step = t.size // conns
            t.segs = [{"s": i * step, "p": i * step, "e": (i + 1) * step - 1 if i < conns - 1 else t.size - 1,
                       "d": False} for i in range(conns)]
        else:
            t.segs = [{"s": 0, "p": 0, "e": t.size - 1 if t.ranged else -1, "d": False}]
    t.done = sum(g["p"] - g["s"] for g in t.segs)
    todo = [g for g in t.segs if not g["d"]]
    t.active = len(todo) or 1
    ths = [threading.Thread(target=seg_worker, args=(t, g), daemon=True) for g in todo]
    for th in ths: th.start()
    for th in ths: th.join()
    if t.stop.is_set():
        t.status = "Paused"
    elif all(g["d"] for g in t.segs):
        t.status = "Completed"; t.done = t.size or t.done
    else:
        t.status, t.err = "Error", "Connection failed"


# ---------------------------------------------------------------- media (yt-dlp)
def num(x):
    try: return float(x)
    except Exception: return 0


def cookies_args():
    b = settings.get("cookies_browser", "")
    return ["--cookies-from-browser", b] if b else []


def js_args():
    """YouTube needs a JavaScript runtime; point yt-dlp at our bundled Deno."""
    return ["--js-runtimes", f"deno:{DENO}"] if os.path.exists(DENO) else []


def media_cmd(t):
    cmd = [YTDLP, "--newline", "--no-playlist", "--ffmpeg-location", BIN, "-P", t.folder,
           "-o", "%(title).150s.%(ext)s", "--retries", "10", "--fragment-retries", "10",
           "--concurrent-fragments", "4",
           "--progress-template",
           "download:FG|%(progress.downloaded_bytes)s|%(progress.total_bytes)s|"
           "%(progress.total_bytes_estimate)s|%(progress.speed)s|%(info.title)s"]
    if settings["speed_kbps"]:
        cmd += ["-r", f"{settings['speed_kbps']}K"]
    cmd += cookies_args() + js_args()
    if t.kind == "audio":
        cmd += ["-f", "ba/b", "-x", "--audio-format", t.fmt or "mp3", "--audio-quality", "0"]
    else:
        h = t.quality if str(t.quality).isdigit() else ""
        sel = f"bv*[height<={h}]+ba/b[height<={h}]" if h else "bv*+ba/b"
        fmt = t.fmt or "mp4"
        cmd += ["-f", sel, "--merge-output-format", fmt]
        if fmt == "mp4":
            cmd += ["-S", "ext:mp4:m4a"]                          # prefer MP4-compatible codecs
    cmd.append(t.url)
    return cmd


def run_media(t):
    tools_ready.wait()
    if not os.path.exists(YTDLP):
        raise RuntimeError("Media engine missing - check your internet connection and restart")
    cmd = media_cmd(t)
    log.info("yt-dlp: %s", " ".join(cmd[:-1]) + " <url>")
    t.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                              encoding="utf-8", errors="replace", creationflags=NOWIN)
    base = cur_d = 0; errline = last = ""; done_already = False
    for line in t.proc.stdout:
        line = line.strip()
        if line.startswith("FG|"):
            p = (line.split("|", 5) + [""] * 6)[1:6]
            d, tot, sp, title = int(num(p[0])), int(num(p[1]) or num(p[2])), num(p[3]), p[4]
            cur_d = d
            t.done = base + d; t.size = base + tot; t.speed = sp
            if title and title != "NA": t.name = title
            continue
        if line:
            log.info("yt-dlp: %s", line[:300])
        if "[download] Destination:" in line:                      # a new stream (video, then audio) begins
            base += cur_d; cur_d = 0
            t.path = line.split("Destination:", 1)[1].strip()
        elif (m := re.search(r'Merging formats into "(.*)"', line)):
            t.path = m.group(1)
        elif line.startswith("[ExtractAudio] Destination:"):
            t.path = line.split("Destination:", 1)[1].strip()
        elif "has already been downloaded" in line:
            done_already = True
        if line.startswith("ERROR:"): errline = line
        elif line: last = line
    rc = t.proc.wait(); t.proc = None
    if t.stop.is_set():
        t.status = "Paused"
    elif rc == 0 or done_already:
        t.status = "Completed"; t.size = t.size or t.done
    else:
        t.status, t.err = "Error", (errline or last)[:200]


def fetch_playlist(url):
    """Returns (title, [(video_title, video_url), ...]); a single video gives one entry."""
    tools_ready.wait()
    if not os.path.exists(YTDLP):
        raise RuntimeError("Media engine missing")
    out = subprocess.run([YTDLP, "-J", "--flat-playlist", "--no-warnings"] + cookies_args() + js_args() + [url],
                         capture_output=True, text=True, encoding="utf-8", errors="replace",
                         timeout=180, creationflags=NOWIN)
    if out.returncode != 0:
        errs = [l for l in out.stderr.splitlines() if l.startswith("ERROR")]
        raise RuntimeError((errs[-1] if errs else out.stderr.strip()[-200:]) or "Could not read link")
    d = json.loads(out.stdout)
    if not d.get("entries"):
        return d.get("title", ""), [(d.get("title") or url, d.get("webpage_url") or url)]
    items = []
    for e in d["entries"]:
        if not e: continue
        u = e.get("url") or e.get("webpage_url") or ""
        if not u.startswith("http"):
            if e.get("id") and "youtube" in (e.get("ie_key") or "").lower():
                u = f"https://www.youtube.com/watch?v={e['id']}"
            else:
                continue
        items.append((e.get("title") or u, u))
    return d.get("title", ""), items


# ---------------------------------------------------------------- components (yt-dlp, Deno, ffmpeg)
def _gh_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
    return json.load(urllib.request.urlopen(req, timeout=20))


def _run(cmd, timeout=30):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, creationflags=NOWIN).stdout.strip()
    except Exception:
        return ""


def ytdlp_version():
    return _run([YTDLP, "--version"]) if os.path.exists(YTDLP) else ""


def deno_version():
    m = re.match(r"deno (\S+)", _run([DENO, "--version"]) if os.path.exists(DENO) else "")
    return m.group(1) if m else ""


def ffmpeg_latest():
    d = _gh_json(FFMPEG_API)
    a = next(x for x in d["assets"] if x["name"] == "ffmpeg-master-latest-win64-gpl.zip")
    return a["updated_at"][:10]


def _install_from_zip(url, wanted, say, label):
    """Download a zip; put files named in `wanted` into BIN via atomic replace."""
    zp = os.path.join(tempfile.gettempdir(), "flowget_dl.zip")
    fetch(url, zp, lambda f: say(f"Downloading {label}: {int(f * 100)}%"))
    try:
        with zipfile.ZipFile(zp) as z:
            for n in z.namelist():
                base = os.path.basename(n)
                if base.lower() in wanted:
                    dst = os.path.join(BIN, base); tmp = dst + ".new"
                    with z.open(n) as src, open(tmp, "wb") as out:
                        shutil.copyfileobj(src, out)
                    os.replace(tmp, dst)
    finally:
        try: os.remove(zp)
        except OSError: pass


def update_ytdlp(say=lambda m: None):
    say("Updating yt-dlp...")
    if os.path.exists(YTDLP):
        _run([YTDLP, "-U"], 120)                                   # yt-dlp replaces itself
    else:
        tmp = YTDLP + ".new"; fetch(YTDLP_URL, tmp); os.replace(tmp, YTDLP)
    settings["tools_checked"] = time.time(); save_settings()


def install_deno(say=lambda m: None):
    _install_from_zip(DENO_URL, {"deno.exe"}, say, "Deno")


def install_ffmpeg(say=lambda m: None):
    try: built = ffmpeg_latest()
    except Exception: built = time.strftime("%Y-%m-%d")
    _install_from_zip(FFMPEG_URL, {"ffmpeg.exe", "ffprobe.exe"}, say, "ffmpeg")
    settings["ffmpeg_built"] = built; save_settings()


def update_component(key, say=lambda m: None):
    {"ytdlp": update_ytdlp, "deno": install_deno, "ffmpeg": install_ffmpeg}[key](say)


def check_components():
    """One row per component: key, name, installed, latest, update (bool), error, info."""
    rows = []

    def row(key, name, inst, lat, upd, err="", info=None):
        rows.append({"key": key, "name": name, "installed": inst or "not installed", "latest": lat,
                     "update": upd, "error": err, "info": info})
    try:
        r = latest_release()
        row("app", f"{APP_NAME} app", VERSION, r["version"] if r else VERSION, bool(r), info=r)
    except Exception as e:
        row("app", f"{APP_NAME} app", VERSION, "?", False, str(e))
    try:
        inst = ytdlp_version(); lat = _gh_json(YTDLP_API)["tag_name"]
        row("ytdlp", "yt-dlp (media engine)", inst, lat, not inst or vt(lat) > vt(inst))
    except Exception as e:
        row("ytdlp", "yt-dlp (media engine)", ytdlp_version(), "?", False, str(e))
    try:
        inst = deno_version(); lat = _gh_json(DENO_API)["tag_name"].lstrip("v")
        row("deno", "Deno (YouTube support)", inst, lat, not inst or vt(lat) > vt(inst))
    except Exception as e:
        row("deno", "Deno (YouTube support)", deno_version(), "?", False, str(e))
    try:
        import datetime as dt
        built = settings.get("ffmpeg_built", ""); lat = ffmpeg_latest(); have = os.path.exists(FFMPEG)
        stale = (not have) or (not built) or (dt.date.fromisoformat(lat) - dt.date.fromisoformat(built)).days > 60
        row("ffmpeg", "ffmpeg (converter)", f"build {built}" if have and built else ("" if not have else "installed"),
            f"build {lat}", stale)
    except Exception as e:
        row("ffmpeg", "ffmpeg (converter)", "installed" if os.path.exists(FFMPEG) else "", "?", False, str(e))
    return rows


def setup_tools(say):
    """Install anything missing; keep yt-dlp and Deno fresh (every 12h) when auto-update is on."""
    failed = []

    def step(label, fn):
        try: fn()
        except Exception as e:
            log.exception(label); failed.append(label)
    due = settings["auto_engine_update"] and time.time() - settings["tools_checked"] > 12 * 3600
    try:
        if not os.path.exists(YTDLP) or due:
            say("Updating media engine..."); step("yt-dlp", lambda: update_ytdlp(say))
        if not os.path.exists(DENO):
            say("Downloading Deno (needed for YouTube)..."); step("Deno", lambda: install_deno(say))
        elif due:
            def refresh_deno():
                if vt(_gh_json(DENO_API)["tag_name"]) > vt(deno_version() or "0"): install_deno(say)
            step("Deno", refresh_deno)
        if not os.path.exists(FFMPEG):
            say("Downloading ffmpeg (one time, ~100 MB)..."); step("ffmpeg", lambda: install_ffmpeg(say))
        say("Ready" if not failed else f"Ready - could not set up: {', '.join(failed)} (see log)")
    finally:
        tools_ready.set()


# ---------------------------------------------------------------- app updates (GitHub Releases)
def vt(v):
    return tuple(int(x) for x in re.findall(r"\d+", v))


def latest_release():
    """Returns {'version','url','sha_url'} if a newer release exists, else None."""
    if "YOUR_USER" in GITHUB_REPO:
        raise RuntimeError("Set GITHUB_REPO in engine.py first")
    req = urllib.request.Request(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
                                 headers={"User-Agent": UA})
    d = json.load(urllib.request.urlopen(req, timeout=20))
    latest = d["tag_name"].lstrip("v")
    assets = {a["name"]: a["browser_download_url"] for a in d.get("assets", [])}
    name = next((n for n in assets if n.endswith("Setup.exe")), None)
    if name and vt(latest) > vt(VERSION):
        return {"version": latest, "url": assets[name], "sha_url": assets.get(name + ".sha256")}
    return None


def download_verified(url, sha_url, dest, cb=None):
    """Download an installer and refuse to keep it unless it matches the published SHA-256."""
    if not sha_url:
        raise RuntimeError("Release has no .sha256 file - refusing to install")
    req = urllib.request.Request(sha_url, headers={"User-Agent": UA})
    expected = urllib.request.urlopen(req, timeout=30).read().decode().split()[0].lower()
    fetch(url, dest, cb)
    h = hashlib.sha256()
    with open(dest, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    if h.hexdigest() != expected:
        os.remove(dest)
        raise RuntimeError("Update checksum mismatch - download discarded")
