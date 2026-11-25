"""Spotify / Apple Music playlist support for FlowGet.

No extra dependencies (stdlib only). Neither service lets you download audio directly, so the
playlist page is read to get the track list, and each track is then fetched through yt-dlp as a
"ytsearch1:Artist - Title" query. Files go into a folder named after the playlist.
"""
import re, json, html, urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")
SPOTIFY_RE = re.compile(r"open\.spotify\.com/(?:intl-[a-z-]+/)?(playlist|album)/([A-Za-z0-9]+)", re.I)
APPLE_RE = re.compile(r"music\.apple\.com/[a-z]{2}/(playlist|album)/", re.I)


def is_music_link(url):
    return bool(SPOTIFY_RE.search(url) or APPLE_RE.search(url))


def safe_folder_name(name, fallback="Playlist"):
    name = re.sub(r"[\u200b-\u200f\u202a-\u202e\ufeff]", "", name or "")      # invisible direction marks
    name = re.sub(r":\s+", " - ", name)                                         # "A: B" -> "A - B"
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    name = re.sub(r"[\u200b-\u200f\u202a-\u202e\ufeff]", "", name or "")      # invisible direction marks
    name = re.sub(r":\s+", " - ", name)                                         # "A: B" -> "A - B"
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return name[:100] or fallback


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", "replace")


def _walk(obj):
    """Yield every dict inside a nested JSON structure."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values(): yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj: yield from _walk(v)


def _secs(v, div=1):
    try: return int(round(float(v) / div))
    except (TypeError, ValueError): return 0


def _iso_secs(v):
    """'PT3M35S' -> 215"""
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", v or "")
    return int(int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + float(m.group(3) or 0)) if m else 0


def _meta(page, key):
    m = re.search(r'<meta[^>]+(?:name|property)="%s"[^>]+content="([^"]*)"' % re.escape(key), page)
    return html.unescape(m.group(1)).strip() if m else ""


def _meta_title(page):
    m = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]*)"', page)
    return html.unescape(m.group(1)).strip() if m else ""


def _spotify(url):
    kind, pid = SPOTIFY_RE.search(url).groups()
    page = _get(f"https://open.spotify.com/embed/{kind.lower()}/{pid}")
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', page, re.S)
    if not m: raise RuntimeError("Spotify page format not recognised (is the playlist public?)")
    data = json.loads(m.group(1))
    title, tracks = "", []
    for d in _walk(data):
        if not title and isinstance(d.get("name"), str) and "trackList" in d: title = d["name"]
        if isinstance(d.get("trackList"), list):
            for t in d["trackList"]:
                if t.get("title"):
                    tracks.append((t["title"].strip(), (t.get("subtitle") or "").replace("\xa0", " ").strip(),
                                   _secs(t.get("duration"), 1000)))
            break
    return title or _meta_title(page), tracks


def _apple_album_api(url):
    """Albums: Apple's public lookup API gives the full track list reliably."""
    m = re.search(r"music\.apple\.com/([a-z]{2})/album/.*?/(\d+)", url)
    if not m: return "", []
    data = json.loads(_get(f"https://itunes.apple.com/lookup?id={m.group(2)}&entity=song&country={m.group(1)}"))
    title, tracks = "", []
    for r in data.get("results", []):
        if r.get("wrapperType") == "collection": title = r.get("collectionName", "")
        elif r.get("wrapperType") == "track" and r.get("trackName"):
            tracks.append((r["trackName"], r.get("artistName", ""), _secs(r.get("trackTimeMillis"), 1000)))
    return title, tracks


def _apple(url):
    if "/album/" in url:
        try:
            title, tracks = _apple_album_api(url)
            if tracks: return title, tracks
        except Exception:
            pass                                                  # fall back to reading the page
    page = _get(url)
    tracks = []
    for m in re.finditer(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', page, re.S):
        try: ld = json.loads(m.group(1))
        except ValueError: continue
        for d in _walk(ld):
            if isinstance(d.get("track"), list):
                for t in d["track"]:
                    if isinstance(t, dict) and t.get("name"):
                        by = t.get("byArtist")
                        by = by[0] if isinstance(by, list) and by else by
                        artist = by.get("name", "") if isinstance(by, dict) else ""
                        tracks.append((t["name"].strip(), artist.strip(), _iso_secs(t.get("duration"))))
    if not tracks:                                                # fallback: embedded app data
        m = re.search(r'<script[^>]+id="serialized-server-data"[^>]*>(.*?)</script>', page, re.S)
        if m:
            for d in _walk(json.loads(m.group(1))):
                if isinstance(d.get("title"), str) and isinstance(d.get("artistName"), str):
                    tracks.append((d["title"].strip(), d["artistName"].strip(), 0))
    title = _meta(page, "apple:title")
    if not title:
        title = re.sub(r"\s+by\s+.*?\s+on\s+Apple\s+Music.*$", "", _meta_title(page), flags=re.I)
        title = re.sub(r"\s+on\s+Apple\s+Music.*$", "", title, flags=re.I)
    return title, tracks


def fetch_music_playlist(url):
    """Return (folder_name, [(display_name, 'ytsearch1:...'), ...])."""
    title, tracks = _spotify(url) if SPOTIFY_RE.search(url) else _apple(url)
    seen, items = set(), []
    for name, artist, dur in tracks:
        key = (name.lower(), artist.lower())
        if key in seen: continue
        seen.add(key)
        name = re.sub(r"\s*[\(\[]\s*mixed\s*[\)\]]\s*$", "", name, flags=re.I)   # DJ-mix suffix hurts matching
        label = f"{artist} - {name}" if artist else name
        items.append((label, f"ytsearch1:{label}" + (f" ||dur={dur}" if dur else "")))   # dur = real track length (s)
    if not items: raise RuntimeError("No tracks found. The playlist must be public.")
    return safe_folder_name(title), items
