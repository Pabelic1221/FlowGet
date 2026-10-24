# FlowGet

A multi-connection download manager for Windows with a glassmorphism UI. It downloads regular files over parallel connections, and video and audio from sites supported by [yt-dlp](https://github.com/yt-dlp/yt-dlp).

![build](https://github.com/YOUR_USER/flowget/actions/workflows/build.yml/badge.svg)

> Replace `YOUR_USER` above with your GitHub username. Add a screenshot here once you have one: `![FlowGet](docs/screenshot.png)`

## Features

**Downloading**
- Segmented downloads: each file is split across up to 16 parallel connections (default 8) when the server supports range requests
- Pause, resume and retry with backoff. The queue and exact resume positions are saved, so downloads survive closing the app or a crash
- Queue with a configurable number of simultaneous downloads, plus a global speed limit
- Disk-space check before large downloads
- Video and audio from YouTube and the other sites yt-dlp supports
- Quality choice (best, 1080p, 720p, 480p, 360p), video formats (MP4, MKV, WebM) and audio formats (MP3, M4A, Opus, FLAC)
- Playlists: paste a link and pick which items to download
- Optional browser cookies (Firefox, Chrome, Edge, Brave, Opera) for age-restricted or members-only content

**App**
- Glass UI built with PySide6: native acrylic blur on Windows 10 and 11, with a dark gradient fallback where blur isn't available
- Tray icon, completion notifications, clipboard link detection, double-click to open a finished file
- Settings dialog and a log file for troubleshooting

**Updates**
- In-app **Updates** window for FlowGet, yt-dlp, Deno and ffmpeg (see [How updates work](#how-updates-work))
- Installer updates are verified against a published SHA-256 checksum before they run

## Requirements

- Windows 10 or 11. The strongest blur effect needs Windows 11 22H2 or newer.
- To run from source or build: Python 3.10 or newer. CI builds with 3.13.
- To build the installer: [Inno Setup 6](https://jrsoftware.org/isinfo.php)

## Run from source

```powershell
git clone https://github.com/YOUR_USER/flowget.git
cd flowget
py -m venv .venv
.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
py app.py
```

On first launch FlowGet downloads yt-dlp, Deno and ffmpeg (about 100 MB, once) into `%LOCALAPPDATA%\FlowGet\bin`. Wait for the status line to say **Ready** before downloading video or audio.

## Build the installer

```powershell
build.bat
```

This produces `dist\FlowGet-Setup.exe` and `dist\FlowGet-Setup.exe.sha256`. The installer is per-user (no admin prompt) and installs to `%LOCALAPPDATA%\Programs\FlowGet`.

For local builds that should check your repo for updates, set `GITHUB_REPO = "YOUR_USER/flowget"` in `engine.py`. Released builds get this stamped in automatically by CI.

## Release a new version

1. Merge your changes to `main`.
2. Tag and push:
   ```powershell
   git tag v1.2.1
   git push origin v1.2.1
   ```
3. GitHub Actions builds the installer, creates the checksum file and publishes a GitHub Release with both files attached.
4. Installed copies of FlowGet offer the update at their next launch.

Both `FlowGet-Setup.exe` and `FlowGet-Setup.exe.sha256` must be on the release. Without the checksum file, the app refuses to install the update.

## How updates work

| Component | Where it lives | How it stays current |
|---|---|---|
| yt-dlp | `%LOCALAPPDATA%\FlowGet\bin` | Updated automatically about every 12 hours (can be turned off in Settings) |
| Deno | same folder | Updated automatically. YouTube extraction needs a JavaScript runtime and FlowGet points yt-dlp at this copy |
| ffmpeg | same folder | You are advised when the build is over 60 days old and update from the Updates window |
| FlowGet | installed app | Prompts when a newer GitHub Release exists, verifies the checksum, installs silently and restarts |
| Python, PySide6 | bundled inside the exe | Cannot change after the build. Dependabot proposes newer pinned versions, CI test-builds them, and a new release delivers them |

## Project layout

```
app.py                         UI (PySide6): window, dialogs, tray
engine.py                      downloads, yt-dlp integration, settings, queue, updates
installer.iss                  Inno Setup installer script
build.bat                      local build: exe, installer, checksum
requirements.txt               pinned build dependencies
.github/workflows/build.yml    CI: test build on PRs, release build on tags
.github/dependabot.yml         weekly dependency update pull requests
```

## Where data is stored

| What | Location |
|---|---|
| Settings, queue, log | `%LOCALAPPDATA%\FlowGet\` (`settings.json`, `queue.json`, `flowget.log`) |
| yt-dlp, Deno, ffmpeg | `%LOCALAPPDATA%\FlowGet\bin\` |
| Downloaded files | your Downloads folder by default (change in Settings) |

The data folder is not removed on uninstall. Delete it by hand to reset everything.

## Troubleshooting

| Problem | Try |
|---|---|
| Video or audio downloads fail right after launch | Wait for the status line to say **Ready**, then retry |
| A site stopped working | Open **Updates** and update yt-dlp. Check `flowget.log` for the full error |
| YouTube asks you to sign in or confirm you're not a bot | Settings, then **Use cookies from**, then pick your browser. Firefox is the most reliable |
| Some servers reject downloads | Lower **Connections per file** in Settings |
| No blur effect | Turn on Windows transparency effects. Otherwise the app uses its dark gradient fallback |
| Update says there is no checksum file | Upload `FlowGet-Setup.exe.sha256` to the release |
| Antivirus flags the exe | This is a common false positive with PyInstaller `--onefile`. A `--onedir` build reduces it |

## Known limitations

- No browser extension yet (the "download this" button on web pages)
- No download scheduler
- The UI uses a stock tray icon and no custom title bar
- Direct links that need a login, special headers or cookies are not supported
- Early release: the UI has had limited testing, so expect rough edges

## Responsible use

Only download content you own or have permission to download. Many sites' terms of service prohibit downloading. DRM-protected services such as Spotify are not supported and this project will not add support for circumventing DRM.

## Third-party software

FlowGet builds on, or downloads at runtime, these projects. Check each license before redistributing.

| Project | License |
|---|---|
| [PySide6 / Qt](https://doc.qt.io/qtforpython-6/) | LGPLv3, GPLv3 or commercial |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Unlicense |
| [Deno](https://github.com/denoland/deno) | MIT |
| [FFmpeg](https://ffmpeg.org/) (builds from [yt-dlp/FFmpeg-Builds](https://github.com/yt-dlp/FFmpeg-Builds)) | LGPL/GPL depending on the build. FlowGet downloads the GPL build at runtime and does not bundle it |
| [PyInstaller](https://pyinstaller.org/) | GPLv2+ with a bootloader exception |
| [Inno Setup](https://jrsoftware.org/isinfo.php) | Inno Setup license |

If you distribute FlowGet, review the LGPL requirements for Qt. A `--onedir` build makes it easier to let users replace the Qt libraries. This is not legal advice.

## License

Choose a license for your own code before publishing (for example MIT) and add a `LICENSE` file, then state it here.
