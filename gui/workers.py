"""Background worker threads for search and download operations."""

from PySide6.QtCore import QThread, Signal

from core import album as album_mgr
from core.downloader import (
    download_video,
    get_video_info,
    resolve_playlist,
    search_youtube,
)


class SearchWorker(QThread):
    """Worker thread for YouTube search."""
    results_ready = Signal(list)
    error = Signal(str)

    def __init__(self, query, limit=10):
        super().__init__()
        self.query = query
        self.limit = limit

    def run(self):
        try:
            results = search_youtube(self.query, self.limit)
            self.results_ready.emit(results)
        except Exception as e:
            self.error.emit(str(e))


class VideoInfoWorker(QThread):
    """Worker thread for fetching single video info."""
    info_ready = Signal(dict)
    error = Signal(str)

    def __init__(self, url):
        super().__init__()
        self.url = url

    def run(self):
        try:
            info = get_video_info(self.url)
            if info:
                self.info_ready.emit(info)
            else:
                self.error.emit(f"Could not fetch info for {self.url}")
        except Exception as e:
            self.error.emit(str(e))


class PlaylistWorker(QThread):
    """Worker thread for resolving playlist URLs."""
    entries_ready = Signal(list)
    error = Signal(str)

    def __init__(self, url, limit=None):
        super().__init__()
        self.url = url
        self.limit = limit

    def run(self):
        try:
            entries = resolve_playlist(self.url, self.limit)
            self.entries_ready.emit(entries)
        except Exception as e:
            self.error.emit(str(e))


class DownloadWorker(QThread):
    """Worker thread for downloading a single video."""
    finished = Signal(int, bool)  # index, success

    def __init__(self, index, url, output_dir, archive_file, fmt="mp3",
                 quality="0", embed_thumbnail=True):
        super().__init__()
        self.index = index
        self.url = url
        self.output_dir = output_dir
        self.archive_file = archive_file
        self.fmt = fmt
        self.quality = quality
        self.embed_thumbnail = embed_thumbnail

    def run(self):
        try:
            success = download_video(
                self.url, self.output_dir, self.archive_file,
                self.fmt, self.quality, self.embed_thumbnail,
            )
            self.finished.emit(self.index, success)
        except Exception:
            self.finished.emit(self.index, False)


class StatsRefreshWorker(QThread):
    """Worker thread for refreshing album statistics (ffprobe calls)."""
    stats_ready = Signal(object)  # dict with count, total_duration, songs
    error = Signal(str)

    def __init__(self, album_name):
        super().__init__()
        self.album_name = album_name

    def run(self):
        try:
            stats = album_mgr.get_song_stats(self.album_name)
            self.stats_ready.emit(stats)
        except Exception as e:
            self.error.emit(str(e))

