"""YouTube/Spotify search and download operations using yt-dlp."""

import json
import os
import re
import shutil
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FFMPEG_DIR = shutil.which("ffmpeg")
if not FFMPEG_DIR:
    for p in [
        r"C:\Users\vBursanHome\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.2-full_build\bin",
    ]:
        if os.path.isfile(os.path.join(p, "ffmpeg.exe")):
            FFMPEG_DIR = p
            break


def search_youtube(query, limit=10):
    """Search YouTube and return list of video info dicts."""
    results = []
    try:
        r = subprocess.run(
            [sys.executable, "-m", "yt_dlp",
             "--flat-playlist", "--dump-json", "--skip-download",
             f"ytsearch{limit}:{query}"],
            capture_output=True, text=True, encoding="utf-8",
            timeout=30,
            cwd=SCRIPT_DIR,
        )
        for line in r.stdout.strip().split("\n"):
            if not line.strip():
                continue
            try:
                info = json.loads(line)
                thumb = ""
                thumbnails = info.get("thumbnails", [])
                if thumbnails:
                    thumb = thumbnails[-1].get("url", "")
                results.append({
                    "id": info.get("id", ""),
                    "title": info.get("title", "Unknown"),
                    "duration": info.get("duration", 0) or 0,
                    "channel": info.get("channel") or info.get("uploader", "Unknown"),
                    "url": f"https://www.youtube.com/watch?v={info.get('id', '')}",
                    "thumbnail": thumb,
                })
            except json.JSONDecodeError:
                continue
    except Exception:
        pass
    return results


def resolve_playlist(url, limit=None):
    """Resolve a playlist URL to individual video dicts with id, title, url."""
    entries = []
    try:
        args = [
            sys.executable, "-m", "yt_dlp",
            "--flat-playlist", "--dump-json", "--skip-download",
        ]
        if limit:
            args += ["--playlist-end", str(limit)]
        args.append(url)

        r = subprocess.run(
            args,
            capture_output=True, text=True, encoding="utf-8",
            timeout=60,
            cwd=SCRIPT_DIR,
        )
        for line in r.stdout.strip().split("\n"):
            if not line.strip():
                continue
            try:
                info = json.loads(line)
                vid = info.get("id", "")
                if vid and re.match(r"^[\w-]{11}$", vid):
                    entries.append({
                        "id": vid,
                        "title": info.get("title", vid),
                        "url": f"https://www.youtube.com/watch?v={vid}",
                    })
            except json.JSONDecodeError:
                continue
    except Exception:
        pass
    return entries


def get_video_info(url):
    """Get info for a single video URL."""
    try:
        r = subprocess.run(
            [sys.executable, "-m", "yt_dlp",
             "--dump-json", "--skip-download", url],
            capture_output=True, text=True, encoding="utf-8",
            timeout=30,
            cwd=SCRIPT_DIR,
        )
        info = json.loads(r.stdout)
        thumb = ""
        thumbnails = info.get("thumbnails", [])
        if thumbnails:
            thumb = thumbnails[-1].get("url", "")
        return {
            "id": info.get("id", ""),
            "title": info.get("title", "Unknown"),
            "duration": info.get("duration", 0) or 0,
            "channel": info.get("channel") or info.get("uploader", "Unknown"),
            "url": info.get("webpage_url", url),
            "thumbnail": thumb,
        }
    except Exception:
        return None


def extract_id(url):
    """Extract YouTube video ID from URL."""
    m = re.search(r"(?:v=|/)([\w-]{11})", url)
    return m.group(1) if m else None


def find_ffmpeg():
    """Locate ffmpeg executable."""
    if FFMPEG_DIR:
        exe = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
        candidate = os.path.join(FFMPEG_DIR, exe)
        if os.path.isfile(candidate):
            return candidate
    return shutil.which("ffmpeg")


def get_output_filename(url, output_dir):
    """Predict the basename (no extension) yt-dlp would use for this URL."""
    template = os.path.join(output_dir, "%(title)s.%(ext)s")
    try:
        r = subprocess.run(
            [sys.executable, "-m", "yt_dlp",
             "--get-filename", "-o", template, url],
            capture_output=True, text=True, encoding="utf-8",
            timeout=15, cwd=SCRIPT_DIR,
        )
        filename = r.stdout.strip()
        if filename:
            return os.path.splitext(filename)[0]
    except Exception:
        pass
    return None


def convert_to_mp3(input_path, output_dir, ffmpeg_path=None):
    """Convert a video file to MP3 using FFmpeg. Returns True on success."""
    ffmpeg = ffmpeg_path or find_ffmpeg()
    if not ffmpeg:
        return False
    basename = os.path.splitext(os.path.basename(input_path))[0]
    output_path = os.path.join(output_dir, basename + ".mp3")
    try:
        r = subprocess.run(
            [ffmpeg, "-i", input_path, "-vn", "-q:a", "0",
             "-map_metadata", "0", "-id3v2_version", "3",
             "-y", output_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=300,
        )
        return r.returncode == 0
    except Exception:
        return False


def build_download_args(output_dir, archive_file, fmt="mp3", quality="0",
                         embed_thumbnail=True, ffmpeg_dir=None):
    """Build yt-dlp argument list for download."""
    template = os.path.join(output_dir, "%(title)s.%(ext)s")

    args = [
        "-o", template,
        "--download-archive", archive_file,
        "--no-playlist",
    ]

    if fmt == "mp3":
        args += [
            "-f", "bestaudio",
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", quality,
        ]
        if embed_thumbnail:
            args += ["--embed-thumbnail"]
    else:
        args += [
            "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--merge-output-format", "mp4",
        ]

    ffmpeg_loc = ffmpeg_dir or FFMPEG_DIR
    if ffmpeg_loc:
        args += ["--ffmpeg-location", ffmpeg_loc]

    return args


def download_video(url, output_dir, archive_file, fmt="mp3", quality="0",
                    embed_thumbnail=True):
    """Download a single video. Converts MP4->MP3 locally if source exists."""
    if fmt == "mp3":
        base = get_output_filename(url, output_dir)
        if base:
            for ext in [".mp4", ".webm", ".mkv"]:
                candidate = base + ext
                if os.path.isfile(candidate):
                    if convert_to_mp3(candidate, output_dir):
                        vid = extract_id(url)
                        if vid:
                            with open(archive_file, "a", encoding="utf-8") as f:
                                f.write(f"youtube {vid}\n")
                        return True

    args = build_download_args(output_dir, archive_file, fmt, quality,
                                embed_thumbnail)
    r = subprocess.run(
        [sys.executable, "-m", "yt_dlp"] + args + [url],
        cwd=SCRIPT_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return r.returncode == 0
