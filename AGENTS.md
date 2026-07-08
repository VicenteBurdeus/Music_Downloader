# AGENTS.md

## Overview

Music Downloader -- desktop application for downloading music from YouTube and Spotify as high-quality MP3/MP4 files.

- Language: **Python 3.9+**
- GUI: **PySide6** (Qt for Python)
- Terminal UI: **Rich**
- Download engine: **yt-dlp**
- External tool: **FFmpeg** (required for audio extraction/conversion)

## Setup

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run

```powershell
python main.py           # GUI
python descargar.py      # CLI (downloads from urls.txt)
python stats.py          # CLI (show statistics)
```

## Architecture

```
main.py                 GUI entry point
descargar.py            CLI downloader (Rich terminal UI)
stats.py                CLI statistics viewer
settings.json           Persistent settings (auto-generated)

gui/                    PySide6 graphical interface
├── app.py              MainWindow -- sidebar, tabs, download orchestrator, media player
└── workers.py          QThread workers for search, download, playlist resolve, stats

core/                   Shared business logic
├── album.py            Album management (subfolders, urls.txt, stats via ffprobe)
└── downloader.py       yt-dlp wrapper (search YouTube, resolve playlists, download, MP4->MP3 convert)
```

### GUI tabs

| Tab | Purpose |
|-----|---------|
| Search | Search YouTube, view results, paste URLs, add to queue |
| Downloads | Queue management, download all/selected, retry, play buttons |
| Stats | Per-album song count, total duration, play/delete per song |
| Settings | Format (MP3/MP4), quality, workers, thumbnail, storage folder, volume |

### Key features

- **Multi-format**: MP3 and MP4 tracked independently (separate `descargados_*.txt` archives)
- **Local conversion**: MP4→MP3 converts existing local file via FFmpeg instead of re-downloading
- **Inline audio player**: QtMultimedia-based playback with play/pause toggle and volume control
- **Ctrl+scroll zoom**: scales the entire UI font
- **Album subfolders**: albums stored in `./albums/` (configurable)
- **Playlist limit**: pasting a playlist URL prompts for max tracks (default 25)

### CLI scripts

| Script | Purpose |
|--------|---------|
| `descargar.py` | Read `urls.txt`, download concurrently (Rich live UI), auto-retry |
| `stats.py` | Scan album folder, show durations via ffprobe |

## Code conventions

- English names (functions, variables, UI)
- 4-space indentation
- Double-quoted strings
- Type annotations where helpful (core modules)
- Subprocess calls via `sys.executable -m yt_dlp` (respects venv)
- Qt signals/slots for thread-safe GUI updates
- `Rich` for terminal UI panels and progress bars

## urls.txt format

One entry per line:

```
https://www.youtube.com/watch?v=VIDEO_ID        # single video
pl https://www.youtube.com/playlist?list=ID  5  # playlist, max 5 songs
```

Already-downloaded videos are tracked in `descargados.txt` (MP3) / `descargados_mp4.txt` (MP4) in yt-dlp archive format.
