"""Engine regression tests: resume integrity, races, name collisions, validation.

Run:  python tests/test_engine.py      (exit code 0 = all passed; uses a local test server, no internet)
"""
import sys, os, io, re, json, time, hashlib, threading, http.server, socketserver, shutil, tempfile
TMP = tempfile.mkdtemp(prefix="flowget-test-")
os.environ["LOCALAPPDATA"] = TMP                                    # keep test settings/queue away from the real ones
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine as E

PAYLOAD = os.urandom(24 * 1024 * 1024); WANT = hashlib.sha256(PAYLOAD).hexdigest()
STATE = {"etag": '"v1"', "plain_hits": 0, "conn": 0, "peak": 0}; LOCK = threading.Lock()
class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def do_GET(self):
        path = self.path.split("?")[0]; n = len(PAYLOAD); rng = self.headers.get("Range"); ifr = self.headers.get("If-Range")
        with LOCK: STATE["conn"] += 1; STATE["peak"] = max(STATE["peak"], STATE["conn"])
        try:
            honor = rng and path in ("/ok.bin", "/ignore.bin")
            if path == "/ignore.bin" and rng and not rng.startswith("bytes=0-0"): honor = False   # ignores real ranges
            if honor and ifr and ifr != STATE["etag"]: honor = False                              # file changed -> full 200
            if honor:
                a, b = re.match(r"bytes=(\d+)-(\d*)", rng).groups(); a = int(a); b = int(b) if b else n - 1
                self.send_response(206); self.send_header("Content-Range", f"bytes {a}-{b}/{n}")
            else:
                a, b = 0, n - 1; self.send_response(200)
            self.send_header("Content-Length", str(b - a + 1)); self.send_header("ETag", STATE["etag"]); self.end_headers()
            limit = b
            if path == "/plain.bin":
                with LOCK: STATE["plain_hits"] += 1; first = STATE["plain_hits"] == 1
                if first: limit = 10 * 1024 * 1024                                             # first connection drops early
            for i in range(a, limit + 1, 65536):
                self.wfile.write(PAYLOAD[i:min(i + 65536, limit + 1)]); time.sleep(0.0015)
            if limit < b: self.close_connection = True; self.connection.close()
        except (BrokenPipeError, ConnectionResetError, OSError): pass
        finally:
            with LOCK: STATE["conn"] -= 1
class S(socketserver.ThreadingMixIn, http.server.HTTPServer): daemon_threads = True
srv = S(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
B = f"http://127.0.0.1:{srv.server_address[1]}"; OUT = os.path.join(TMP, "out"); os.makedirs(OUT)
sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
def wait(t, cond=lambda t: t.status == "Downloading", timeout=90):
    d = time.time() + timeout
    while cond(t) and time.time() < d: time.sleep(0.05)
def drive(t, timeout=90):                                   # emulate the UI scheduler
    d = time.time() + timeout
    while time.time() < d:
        if t.status == "Queued" and not t.alive(): t.start()
        if t.status in ("Completed", "Error") and not t.alive(): return
        time.sleep(0.05)
ok = lambda name, c: print(("PASS " if c else "FAIL ") + name) or c
res = []

# 1) .part while downloading, final name only when complete
t = E.Task(f"{B}/ok.bin", "file", os.path.join(OUT, "1")); t.start()
while not (t.path and t.done > 2 * 1024 * 1024): time.sleep(0.02)
mid = os.path.exists(t.path + ".part") and not os.path.exists(t.path); wait(t)
res.append(ok("1 .part during download, final name only after completion", mid and t.status == "Completed" and sha(t.path) == WANT and not os.path.exists(t.path + ".part")))

# 2) server ignores Range on resume request -> Error, no corrupt file left
t = E.Task(f"{B}/ignore.bin", "file", os.path.join(OUT, "2")); t.start(); wait(t)
left = [f for f in os.listdir(os.path.join(OUT, "2"))] if os.path.isdir(os.path.join(OUT, "2")) else []
res.append(ok(f"2 server ignores Range -> error, nothing corrupt kept (status={t.status}, files={left})", t.status == "Error" and "resume" in t.err and left == []))

# 3) file changes between pause and resume -> detected; re-download then works
STATE["etag"] = '"v1"'; t = E.Task(f"{B}/ok.bin", "file", os.path.join(OUT, "3")); t.start()
while t.done < 5 * 1024 * 1024: time.sleep(0.02)
t.pause(); wait(t, lambda t: t.alive()); STATE["etag"] = '"v2"'; t.resume(); drive(t)
res.append(ok(f"3 file changed while paused -> detected ({t.err[:45]}...)", t.status == "Error" and "changed" in t.err and not [f for f in os.listdir(os.path.join(OUT, "3")) if f.endswith(".part")]))
t.resume(); drive(t)
res.append(ok("3b retry after error downloads the new version intact", t.status == "Completed" and sha(t.path) == WANT))

# 4) server without resume support drops the connection -> no duplicated/corrupt data
t = E.Task(f"{B}/plain.bin", "file", os.path.join(OUT, "4")); t.start(); wait(t, timeout=120)
res.append(ok(f"4 no-resume server + dropped connection -> intact file (status={t.status})", t.status == "Completed" and sha(t.path) == WANT))

# 5) Pause immediately followed by Resume must not start a second worker set
STATE["etag"] = '"v1"'; STATE["peak"] = 0; t = E.Task(f"{B}/ok.bin", "file", os.path.join(OUT, "5")); t.start()
time.sleep(0.4); t.pause(); t.resume(); drive(t)
res.append(ok(f"5 quick Pause+Resume -> one worker set, file intact (peak connections={STATE['peak']}, status={t.status})", t.status == "Completed" and sha(t.path) == WANT and STATE["peak"] <= 9))

# 6) same filename started simultaneously
a = E.Task(f"{B}/ok.bin?x=1", "file", os.path.join(OUT, "6")); b = E.Task(f"{B}/ok.bin?x=2", "file", os.path.join(OUT, "6")); a.start(); b.start(); drive(a); drive(b)
names = sorted(os.listdir(os.path.join(OUT, "6"))); res.append(ok(f"6 same-name downloads get distinct files {names}", a.status == b.status == "Completed" and a.path != b.path and all(sha(p) == WANT for p in (a.path, b.path))))

# 7) names + URLs
res.append(ok("7 reserved/odd names", E.safe_name("CON.txt") == "_CON.txt" and E.safe_name("a/b:c?.zip") == "a_b_c_.zip" and E.safe_name("..") == "" and E.safe_name("nul") == "_nul"))
res.append(ok("7b URL validation", all(E.valid_url(u) for u in ("https://a.com/x", "http://h:8/p?q=1")) and not any(E.valid_url(u) for u in ("-o /etc/x", "file:///c:/x", "javascript:1", "http://", "https://a b.com", "ftp://a.com/x"))))

# 8) corrupt files are preserved, bad entries skipped
open(E.QUEUE_FILE, "w").write("{not json"); r = E.load_queue()
res.append(ok("8 corrupt queue.json -> [] and kept as .bak", r == [] and os.path.exists(E.QUEUE_FILE + ".bak") and not os.path.exists(E.QUEUE_FILE)))
good = E.Task("http://x.com/a.zip", "file", TMP).to_dict(); json.dump([good, {"junk": 1}, "str", good], open(E.QUEUE_FILE, "w"))
res.append(ok("8b unreadable queue entries skipped, good ones kept", len(E.load_queue()) == 2))

# 9) update URLs must belong to our own repo's releases
E.GITHUB_REPO = "Pabelic1221/FlowGet"; real = E.urllib.request.urlopen
def fake(payload): return lambda req, timeout=None: io.BytesIO(json.dumps(payload).encode())
pre = "https://github.com/Pabelic1221/FlowGet/releases/download/v9.0.0/"
E.urllib.request.urlopen = fake({"tag_name": "v9.0.0", "assets": [{"name": "FlowGet-Setup.exe", "browser_download_url": "https://evil.example/x.exe"}, {"name": "FlowGet-Setup.exe.sha256", "browser_download_url": "https://evil.example/x.sha"}]})
r1 = E.latest_release()
E.urllib.request.urlopen = fake({"tag_name": "v9.0.0", "assets": [{"name": "FlowGet-Setup.exe", "browser_download_url": pre + "FlowGet-Setup.exe"}, {"name": "FlowGet-Setup.exe.sha256", "browser_download_url": pre + "FlowGet-Setup.exe.sha256"}]})
r2 = E.latest_release(); E.urllib.request.urlopen = real
res.append(ok("9 foreign download URLs ignored, own-repo URLs accepted", r1 is None and r2 and r2["sha_url"].endswith(".sha256")))

# 10) tampered settings / helpers
E.settings.update(connections="lots", speed_kbps=-5, max_concurrent=999)
res.append(ok("10 tampered settings are clamped", E.get_int("connections", 1, 16) == 8 and E.get_int("speed_kbps", 0, 10**7) == 0 and E.get_int("max_concurrent", 1, 10) == 10))
res.append(ok("10b ETA formatting", [E.fmt_eta(x) for x in (5, 125, 3725)] == ["5s", "2m 05s", "1h 02m"]))
print(f"\n{sum(res)}/{len(res)} passed")
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(0 if all(res) else 1)
