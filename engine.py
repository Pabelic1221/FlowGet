"""FlowGet engine: downloads, yt-dlp integration, settings, queue persistence, updates."""
import os, sys, re, json, time, threading, subprocess, zipfile, tempfile, shutil, hashlib, logging
import urllib.request, urllib.parse

APP_NAME = "FlowGet"
VERSION = "1.4.0"
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
            "auto_engine_update": True, "tools_checked": 0, "ffmpeg_built": "", "theme": "dark", "geometry": ""}
settings = dict(DEFAULTS)


def _write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def _load_json(path, default):
    """Read JSON; a corrupt file is kept as <name>.bak instead of being silently lost."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except Exception:
        log.exception("corrupt file: %s", path)
        try: os.replace(path, path + ".bak")
        except OSError: pass
        return default


def load_settings():
    d = _load_json(SETTINGS_FILE, {})
    if isinstance(d, dict):
        settings.update(d)


def save_settings():
    try: _write_json(SETTINGS_FILE, settings)
    except Exception: log.exception("save settings")


load_settings()


def get_int(key, lo, hi):
    """Settings value as an int clamped to [lo, hi]; bad or tampered values fall back to the default."""
    try: v = int(settings.get(key, DEFAULTS[key]))
    except (TypeError, ValueError): v = int(DEFAULTS[key])
    return max(lo, min(hi, v))


def fmt_size(n):
    n = float(n or 0)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {u}" if u != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} PB"


_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}
_path_lock = threading.Lock()


def safe_name(n):
    n = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", n).strip(" .")[:180]
    if n.split(".")[0].upper() in _RESERVED:                        # CON, NUL, COM1... cannot be file names on Windows
        n = "_" + n
    return n


def valid_url(u):
    try: p = urllib.parse.urlparse(u)
    except ValueError: return False
    return p.scheme in ("http", "https") and bool(p.netloc) and not re.search(r"\s", u)


def unique_path(p):
    base, ext = os.path.splitext(p)
    i = 1
    while os.path.exists(p) or os.path.exists(p + ".part"):
        p = f"{base} ({i}){ext}"; i += 1
    return p


def fmt_eta(sec):
    sec = int(sec)
    if sec < 60: return f"{sec}s"
    if sec < 3600: return f"{sec // 60}m {sec % 60:02d}s"
    return f"{sec // 3600}h {(sec % 3600) // 60:02d}m"


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
           "path", "ranged", "segs", "etag")


class Task:
    def __init__(s, url, kind, folder, quality="best", fmt=""):
        s.url, s.kind, s.folder, s.quality, s.fmt = url, kind, folder, quality, fmt  # kind: file|video|audio
        s.name = url[:70]; s.size = 0; s.done = 0; s.speed = 0.0; s.last = 0; s._t = 0.0
        s.status = "Queued"; s.err = ""; s.path = None; s.ranged = False; s.segs = None; s.etag = ""
        s.stop = threading.Event(); s.lock = threading.Lock(); s.proc = None; s.thread = None
        s.notified = False; s.want_resume = False; s.fatal = ""

    def add(s, n):
        with s.lock:
            s.done += n

    def alive(s):
        return s.thread is not None and s.thread.is_alive()

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
        if s.alive(): return False                                 # never run two workers on one task
        s.stop.clear(); s.fatal = ""; s.status = "Downloading"; s.err = ""; s.want_resume = False
        s.last = s.done; s._t = 0.0; s.speed = 0.0
        s.thread = threading.Thread(target=s._run, daemon=True); s.thread.start()
        return True

    def _run(s):
        try:
            (run_http if s.kind == "file" else run_media)(s)
        except Exception as e:
            s.status, s.err = "Error", str(e)[:200]
            log.exception("task failed: %s", s.url)
        if s.want_resume and s.status == "Paused":                 # Resume was pressed while we were still stopping
            s.want_resume = False; s.status = "Queued"

    def pause(s):
        s.want_resume = False; s.stop.set()
        if s.proc:
            try: s.proc.terminate()
            except Exception: pass
        if s.status in ("Downloading", "Queued"):
            s.status = "Paused"

    def resume(s):
        if s.status in ("Paused", "Error"):
            s.want_resume = s.alive(); s.status = "Queued"

    def update_speed(s):
        """Smoothed speed from real elapsed time (file downloads)."""
        now = time.time()
        if s._t:
            inst = max(0.0, (s.done - s.last) / max(now - s._t, 0.001))
            s.speed = inst if not s.speed else 0.6 * s.speed + 0.4 * inst
        s._t = now; s.last = s.done

    def eta(s):
        return fmt_eta((s.size - s.done) / s.speed) if s.size and s.speed > 1 and s.size > s.done else ""


def cleanup_task(t):
    """Delete the partial file of a cancelled file download (retries while Windows still holds it)."""
    if t.kind != "file" or t.status == "Completed" or not t.path:
        return
    part = t.path + ".part"
    def work():
        for _ in range(10):
            try:
                if os.path.exists(part): os.remove(part)
                return
            except OSError:
                time.sleep(1)
    threading.Thread(target=work, daemon=True).start()


def save_queue(tasks):
    try: _write_json(QUEUE_FILE, [t.to_dict() for t in tasks])
    except Exception: log.exception("save queue")


def load_queue():
    out = []; data = _load_json(QUEUE_FILE, [])
    for d in data if isinstance(data, list) else []:
        try: out.append(Task.from_dict(d))
        except Exception: log.warning("skipped unreadable queue entry")
    return out


# ---------------------------------------------------------------- direct (HTTP) downloads
class _Fatal(Exception):
    """Unrecoverable for this download (server stopped supporting resume, or the file changed)."""


def part_of(t):
    return t.path + ".part"


def http_probe(t):
    req = urllib.request.Request(t.url, headers={"User-Agent": UA, "Range": "bytes=0-0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        cr = r.headers.get("Content-Range"); cd = r.headers.get("Content-Disposition", "")
        final = r.geturl()
        if r.status == 206 and cr:
            t.size = int(cr.split("/")[-1]); t.ranged = True
        else:
            t.size = int(r.headers.get("Content-Length", 0)); t.ranged = False
        et, lm = r.headers.get("ETag", ""), r.headers.get("Last-Modified", "")
        t.etag = et if et and not et.startswith("W/") else lm         # validator for If-Range
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
                if t.etag: h["If-Range"] = t.etag                   # server answers 200 if the file changed
            t0 = time.time(); sent = 0
            with urllib.request.urlopen(urllib.request.Request(t.url, headers=h), timeout=30) as r, \
                    open(part_of(t), "r+b") as f:
                if t.ranged and (r.status != 206 or
                                 not (r.headers.get("Content-Range") or "").startswith(f"bytes {g['p']}-")):
                    raise _Fatal("The server stopped supporting resume or the file changed. "
                                 "Remove this item and add the link again.")
                f.seek(g["p"])
                while not t.stop.is_set():
                    b = r.read(65536)
                    if not b:
                        if g["e"] < 0 or g["p"] > g["e"]:
                            g["d"] = True
                            return
                        raise IOError("truncated")
                    f.write(b); g["p"] += len(b); t.add(len(b)); tries = 0
                    lim = get_int("speed_kbps", 0, 10_000_000) * 1024
                    if lim:                                       # global limit shared by the unfinished segments
                        left = sum(1 for x in t.segs if not x["d"]) or 1
                        sent += len(b)
                        wait = sent / (lim / left) - (time.time() - t0)
                        if wait > 0: time.sleep(min(wait, 1))
        except _Fatal as e:
            t.fatal = str(e); t.stop.set(); return
        except Exception as e:
            tries += 1; log.warning("segment retry (%s): %s", tries, e)
            if not t.ranged:                                      # a fresh stream restarts at byte 0
                with t.lock:
                    t.done -= g["p"] - g["s"]; g["p"] = g["s"]
            t.stop.wait(min(2 * tries, 10))


def mark_of_the_web(path, url):
    """Tag a download as coming from the Internet so Windows SmartScreen / Protected View still apply."""
    if os.name != "nt":
        return
    try:
        p = urllib.parse.urlparse(url)                              # origin only: signed URLs can carry secrets
        with open(path + ":Zone.Identifier", "w", encoding="ascii", errors="ignore") as f:
            f.write(f"[ZoneTransfer]\r\nZoneId=3\r\nHostUrl={p.scheme}://{p.netloc}/\r\n")
    except OSError:
        pass                                                         # e.g. FAT/exFAT drives have no streams


def finalize(t):
    """Move name.part -> name once complete (retries: antivirus may briefly hold the file)."""
    for i in range(10):
        try:
            os.replace(part_of(t), t.path); mark_of_the_web(t.path, t.url); return
        except OSError:
            if i == 9: raise
            time.sleep(0.5)


def run_http(t):
    conns = get_int("connections", 1, 16)
    if t.segs:                                                     # resuming: is the partial file still there?
        if not t.path:
            t.segs = None
        elif not os.path.exists(part_of(t)):
            if os.path.exists(t.path) and not all(g["d"] for g in t.segs):
                os.replace(t.path, part_of(t))                     # partial file written by an older version
            else:
                t.segs = None
    if not t.segs:
        http_probe(t)
        os.makedirs(t.folder, exist_ok=True)
        if t.size and shutil.disk_usage(t.folder).free < t.size + 50 * 1024 * 1024:
            raise RuntimeError("Not enough free disk space")
        with _path_lock:                                           # two downloads can't pick the same name
            t.path = unique_path(os.path.join(t.folder, t.name)); t.name = os.path.basename(t.path)
            with open(part_of(t), "wb") as f:
                if t.size: f.truncate(t.size)
        if t.ranged and t.size > 2 * 1024 * 1024 and conns > 1:
            step = t.size // conns
            t.segs = [{"s": i * step, "p": i * step, "e": (i + 1) * step - 1 if i < conns - 1 else t.size - 1,
                       "d": False} for i in range(conns)]
        else:
            t.segs = [{"s": 0, "p": 0, "e": t.size - 1 if t.ranged else -1, "d": False}]
    t.done = sum(g["p"] - g["s"] for g in t.segs)
    ths = [threading.Thread(target=seg_worker, args=(t, g), daemon=True) for g in t.segs if not g["d"]]
    for th in ths: th.start()
    for th in ths: th.join()
    if t.fatal:                                                    # never keep a possibly corrupt file
        try: os.remove(part_of(t))
        except OSError: pass
        t.segs = None; t.done = 0; t.status, t.err = "Error", t.fatal
    elif t.stop.is_set():
        t.status = "Paused"
    elif all(g["d"] for g in t.segs):
        finalize(t); t.status = "Completed"; t.done = t.size or t.done
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
           "-o", "%(title).150s.%(ext)s", "--windows-filenames", "--retries", "10", "--fragment-retries", "10",
           "--concurrent-fragments", "4",
           "--progress-template",
           "download:FG|%(progress.downloaded_bytes)s|%(progress.total_bytes)s|"
           "%(progress.total_bytes_estimate)s|%(progress.speed)s|%(info.title)s"]
    if get_int("speed_kbps", 0, 10_000_000):
        cmd += ["-r", f"{get_int('speed_kbps', 0, 10_000_000)}K"]
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
    prefix = f"https://github.com/{GITHUB_REPO}/releases/download/"       # only trust our own release files
    assets = {a["name"]: a["browser_download_url"] for a in d.get("assets", [])
              if str(a.get("browser_download_url", "")).startswith(prefix)}
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
