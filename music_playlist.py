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
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name or "").strip(" .")
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
                    tracks.append((t["title"].strip(), (t.get("subtitle") or "").replace("\xa0", " ").strip()))
            break
    return title or _meta_title(page), tracks


def _apple(url):
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
                        tracks.append((t["name"].strip(), artist.strip()))
    if not tracks:                                                # fallback: embedded app data
        m = re.search(r'<script[^>]+id="serialized-server-data"[^>]*>(.*?)</script>', page, re.S)
        if m:
            for d in _walk(json.loads(m.group(1))):
                if isinstance(d.get("title"), str) and isinstance(d.get("artistName"), str):
                    tracks.append((d["title"].strip(), d["artistName"].strip()))
    title = re.sub(r"\s+(on|by)\s+Apple\s+Music.*$", "", _meta_title(page), flags=re.I)
    return title, tracks


def fetch_music_playlist(url):
    """Return (folder_name, [(display_name, 'ytsearch1:...'), ...])."""
    title, tracks = _spotify(url) if SPOTIFY_RE.search(url) else _apple(url)
    seen, items = set(), []
    for name, artist in tracks:
        key = (name.lower(), artist.lower())
        if key in seen: continue
        seen.add(key)
        label = f"{artist} - {name}" if artist else name
        items.append((label, f"ytsearch1:{label}"))
    if not items: raise RuntimeError("No tracks found. The playlist must be public.")
    return safe_folder_name(title), items
