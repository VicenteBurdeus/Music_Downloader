"""Album management - subfolder operations, file tracking, statistics."""

import json
import os
import shutil
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_albums_dir = os.path.join(SCRIPT_DIR, "albums")


def set_albums_dir(path):
    """Set the base directory where album subfolders are stored."""
    global _albums_dir
    _albums_dir = os.path.abspath(path)


def get_albums_dir():
    """Get the base directory where albums are stored."""
    return _albums_dir


def list_albums():
    """Return list of album names (subdirectories containing urls.txt)."""
    base = get_albums_dir()
    os.makedirs(base, exist_ok=True)
    albums = []
    try:
        for entry in os.listdir(base):
            path = os.path.join(base, entry)
            if os.path.isdir(path) and not entry.startswith("."):
                if os.path.isfile(os.path.join(path, "urls.txt")):
                    albums.append(entry)
    except FileNotFoundError:
        pass
    return sorted(albums)


def create_album(name):
    """Create a new album folder with empty urls.txt."""
    path = os.path.join(get_albums_dir(), name)
    os.makedirs(path, exist_ok=True)
    urls_file = os.path.join(path, "urls.txt")
    if not os.path.isfile(urls_file):
        with open(urls_file, "w", encoding="utf-8") as f:
            pass
    return path


def delete_album(name):
    """Delete an album folder and all its contents."""
    path = os.path.join(get_albums_dir(), name)
    if os.path.isdir(path):
        shutil.rmtree(path)


def rename_album(old_name, new_name):
    """Rename an album folder."""
    base = get_albums_dir()
    old_path = os.path.join(base, old_name)
    new_path = os.path.join(base, new_name)
    if os.path.isdir(old_path) and not os.path.exists(new_path):
        os.rename(old_path, new_path)
        return True
    return False


def get_album_paths(name, fmt="mp3"):
    """Get paths for an album's files. Archive is format-specific."""
    base = os.path.join(get_albums_dir(), name)
    suffix = "" if fmt == "mp3" else f"_{fmt}"
    return {
        "base": base,
        "urls": os.path.join(base, "urls.txt"),
        "archive": os.path.join(base, f"descargados{suffix}.txt"),
        "output": os.path.join(base, "musica"),
    }


def read_urls(album_name):
    """Read urls.txt for an album, return list of (type, url, limit) tuples."""
    paths = get_album_paths(album_name)
    if not os.path.isfile(paths["urls"]):
        return []
    urls = []
    with open(paths["urls"], "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if parts[0] == "pl" and len(parts) >= 3:
                urls.append(("playlist", parts[1], int(parts[2])))
            else:
                urls.append(("video", parts[0], None))
    return urls


def write_urls(album_name, urls):
    """Write urls.txt for an album."""
    paths = get_album_paths(album_name)
    os.makedirs(paths["base"], exist_ok=True)
    with open(paths["urls"], "w", encoding="utf-8") as f:
        for entry in urls:
            if entry[0] == "playlist":
                f.write(f"pl {entry[1]} {entry[2]}\n")
            else:
                f.write(f"{entry[1]}\n")


def add_url_to_album(album_name, url):
    """Append a single video URL to the album's urls.txt."""
    paths = get_album_paths(album_name)
    os.makedirs(paths["base"], exist_ok=True)
    with open(paths["urls"], "a", encoding="utf-8") as f:
        f.write(f"{url}\n")


def get_downloaded_ids(album_name, fmt="mp3"):
    """Get set of downloaded video IDs from descargados (format-specific)."""
    paths = get_album_paths(album_name, fmt)
    archive = paths["archive"]
    if not os.path.isfile(archive):
        return set()
    ids = set()
    with open(archive, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("youtube "):
                ids.add(line.split()[1])
    return ids


def get_song_stats(album_name):
    """Get statistics for an album's downloaded songs."""
    paths = get_album_paths(album_name)
    output_dir = paths["output"]
    if not os.path.isdir(output_dir):
        return {"count": 0, "total_duration": 0, "songs": []}

    songs = []
    for f in os.listdir(output_dir):
        fpath = os.path.join(output_dir, f)
        if os.path.isfile(fpath):
            dur = _get_duration(fpath)
            songs.append({"name": f, "path": fpath, "duration": dur})

    songs.sort(key=lambda x: x["duration"], reverse=True)
    total = sum(s["duration"] for s in songs)

    return {
        "count": len(songs),
        "total_duration": total,
        "songs": songs,
    }


def _find_ffprobe():
    """Locate ffprobe executable."""
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        return ffprobe
    for p in [
        r"C:\Users\vBursanHome\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.2-full_build\bin",
    ]:
        candidate = os.path.join(p, "ffprobe.exe")
        if os.path.isfile(candidate):
            return candidate
    return None


def _get_duration(filepath):
    """Get duration of audio/video file using ffprobe."""
    ffprobe = _find_ffprobe()
    if not ffprobe:
        return 0.0

    try:
        r = subprocess.run(
            [ffprobe, "-v", "quiet", "-print_format", "json",
             "-show_format", filepath],
            capture_output=True, text=True, encoding="utf-8",
            timeout=15,
        )
        data = json.loads(r.stdout)
        return float(data["format"]["duration"])
    except Exception:
        return 0.0


def format_duration(seconds):
    """Format seconds as H:MM:SS or M:SS."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}h {m:02d}m {s:02d}s"
    return f"{m}:{s:02d}"


def open_folder(album_name):
    """Open the album folder in system file explorer."""
    paths = get_album_paths(album_name)
    folder = paths["output"] if os.path.isdir(paths["output"]) else paths["base"]
    if sys.platform == "win32":
        os.startfile(folder)
    elif sys.platform == "darwin":
        subprocess.run(["open", folder])
    else:
        subprocess.run(["xdg-open", folder])
