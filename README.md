<p align="center">
  <img src="files-logo/logo.svg" alt="FlowGet" width="440">
</p>

<p align="center">
  A multi-connection download manager for Windows with a modern glassmorphism UI.
  <br>
  Download files using parallel connections, or grab video and audio from sites supported by <a href="https://github.com/yt-dlp/yt-dlp">yt-dlp</a>.
</p>

## Features

**Downloading**
- Segmented downloads with up to **16 parallel connections** (8 by default), when supported by the server.
- Pause, resume, and retry downloads without losing progress.
- Download queue with configurable simultaneous downloads and speed limits.
- Disk-space checks before large downloads.
- Video and audio downloads from YouTube and other websites supported by yt-dlp.
- Video quality selection (Best, 1080p, 720p, 480p, 360p) and supported formats (MP4, MKV, WebM, MP3, M4A, Opus, FLAC).
- Playlist support with selectable items.
- Optional browser cookies for content requiring authentication.

**Application**
- Modern glassmorphism interface built with PySide6.
- Light and dark themes, with a System option.
- System tray icon and download completion notifications.
- Clipboard link detection for quick downloads.
- Settings and logging for troubleshooting.

**Updates**
- In-app updates for FlowGet, yt-dlp, Deno, and FFmpeg.
- Installer updates verified with SHA-256 checksums.

## Installation

1. Visit the [FlowGet Releases](https://github.com/Pabelic1221/FlowGet/releases) page.
2. Download the latest `FlowGet-Setup.exe`.
3. Run the installer and follow the instructions.
4. Launch FlowGet and wait until the status displays **Ready** before downloading video or audio.

On first launch, FlowGet downloads yt-dlp, Deno, and FFmpeg automatically (approximately 100 MB, one time).

## Requirements

- Windows 10 or Windows 11.
- Python 3.10 or newer, if running from source.
- Inno Setup 6, if building the installer yourself.

## Run from Source

```powershell
git clone https://github.com/Pabelic1221/FlowGet.git
cd FlowGet
py -m venv .venv
.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
py app.py
```

## Build the Installer

If you want to build the installer yourself, run:

```powershell
build.bat
```

The installer and checksum are generated in the `dist` folder.

## Troubleshooting

| Problem | Try |
|---|---|
| Video or audio downloads fail after launch | Wait until the status displays **Ready**, then retry. |
| YouTube asks you to sign in | Enable **Use cookies from** in Settings. |
| Some servers reject downloads | Lower **Connections per file** in Settings. |
| Blur effect is missing | Enable Windows transparency effects. |
| Antivirus flags the executable | PyInstaller one-file builds can trigger false positives; investigate detections before running the file. |

## Known Limitations

- No browser extension yet (the "download this" button on web pages)
- No download scheduler
- The UI uses a stock tray icon and no custom title bar
- Direct links that need a login, special headers or cookies are not supported
- Early release: the UI has had limited testing, so expect rough edges

## Responsible Use

Only download content you own or have permission to download. Respect the terms of service of the websites you use. DRM-protected services such as Spotify are not supported, and FlowGet does not support circumventing DRM.

## Third-Party Software

| Project | License |
|---|---|
| [PySide6 / Qt](https://doc.qt.io/qtforpython-6/) | LGPLv3, GPLv3, or commercial |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Unlicense |
| [Deno](https://github.com/denoland/deno) | MIT |
| [FFmpeg](https://ffmpeg.org/) | LGPL/GPL, depending on the build |
| [PyInstaller](https://pyinstaller.org/) | GPLv2+ with a bootloader exception |
| [Inno Setup](https://jrsoftware.org/isinfo.php) | Inno Setup license |

## License

Add your chosen license to the repository in a `LICENSE` file, then update this section to identify it.
