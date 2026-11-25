"""Torrent / magnet support for FlowGet (uses the `libtorrent` Python package: pip install libtorrent).

One shared libtorrent session serves every torrent task. It shares the app's speed limit with the other
downloads, can leave through several network adapters (Settings > Network adapters) and does not seed after
a download finishes. The engine module is passed in (E) so this file never imports it.
"""
import os, re, time, threading, shutil, urllib.request, urllib.parse

MAGNET_RE = re.compile(r"^magnet:\?(?:.*&)?xt=urn:bt(?:ih|mh):", re.I)
TRACKERS = "router.bittorrent.com:6881,router.utorrent.com:6881,dht.transmissionbt.com:6881,dht.libtorrent.org:25401"

_ses = None
_handles = {}                                                     # id(task) -> torrent handle (kept while paused)
_lock = threading.Lock()
_applied = {}


def is_magnet(u):
    return bool(MAGNET_RE.match((u or "").strip()))


def is_torrent_link(u):
    u = (u or "").strip()
    if is_magnet(u): return True
    if re.match(r"https?://", u, re.I): return urllib.parse.urlparse(u).path.lower().endswith(".torrent")
    return u.lower().endswith(".torrent") and os.path.isfile(u)


def magnet_name(u):
    m = re.search(r"[?&]dn=([^&]+)", u)
    return urllib.parse.unquote_plus(m.group(1)) if m else ""


def _lt():
    try:
        import libtorrent as lt
    except ImportError:
        raise RuntimeError("Torrent engine missing. Install it with:  pip install libtorrent  (then restart FlowGet)")
    return lt


def _session(E):
    global _ses
    with _lock:
        if _ses is None:
            lt = _lt()
            _ses = lt.session({
                "user_agent": f"FlowGet/{E.VERSION}", "listen_interfaces": "0.0.0.0:6881,[::]:6881",
                "max_retry_port_bind": 20, "enable_dht": True, "enable_lsd": True, "enable_upnp": True,
                "enable_natpmp": True, "dht_bootstrap_nodes": TRACKERS, "active_downloads": -1, "active_limit": -1,
                "connections_limit": 400})
        return _ses


def _apply_limits(E, ses):
    """Download limit = the shared total, scaled to the torrents' share of all running downloads."""
    lim = E.get_int("speed_kbps", 0, 10_000_000) * 1024
    with E._active_lock: act = list(E._active)
    mine = sum(1 for x in act if x.kind == "torrent")
    want = {"download_rate_limit": int(lim * mine / max(1, len(act))) if lim else 0,
            "upload_rate_limit": E.get_int("torrent_upload_kbps", 0, 10_000_000) * 1024,
            "outgoing_interfaces": ",".join(E.bind_ips())}
    changed = {k: v for k, v in want.items() if _applied.get(k) != v}
    if changed:
        ses.apply_settings(changed); _applied.update(changed)


def _add(E, t, ses, lt):
    os.makedirs(t.folder, exist_ok=True)
    u = t.url.strip()
    if is_magnet(u):
        p = lt.parse_magnet_uri(u)
    else:
        if os.path.isfile(u):
            with open(u, "rb") as f: data = f.read()
        else:
            req = urllib.request.Request(u, headers={"User-Agent": E.UA})
            with urllib.request.urlopen(req, timeout=30) as r: data = r.read(16 << 20)
        p = lt.add_torrent_params()
        p.ti = lt.torrent_info(lt.bdecode(data))
    p.save_path = t.folder
    p.flags &= ~lt.torrent_flags.auto_managed                     # FlowGet's own queue decides what runs
    p.flags &= ~lt.torrent_flags.paused
    try:
        return ses.add_torrent(p)
    except RuntimeError as ex:
        if "duplicate" in str(ex).lower(): raise RuntimeError("This torrent is already in the list")
        raise


def run(t, E):
    lt = _lt(); ses = _session(E); key = id(t)
    h = _handles.get(key)
    if h is not None and h.is_valid():
        h.resume()
    else:
        if E.is_magnet_name(t): t.name = magnet_name(t.url) or "Magnet link"
        h = _handles[key] = _add(E, t, ses, lt)
    S = lt.torrent_status; t.info = ""; t.status = "Downloading"; last = 0.0; named = False
    while True:
        if t.stop.is_set():
            try: h.pause()
            except Exception: pass
            t.speed = 0.0; t.info = ""
            return
        st = h.status()
        if time.time() - last > 2: _apply_limits(E, ses); last = time.time()
        if st.errc.value(): raise RuntimeError(st.errc.message()[:150])
        if st.state == S.downloading_metadata:
            t.info = f"fetching metadata  ({st.num_peers} peers)"
        else:
            if not named:
                named = True; t.name = st.name or t.name
                if st.total_wanted and shutil.disk_usage(t.folder).free < st.total_wanted - st.total_wanted_done + 50 * 1024 * 1024:
                    raise RuntimeError("Not enough free disk space")
            t.size = st.total_wanted; t.done = st.total_wanted_done; t.speed = float(st.download_rate)
            if st.state in (S.checking_files, S.checking_resume_data):
                t.info = f"checking files {int(st.progress * 100)}%"
            else:
                t.info = f"{st.num_seeds} seeds, {st.num_peers - st.num_seeds} peers"
            if st.is_finished or st.state in (S.finished, S.seeding): break
        time.sleep(0.5)
    t.path = os.path.join(t.folder, st.name); t.done = t.size = max(t.size, t.done); t.speed = 0.0; t.info = ""
    _handles.pop(key, None)
    ses.remove_torrent(h)                                         # files stay; we do not seed after finishing
    t.status = "Completed"


def discard(t):
    """Remove an unfinished torrent from the session and delete its partial data."""
    h = _handles.pop(id(t), None)
    if h is not None and _ses is not None:
        try: _ses.remove_torrent(h, _lt().session.delete_files)
        except Exception: pass
