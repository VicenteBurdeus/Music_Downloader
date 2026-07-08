# Music Downloader

A desktop application for downloading music from YouTube as high-quality MP3/MP4 files with album management and an inline audio player.

## Features

- **Graphical interface** -- search YouTube, paste URLs, manage albums visually
- **Multi-album support** -- organize downloads into separate album subfolders with drag-and-drop reorder
- **YouTube search** -- find songs directly from the app by title or artist
- **URL paste** -- paste individual video or playlist links; playlist URLs prompt for a track limit
- **Download queue** -- add songs to a queue, download in parallel (configurable workers), auto-retry failed
- **Multi-format** -- MP3 (audio only, with optional embedded thumbnail) and MP4 (video); separate download archives per format
- **Local MP4→MP3 conversion** -- if you already have an MP4 file, converts locally via FFmpeg instead of re-downloading
- **Inline audio player** -- QtMultimedia-based playback with play/pause toggle, stop, next, volume control, and play-all
- **Statistics** -- per-album song count, total duration, track listing with play/delete per song
- **Settings** -- format, quality, parallel workers, thumbnail embed, albums folder, volume
- **Open folder** -- one-click access to your downloaded files
- **Ctrl+scroll zoom** -- scales the entire UI font
- **Command-line interface** -- also includes a terminal-based version with Rich UI

## Installation

```powershell
# Clone the repository
git clone https://github.com/your-username/music-downloader.git
cd music-downloader

# Create and activate virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

**Requirements:**
- Python 3.9+
- [FFmpeg](https://ffmpeg.org/) (required for audio extraction and conversion)

## Usage

### Graphical interface

```powershell
python main.py
```

1. **Create an album** -- click "+ New" in the sidebar
2. **Search for songs** -- type in the search bar on the Search tab and press Enter
3. **Add to queue** -- double-click a result, or select rows and click "Add Selected"
4. **Paste URLs** -- paste YouTube links in the URL bar; playlists will ask for a track limit
5. **Download** -- switch to the Downloads tab and click "Download All"
6. **Play music** -- go to the Stats tab and click ▶ on any song; use Play All for the full album
7. **Manage files** -- delete songs with ✕, reorder albums by dragging them in the sidebar
8. **Settings** -- Ctrl+scroll to zoom, adjust volume/format/quality in the Settings tab

### Command-line interface

```powershell
# Download songs listed in ./urls.txt to ./musica/
python descargar.py

# Download songs from a specific album subfolder
python descargar.py "my album"

# View statistics for downloaded songs
python stats.py
```

`urls.txt` format (one entry per line):
```
https://www.youtube.com/watch?v=VIDEO_ID        # single video
pl https://www.youtube.com/playlist?list=ID  5  # playlist, max 5 songs
```

## Project structure

```
├── main.py                 # GUI entry point
├── descargar.py            # CLI downloader (Rich terminal UI)
├── stats.py                # CLI statistics viewer
├── gui/
│   ├── app.py              # Main application window (PySide6)
│   └── workers.py          # Background thread workers
├── core/
│   ├── downloader.py       # yt-dlp wrapper (search, download, MP4→MP3)
│   └── album.py            # Album management (folders, stats, archive)
├── albums/                 # Default albums directory (configurable)
├── requirements.txt
└── settings.json           # Persistent settings (auto-generated)
```

## Settings

| Setting | Default | Description |
|---------|---------|-------------|
| Format | MP3 | Download as MP3 (audio) or MP4 (video) |
| Quality | 0 (best) | Audio quality 0-9 (MP3 only) |
| Max workers | 3 | Number of parallel downloads |
| Embed thumbnail | On | Embed cover art into MP3 files |
| Albums folder | ./albums/ | Where album subfolders are stored |
| Volume | 80 | Playback volume (0-100) |
| Album order | (auto) | Drag-and-drop order persisted between sessions |

## Dependencies

| Package | Purpose |
|---------|---------|
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Video/audio downloading from YouTube |
| [PySide6](https://wiki.qt.io/Qt_for_Python) | Desktop GUI framework |
| [Rich](https://github.com/Textualize/rich) | Terminal UI (CLI version) |
| [FFmpeg](https://ffmpeg.org/) | Audio extraction and format conversion |

## Disclaimer

This project was primarily developed with AI assistance. It is provided for educational purposes only. Users are responsible for complying with the terms of service of any platform they download from and applicable copyright laws in their jurisdiction.

## License

[GNU General Public License v3.0](https://www.gnu.org/licenses/gpl-3.0.html)
