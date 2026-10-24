"""FlowGet - glassmorphism UI (PySide6). Download logic lives in engine.py."""
import os, sys, ctypes, tempfile, subprocess, threading, urllib.parse
from ctypes import c_int, c_uint, c_void_p, c_size_t, Structure
from PySide6.QtCore import Qt, QTimer, Signal, QSize
from PySide6.QtGui import QPainter, QLinearGradient, QRadialGradient, QColor
from PySide6.QtWidgets import (QApplication, QWidget, QDialog, QDialogButtonBox, QVBoxLayout, QHBoxLayout,
                               QFormLayout, QLabel, QPlainTextEdit, QComboBox, QLineEdit, QPushButton,
                               QListWidget, QListWidgetItem, QFileDialog, QMessageBox, QFrame, QProgressBar,
                               QSpinBox, QCheckBox, QSystemTrayIcon, QMenu, QStyle)
import engine as E

QUALITY = [("Best", "best"), ("1080p", "1080"), ("720p", "720"), ("480p", "480"), ("360p", "360")]
VFMT = ["mp4", "mkv", "webm"]
AFMT = ["mp3", "m4a", "opus", "flac"]

QSS = """
* { font-family: 'Segoe UI Variable Text','Segoe UI',sans-serif; font-size: 13px; color: #f2f2fa; }
QDialog { background: #17162b; }
QFrame#card { background: rgba(255,255,255,20); border: 1px solid rgba(255,255,255,48); border-radius: 18px; }
QLabel { background: transparent; border: none; }
QLabel#title { font-size: 26px; font-weight: 700; }
QLabel#muted { color: rgba(242,242,250,150); font-size: 12px; }
QPlainTextEdit, QLineEdit, QSpinBox { background: rgba(0,0,0,70); border: 1px solid rgba(255,255,255,40);
    border-radius: 12px; padding: 7px 9px; selection-background-color: #7c6cf0; }
QComboBox { background: rgba(0,0,0,70); border: 1px solid rgba(255,255,255,40); border-radius: 12px; padding: 7px 12px; }
QComboBox:disabled, QSpinBox:disabled { color: rgba(242,242,250,70); }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: #1d1b30; border: 1px solid rgba(255,255,255,40);
    selection-background-color: #6d5bd0; outline: 0; }
QCheckBox { spacing: 8px; background: transparent; }
QCheckBox::indicator, QListView::indicator { width: 16px; height: 16px; border-radius: 5px;
    border: 1px solid rgba(255,255,255,90); background: rgba(0,0,0,70); }
QCheckBox::indicator:checked, QListView::indicator:checked { background: #8b5cf6; border-color: #8b5cf6; }
QPushButton { background: rgba(255,255,255,24); border: 1px solid rgba(255,255,255,55); border-radius: 12px; padding: 8px 16px; }
QPushButton:hover { background: rgba(255,255,255,44); }
QPushButton:pressed { background: rgba(255,255,255,16); }
QPushButton#accent { border: none; font-weight: 600; padding: 10px 16px;
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #22d3ee, stop:1 #8b5cf6); color: #0b0b18; }
QPushButton#accent:hover { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #67e8f9, stop:1 #a78bfa); }
QListWidget { background: transparent; border: none; outline: 0; }
QListWidget::item { background: transparent; border-radius: 18px; }
QListWidget::item:selected { background: rgba(139,92,246,60); }
QListWidget#plist { background: rgba(0,0,0,50); border: 1px solid rgba(255,255,255,40); border-radius: 12px; }
QListWidget#plist::item { border-radius: 8px; padding: 5px; }
QProgressBar { background: rgba(255,255,255,28); border: none; border-radius: 4px; }
QProgressBar::chunk { border-radius: 4px;
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #22d3ee, stop:1 #a78bfa); }
QMenu { background: #1d1b30; border: 1px solid rgba(255,255,255,40); padding: 4px; }
QMenu::item { padding: 6px 20px; border-radius: 6px; }
QMenu::item:selected { background: #6d5bd0; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical { background: rgba(255,255,255,70); border-radius: 4px; min-height: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
"""


def enable_blur(hwnd):
    """Native acrylic blur behind the window. Returns True if applied."""
    if sys.platform != "win32":
        return False
    try:
        dwm = ctypes.windll.dwmapi
        dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(c_int(1)), 4)        # dark title bar
        if sys.getwindowsversion().build >= 22621:                            # Windows 11 22H2+
            dwm.DwmSetWindowAttribute(hwnd, 38, ctypes.byref(c_int(3)), 4)    # acrylic backdrop

            class MARGINS(Structure):
                _fields_ = [(n, c_int) for n in ("l", "r", "t", "b")]
            dwm.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(MARGINS(-1, -1, -1, -1)))
            return True

        class ACCENT(Structure):                                              # Windows 10 / early 11
            _fields_ = [("State", c_int), ("Flags", c_int), ("Color", c_uint), ("Anim", c_int)]

        class WCA(Structure):
            _fields_ = [("Attr", c_int), ("Data", c_void_p), ("Size", c_size_t)]
        acc = ACCENT(4, 2, 0x99201510, 0)
        data = WCA(19, ctypes.cast(ctypes.pointer(acc), c_void_p), ctypes.sizeof(acc))
        ctypes.windll.user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data))
        return True
    except Exception:
        return False


def discard(path):
    try:
        if os.path.exists(path): os.remove(path)
    except OSError:
        pass


def reveal(path, folder):
    if os.name != "nt":
        return
    if path and os.path.exists(path):
        subprocess.Popen(["explorer", "/select," + os.path.normpath(path)])
    elif os.path.isdir(folder):
        os.startfile(folder)


class Card(QFrame):
    def __init__(s):
        super().__init__(); s.setObjectName("card")


class DownloadCard(Card):
    def __init__(s):
        super().__init__()
        s._col = None
        lay = QVBoxLayout(s); lay.setContentsMargins(16, 12, 16, 12); lay.setSpacing(6)
        row = QHBoxLayout()
        s.name = QLabel(); s.name.setStyleSheet("font-weight:600; font-size:14px;")
        s.state = QLabel(); s.state.setAlignment(Qt.AlignmentFlag.AlignRight)
        row.addWidget(s.name, 1); row.addWidget(s.state)
        s.bar = QProgressBar(); s.bar.setRange(0, 1000); s.bar.setTextVisible(False); s.bar.setFixedHeight(8)
        s.meta = QLabel(); s.meta.setObjectName("muted")
        lay.addLayout(row); lay.addWidget(s.bar); lay.addWidget(s.meta)

    def refresh(s, t):
        s.name.setText(t.name if len(t.name) < 70 else t.name[:67] + "...")
        pct = 1.0 if t.status == "Completed" else (min(1.0, t.done / t.size) if t.size else 0)
        s.bar.setValue(int(pct * 1000))
        col = {"Completed": "#4ade80", "Error": "#f87171", "Paused": "#fbbf24"}.get(t.status, "rgba(242,242,250,150)")
        if col != s._col:
            s._col = col; s.state.setStyleSheet(f"color:{col}; font-size:12px;")
        s.state.setText(t.status)
        if t.status == "Error" and t.err:
            s.meta.setText(t.err[:140]); return
        tag = {"file": "File", "video": "Video", "audio": "Audio"}.get(t.kind, "")
        spd = f"  •  {E.fmt_size(t.speed)}/s" if t.status == "Downloading" and t.speed else ""
        size = f"{E.fmt_size(t.done)} / {E.fmt_size(t.size)}" if t.size else E.fmt_size(t.done)
        s.meta.setText(f"{tag}  •  {int(pct * 100)}%  •  {size}{spd}")


class SettingsDialog(QDialog):
    def __init__(s, parent):
        super().__init__(parent); s.setWindowTitle("Settings"); s.setMinimumWidth(480)
        st = E.settings
        f = QFormLayout(s); f.setContentsMargins(20, 18, 20, 18); f.setVerticalSpacing(12)
        s.maxc = QSpinBox(); s.maxc.setRange(1, 10); s.maxc.setValue(st["max_concurrent"])
        s.conns = QSpinBox(); s.conns.setRange(1, 16); s.conns.setValue(st["connections"])
        s.speed = QSpinBox(); s.speed.setRange(0, 10_000_000); s.speed.setSuffix(" KB/s")
        s.speed.setSpecialValueText("Unlimited"); s.speed.setValue(st["speed_kbps"])
        s.folder = QLineEdit(st["folder"])
        br = QPushButton("Browse"); br.clicked.connect(s.browse)
        fr = QHBoxLayout(); fr.addWidget(s.folder, 1); fr.addWidget(br)
        s.cookies = QComboBox(); s.cookies.addItems(["None", "firefox", "chrome", "edge", "brave", "opera"])
        s.cookies.setCurrentText(st["cookies_browser"] or "None")
        s.cookies.setToolTip("Use your logged-in browser session for age-restricted / members-only videos.\n"
                             "Firefox is the most reliable; newer Chrome/Edge versions can fail to share cookies.")
        s.clip = QCheckBox("Detect links copied to the clipboard"); s.clip.setChecked(st["clipboard"])
        s.notify = QCheckBox("Show notifications when downloads finish"); s.notify.setChecked(st["notify"])
        f.addRow("Downloads at once", s.maxc); f.addRow("Connections per file", s.conns)
        f.addRow("Speed limit", s.speed); f.addRow("Default folder", fr)
        f.addRow("Use cookies from", s.cookies); f.addRow("", s.clip); f.addRow("", s.notify)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(s.accept); bb.rejected.connect(s.reject); f.addRow(bb)

    def browse(s):
        d = QFileDialog.getExistingDirectory(s, "Default folder", s.folder.text())
        if d: s.folder.setText(d)

    def apply(s):
        c = s.cookies.currentText()
        E.settings.update(max_concurrent=s.maxc.value(), connections=s.conns.value(), speed_kbps=s.speed.value(),
                          folder=s.folder.text().strip() or E.DEFAULT_DIR, cookies_browser="" if c == "None" else c,
                          clipboard=s.clip.isChecked(), notify=s.notify.isChecked())
        E.save_settings()


class PlaylistDialog(QDialog):
    def __init__(s, parent, title, items):
        super().__init__(parent); s.setWindowTitle("Choose items"); s.resize(580, 540)
        lay = QVBoxLayout(s); lay.setContentsMargins(18, 16, 18, 16); lay.setSpacing(10)
        lay.addWidget(QLabel(f"{title or 'Playlist'}  -  {len(items)} items"))
        s.list = QListWidget(); s.list.setObjectName("plist")
        for name, url in items:
            it = QListWidgetItem(name)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked); it.setData(Qt.ItemDataRole.UserRole, url)
            s.list.addItem(it)
        lay.addWidget(s.list, 1)
        row = QHBoxLayout()
        a = QPushButton("Select all"); n = QPushButton("Select none")
        a.clicked.connect(lambda: s.set_all(Qt.CheckState.Checked)); n.clicked.connect(lambda: s.set_all(Qt.CheckState.Unchecked))
        row.addWidget(a); row.addWidget(n); row.addStretch(1); lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("Download selected")
        bb.accepted.connect(s.accept); bb.rejected.connect(s.reject); lay.addWidget(bb)

    def set_all(s, state):
        for i in range(s.list.count()): s.list.item(i).setCheckState(state)

    def chosen(s):
        out = []
        for i in range(s.list.count()):
            it = s.list.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                out.append((it.text(), it.data(Qt.ItemDataRole.UserRole)))
        return out


class Main(QWidget):
    sig_msg = Signal(str)
    sig_update = Signal(object)
    sig_playlist = Signal(str, list)
    sig_quit = Signal()

    def __init__(s):
        super().__init__()
        s.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        s.setWindowTitle(f"{E.APP_NAME} {E.VERSION}"); s.resize(1020, 720); s.setMinimumSize(780, 560)
        s.blur = False; s._blurred = False; s.rows = []; s._quitting = False; s._lastclip = ""
        icon = QApplication.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown)
        s.setWindowIcon(icon)

        root = QVBoxLayout(s); root.setContentsMargins(22, 18, 22, 18); root.setSpacing(14)
        head = QHBoxLayout(); head.setSpacing(8)
        t = QLabel(E.APP_NAME); t.setObjectName("title")
        s.status = QLabel("Starting..."); s.status.setObjectName("muted")
        s.status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        st = QPushButton("Settings"); st.clicked.connect(s.open_settings)
        up = QPushButton("Check for updates"); up.clicked.connect(lambda: s.check_update(True))
        head.addWidget(t); head.addStretch(1); head.addWidget(s.status); head.addWidget(st); head.addWidget(up)
        root.addLayout(head)

        add = Card(); al = QVBoxLayout(add); al.setContentsMargins(16, 14, 16, 14); al.setSpacing(10)
        s.txt = QPlainTextEdit(); s.txt.setFixedHeight(84)
        s.txt.setPlaceholderText("Paste one or more links - one per line (files, YouTube, audio, video...)")
        al.addWidget(s.txt)
        opts = QHBoxLayout(); opts.setSpacing(8)
        s.kind = QComboBox(); s.kind.addItems(["Auto", "Direct file", "Video", "Audio"])
        s.quality = QComboBox()
        for label, val in QUALITY: s.quality.addItem(label, val)
        s.fmt = QComboBox()
        s.playlist = QCheckBox("Playlist: pick items")
        s.kind.currentTextChanged.connect(s.on_kind); s.on_kind()
        opts.addWidget(s.kind); opts.addWidget(s.quality); opts.addWidget(s.fmt); opts.addWidget(s.playlist)
        opts.addStretch(1); al.addLayout(opts)
        dest = QHBoxLayout(); dest.setSpacing(8)
        s.folder = QLineEdit(E.settings["folder"])
        br = QPushButton("Browse"); br.clicked.connect(s.browse)
        go = QPushButton("Add downloads"); go.setObjectName("accent"); go.clicked.connect(s.add_urls)
        dest.addWidget(s.folder, 1); dest.addWidget(br); dest.addWidget(go); al.addLayout(dest)
        root.addWidget(add)

        bar = QHBoxLayout(); bar.setSpacing(8)
        for label, fn in (("Pause", s.pause), ("Resume", s.resume), ("Remove", s.remove),
                          ("Clear completed", s.clear_done), ("Show in folder", s.open_folder)):
            b = QPushButton(label); b.clicked.connect(fn); bar.addWidget(b)
        bar.addStretch(1); root.addLayout(bar)

        s.list = QListWidget(); s.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        s.list.setSpacing(6); s.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        s.list.itemDoubleClicked.connect(s.open_item)
        root.addWidget(s.list, 1)

        # tray icon (notifications + keep downloading in background)
        s.tray_ok = QSystemTrayIcon.isSystemTrayAvailable()
        s.tray = QSystemTrayIcon(icon, s)
        s.tray_menu = QMenu()
        s.tray_menu.addAction("Show FlowGet", s.show_normal); s.tray_menu.addAction("Quit", s.quit_app)
        s.tray.setContextMenu(s.tray_menu)
        s.tray.activated.connect(lambda r: s.show_normal() if r == QSystemTrayIcon.ActivationReason.Trigger else None)
        if s.tray_ok: s.tray.show()

        s.sig_msg.connect(s.status.setText); s.sig_update.connect(s.offer)
        s.sig_playlist.connect(s.on_playlist); s.sig_quit.connect(s.quit_app)
        QApplication.clipboard().dataChanged.connect(s.on_clip)

        for task in E.load_queue():                                   # restore previous session
            s.add_task(task)
        threading.Thread(target=E.setup_tools, args=(s.sig_msg.emit,), daemon=True).start()
        QTimer.singleShot(4000, lambda: s.check_update(False))
        s.timer = QTimer(s); s.timer.timeout.connect(s.tick); s.timer.start(500)
        s.saver = QTimer(s); s.saver.timeout.connect(s.save); s.saver.start(5000)

    # ---- glass background
    def showEvent(s, e):
        super().showEvent(e)
        if not s._blurred:
            s._blurred = True; s.blur = enable_blur(int(s.winId())); s.update()

    def paintEvent(s, e):
        p = QPainter(s); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        a = 95 if s.blur else 255
        g = QLinearGradient(0, 0, s.width(), s.height())
        g.setColorAt(0, QColor(18, 16, 40, a)); g.setColorAt(1, QColor(8, 20, 38, a))
        p.fillRect(s.rect(), g)
        for cx, cy, col in ((0.12, 0.05, QColor(139, 92, 246)), (0.92, 0.95, QColor(34, 211, 238))):
            r = QRadialGradient(s.width() * cx, s.height() * cy, max(s.width(), s.height()) * 0.55)
            c1 = QColor(col); c1.setAlpha(95); c2 = QColor(col); c2.setAlpha(0)
            r.setColorAt(0, c1); r.setColorAt(1, c2); p.fillRect(s.rect(), r)

    # ---- adding downloads
    def on_kind(s):
        k = s.kind.currentText()
        s.quality.setEnabled(k in ("Auto", "Video")); s.fmt.setEnabled(k != "Direct file")
        s.playlist.setEnabled(k != "Direct file")
        s.fmt.clear(); s.fmt.addItems(AFMT if k == "Audio" else VFMT)

    def browse(s):
        d = QFileDialog.getExistingDirectory(s, "Save to", s.folder.text())
        if d: s.folder.setText(d)

    def make_task(s, url, media_only=False):
        k = s.kind.currentText()
        if k == "Audio":
            kind = "audio"
        elif k == "Video" or (media_only and k != "Audio"):
            kind = "video"
        elif k == "Direct file":
            kind = "file"
        else:                                                         # Auto: guess from the URL's extension
            ext = os.path.splitext(urllib.parse.urlparse(url).path)[1].lstrip(".").lower()
            kind = "file" if ext in E.FILE_EXTS else "video"
        quality = s.quality.currentData() if kind == "video" else "best"
        fmt = "" if kind == "file" else s.fmt.currentText()
        return E.Task(url, kind, s.folder.text().strip() or E.DEFAULT_DIR, quality, fmt)

    def add_urls(s):
        links = [l.strip() for l in s.txt.toPlainText().splitlines() if l.strip().lower().startswith("http")]
        if not links:
            QMessageBox.warning(s, E.APP_NAME, "Paste at least one http(s) link."); return
        if s.playlist.isChecked() and s.kind.currentText() != "Direct file":
            s.sig_msg.emit("Reading link...")
            for u in links:
                threading.Thread(target=s._read_playlist, args=(u,), daemon=True).start()
        else:
            for u in links: s.add_task(s.make_task(u))
        s.txt.clear()

    def _read_playlist(s, url):
        try:
            title, items = E.fetch_playlist(url)
            s.sig_playlist.emit(title, items)
        except Exception as e:
            s.sig_msg.emit(f"Could not read link: {e}")

    def on_playlist(s, title, items):
        if not items:
            s.sig_msg.emit("Nothing to download in that link."); return
        if len(items) == 1:
            chosen = items
        else:
            s.show_normal()
            dlg = PlaylistDialog(s, title, items)
            if dlg.exec() != QDialog.DialogCode.Accepted: s.sig_msg.emit("Ready"); return
            chosen = dlg.chosen()
        for name, url in chosen:
            task = s.make_task(url, media_only=True); task.name = name; s.add_task(task)
        s.sig_msg.emit(f"Added {len(chosen)} item(s)")

    def add_task(s, task):
        item = QListWidgetItem(); item.setSizeHint(QSize(0, 100))
        card = DownloadCard(); card.refresh(task)
        s.list.addItem(item); s.list.setItemWidget(item, card)
        s.rows.append((task, item, card))

    # ---- list actions
    def selected(s): return [r for r in s.rows if r[1].isSelected()]

    def pause(s):
        for t, _, _ in s.selected(): t.pause()

    def resume(s):
        for t, _, _ in s.selected():
            if t.status in ("Paused", "Error"): t.status = "Queued"

    def _drop(s, r):
        t = r[0]
        t.pause(); s.rows.remove(r); s.list.takeItem(s.list.row(r[1]))
        if t.kind == "file" and t.status != "Completed" and t.path:   # discard our own partial file
            QTimer.singleShot(1500, lambda p=t.path: discard(p))

    def remove(s):
        for r in s.selected(): s._drop(r)

    def clear_done(s):
        for r in [r for r in s.rows if r[0].status == "Completed"]:
            s.rows.remove(r); s.list.takeItem(s.list.row(r[1]))

    def open_folder(s):
        for t, _, _ in s.selected()[:1]: reveal(t.path, t.folder)

    def open_item(s, item):
        for t, i, _ in s.rows:
            if i is item:
                if t.status == "Completed" and t.path and os.path.exists(t.path) and os.name == "nt":
                    os.startfile(t.path)
                else:
                    reveal(t.path, t.folder)

    def tick(s):
        cap = int(E.settings["max_concurrent"])
        running = sum(1 for t, _, _ in s.rows if t.status == "Downloading")
        for t, _, card in s.rows:
            if t.status == "Queued" and running < cap:
                t.start(); running += 1
            if t.kind == "file":
                t.speed = max(0, (t.done - t.last) / 0.5); t.last = t.done
            card.refresh(t)
            if t.status == "Completed" and not t.notified:
                t.notified = True
                if E.settings["notify"] and s.tray_ok:
                    s.tray.showMessage("Download complete", t.name, QSystemTrayIcon.MessageIcon.Information, 5000)

    def save(s): E.save_queue([r[0] for r in s.rows])

    # ---- settings / clipboard
    def open_settings(s):
        dlg = SettingsDialog(s)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            dlg.apply(); s.folder.setText(E.settings["folder"])

    def on_clip(s):
        if not E.settings["clipboard"]: return
        txt = QApplication.clipboard().text().strip()
        if txt.lower().startswith("http") and "\n" not in txt and " " not in txt and txt != s._lastclip:
            s._lastclip = txt
            cur = s.txt.toPlainText().strip()
            if txt not in cur: s.txt.setPlainText((cur + "\n" if cur else "") + txt)
            s.sig_msg.emit("Link detected from clipboard - press Add downloads")

    # ---- app auto-update (checksum verified)
    def check_update(s, manual):
        def work():
            try:
                info = E.latest_release()
                if info: s.sig_update.emit(info)
                elif manual: s.sig_msg.emit("You're on the latest version.")
            except Exception as e:
                if manual: s.sig_msg.emit(f"Update check failed: {e}")
        threading.Thread(target=work, daemon=True).start()

    def offer(s, info):
        if QMessageBox.question(s, E.APP_NAME, f"Version {info['version']} is available. Update now?\n"
                                "(Downloads are saved and resume after the restart.)") != QMessageBox.StandardButton.Yes:
            return
        def work():
            try:
                p = os.path.join(tempfile.gettempdir(), "FlowGet-Setup.exe")
                E.download_verified(info["url"], info["sha_url"], p,
                                    lambda f: s.sig_msg.emit(f"Downloading update: {int(f * 100)}%"))
                subprocess.Popen([p, "/SILENT", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"], creationflags=E.NOWIN)
                s.sig_quit.emit()
            except Exception as e:
                s.sig_msg.emit(f"Update failed: {e}")
        threading.Thread(target=work, daemon=True).start()

    # ---- window lifecycle
    def show_normal(s):
        s.showNormal(); s.raise_(); s.activateWindow()

    def quit_app(s):
        s._quitting = True
        s.save()                                                      # active items resume on next launch
        for t, _, _ in s.rows: t.pause()
        E.save_settings()
        QApplication.quit()

    def closeEvent(s, e):
        busy = any(t.status in ("Downloading", "Queued") for t, _, _ in s.rows)
        if busy and s.tray_ok and not s._quitting:
            e.ignore(); s.hide()
            s.tray.showMessage(E.APP_NAME, "Still downloading in the background. Right-click the tray icon to quit.",
                               QSystemTrayIcon.MessageIcon.Information, 4000)
        else:
            s.quit_app(); e.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(QSS)
    w = Main(); w.show()
    sys.exit(app.exec())
