"""Main GUI application for Music Downloader."""

import json
import os
import sys
import webbrowser
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSlider,
    QSplitter,
    QSpinBox,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core import album as album_mgr
from core import downloader as dl
from gui.workers import (
    DownloadWorker,
    PlaylistWorker,
    SearchWorker,
    StatsRefreshWorker,
    VideoInfoWorker,
)

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    HAS_MULTIMEDIA = True
except ImportError:
    HAS_MULTIMEDIA = False

SETTINGS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "settings.json",
)

DEFAULT_SETTINGS = {
    "format": "mp3",
    "quality": "0",
    "max_workers": 3,
    "embed_thumbnail": True,
    "albums_dir": "",
    "volume": 80,
    "album_order": [],
}


class MusicDownloader(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Music Downloader")
        self.resize(1100, 680)

        self._settings = self._load_settings()
        self._loaded_settings = dict(self._settings)  # snapshot for dirty check
        self._current_album = None
        self._queue = []         # list of dicts: title, url, status
        self._workers = []        # active worker references
        self._active_downloads = 0
        self._stats_cache = {}    # album_name -> stats dict

        global HAS_MULTIMEDIA
        if HAS_MULTIMEDIA:
            try:
                self._audio_output = QAudioOutput()
                self._media_player = QMediaPlayer()
                self._media_player.setAudioOutput(self._audio_output)
                self._media_player.playbackStateChanged.connect(self._on_playback_changed)
                self._media_player.mediaStatusChanged.connect(self._on_media_status_changed)
                self._audio_output.setVolume(self._settings.get("volume", 80) / 100)
            except Exception:
                HAS_MULTIMEDIA = False
                self._audio_output = None
                self._media_player = None
            self._current_playing = None
            self._play_buttons = {}   # filepath -> QPushButton
            self._playlist = []       # list of filepaths for play all
            self._playlist_index = -1

        self._setup_ui()
        self._load_albums()

        # Zoom
        self._zoom_level = 0
        self._base_font_size = QApplication.instance().font().pointSize()

        # Auto-select first album
        if self.sidebar_list.count() > 0:
            self.sidebar_list.setCurrentRow(0)

    # ── settings persistence ──────────────────────────────────────────

    def _load_settings(self):
        if os.path.isfile(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    settings = {**DEFAULT_SETTINGS, **json.load(f)}
            except Exception:
                settings = dict(DEFAULT_SETTINGS)
        else:
            settings = dict(DEFAULT_SETTINGS)

        if settings.get("albums_dir"):
            album_mgr.set_albums_dir(settings["albums_dir"])
        return settings

    def _save_settings(self):
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self._settings, f, indent=2)
        except Exception:
            pass

    # ── zoom ──────────────────────────────────────────────────────────

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self._zoom_level = min(self._zoom_level + 1, 10)
            elif delta < 0:
                self._zoom_level = max(self._zoom_level - 1, -5)
            self._apply_zoom()
            return
        super().wheelEvent(event)

    def _apply_zoom(self):
        font = QApplication.instance().font()
        new_size = self._base_font_size + self._zoom_level
        if new_size < 7:
            new_size = 7
        font.setPointSize(new_size)
        QApplication.instance().setFont(font)

    def closeEvent(self, event):
        if self._is_settings_dirty():
            msg = QMessageBox(self)
            msg.setWindowTitle("Unsaved Changes")
            msg.setText("You have unsaved changes in Settings.")
            msg.setInformativeText("Do you want to save them before closing?")
            msg.setStandardButtons(
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel
            )
            msg.setDefaultButton(QMessageBox.Save)
            msg.button(QMessageBox.Discard).setText("Discard")
            result = msg.exec()
            if result == QMessageBox.Save:
                self._on_save_settings()
                event.accept()
            elif result == QMessageBox.Discard:
                event.accept()
            else:
                event.ignore()
            return
        self._cleanup_threads()
        event.accept()

    def _cleanup_threads(self):
        """Stop any running workers gracefully."""
        if HAS_MULTIMEDIA and self._media_player:
            self._media_player.stop()
        for w in getattr(self, "_title_workers", []):
            if w.isRunning():
                w.terminate()
                w.wait(2000)
        for w in self._workers:
            if w.isRunning():
                w.terminate()
                w.wait(2000)

    def _is_settings_dirty(self):
        current = {
            "format": "mp4" if self.fmt_mp4.isChecked() else "mp3",
            "quality": str(self.quality_combo.currentIndex()),
            "max_workers": self.workers_spin.value(),
            "embed_thumbnail": self.embed_thumb.isChecked(),
            "volume": self.volume_slider.value(),
        }
        for key, val in current.items():
            if str(self._loaded_settings.get(key)) != str(val):
                return True
        return False

    # ── overall UI skeleton ───────────────────────────────────────────

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter)

        # Sidebar
        self.sidebar = self._build_sidebar()
        splitter.addWidget(self.sidebar)

        # Main tabs
        self.tabs = QTabWidget()
        self.search_tab = self._build_search_tab()
        self.downloads_tab = self._build_downloads_tab()
        self.stats_tab = self._build_stats_tab()
        self.settings_tab = self._build_settings_tab()

        self.tabs.addTab(self.search_tab, "Search")
        self.tabs.addTab(self.downloads_tab, "Downloads")
        self.tabs.addTab(self.stats_tab, "Stats")
        self.tabs.addTab(self.settings_tab, "Settings")
        self.tabs.currentChanged.connect(self._on_tab_changing)
        self._settings_tab_index = 3
        self._previous_tab_index = 0
        splitter.addWidget(self.tabs)

        splitter.setSizes([200, 880])

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_label = QLabel("Ready")
        self.status_bar.addWidget(self.status_label)

    def _on_tab_changing(self, new_index):
        old = self._previous_tab_index
        self._previous_tab_index = new_index
        if old == self._settings_tab_index and new_index != self._settings_tab_index:
            if self._is_settings_dirty():
                self.tabs.blockSignals(True)
                msg = QMessageBox(self)
                msg.setWindowTitle("Unsaved Changes")
                msg.setText("You have unsaved changes in Settings.")
                msg.setInformativeText("Do you want to save them before leaving?")
                msg.setStandardButtons(
                    QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel
                )
                msg.setDefaultButton(QMessageBox.Save)
                msg.button(QMessageBox.Discard).setText("Discard")
                result = msg.exec()
                if result == QMessageBox.Save:
                    self._on_save_settings()
                    self.tabs.setCurrentIndex(new_index)
                elif result == QMessageBox.Discard:
                    self.tabs.setCurrentIndex(new_index)
                else:
                    self.tabs.setCurrentIndex(old)
                self.tabs.blockSignals(False)

    # ── sidebar ───────────────────────────────────────────────────────

    def _build_sidebar(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)

        title = QLabel("<b>Albums</b>")
        layout.addWidget(title)

        self.sidebar_list = QListWidget()
        self.sidebar_list.setDragDropMode(QListWidget.InternalMove)
        self.sidebar_list.setDefaultDropAction(Qt.MoveAction)
        self.sidebar_list.currentRowChanged.connect(self._on_album_selected)
        self.sidebar_list.setContextMenuPolicy(Qt.ActionsContextMenu)

        delete_action = QAction("Delete", self)
        delete_action.triggered.connect(self._delete_album)
        self.sidebar_list.addAction(delete_action)

        rename_action = QAction("Rename", self)
        rename_action.triggered.connect(self._rename_album)
        self.sidebar_list.addAction(rename_action)

        layout.addWidget(self.sidebar_list)

        btn_row = QHBoxLayout()
        new_btn = QPushButton("+ New")
        new_btn.clicked.connect(self._create_album)
        btn_row.addWidget(new_btn)

        open_btn = QPushButton("Open Folder")
        open_btn.clicked.connect(self._open_album_folder)
        btn_row.addWidget(open_btn)
        layout.addLayout(btn_row)

        return widget

    # ── search tab ────────────────────────────────────────────────────

    def _build_search_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Search bar
        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search YouTube or paste a URL...")
        self.search_input.returnPressed.connect(self._on_search)
        search_row.addWidget(self.search_input)

        self.platform_combo = QComboBox()
        self.platform_combo.addItems(["YouTube"])
        search_row.addWidget(self.platform_combo)

        search_btn = QPushButton("Search")
        search_btn.clicked.connect(self._on_search)
        search_row.addWidget(search_btn)
        layout.addLayout(search_row)

        # Results table
        self.results_table = QTableWidget(0, 4)
        self.results_table.setHorizontalHeaderLabels(
            ["Title", "Channel", "Duration", "URL"]
        )
        self.results_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch
        )
        self.results_table.setColumnHidden(3, True)
        self.results_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results_table.doubleClicked.connect(self._on_result_double_click)
        self.results_table.setContextMenuPolicy(Qt.ActionsContextMenu)
        open_action = QAction("Open in Browser", self)
        open_action.triggered.connect(self._open_result_in_browser)
        self.results_table.addAction(open_action)
        layout.addWidget(self.results_table)

        # Action buttons
        btn_row = QHBoxLayout()
        add_selected_btn = QPushButton("Add Selected to Queue")
        add_selected_btn.clicked.connect(self._add_selected_to_queue)
        btn_row.addWidget(add_selected_btn)

        add_all_btn = QPushButton("Add All to Queue")
        add_all_btn.clicked.connect(self._add_all_to_queue)
        btn_row.addWidget(add_all_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # URL paste row
        paste_row = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Paste YouTube URL...")
        self.url_input.returnPressed.connect(self._on_paste_url)
        paste_row.addWidget(self.url_input)

        add_url_btn = QPushButton("Add URL")
        add_url_btn.clicked.connect(self._on_paste_url)
        paste_row.addWidget(add_url_btn)
        layout.addLayout(paste_row)

        return widget

    # ── downloads tab ─────────────────────────────────────────────────

    def _build_downloads_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Queue table
        self.queue_table = QTableWidget(0, 4)
        self.queue_table.setHorizontalHeaderLabels(
            ["", "Status", "Title", "URL"]
        )
        self.queue_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch
        )
        self.queue_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.queue_table.setColumnHidden(3, True)
        self.queue_table.setColumnWidth(0, 34)
        self.queue_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.queue_table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.queue_table)

        # Progress
        self.dl_progress = QProgressBar()
        self.dl_progress.setVisible(False)
        layout.addWidget(self.dl_progress)

        # Buttons
        btn_row = QHBoxLayout()
        dl_all_btn = QPushButton("Download All")
        dl_all_btn.clicked.connect(self._start_downloads)
        btn_row.addWidget(dl_all_btn)

        dl_sel_btn = QPushButton("Download Selected")
        dl_sel_btn.clicked.connect(self._download_selected)
        btn_row.addWidget(dl_sel_btn)

        remove_btn = QPushButton("Remove Selected")
        remove_btn.clicked.connect(self._remove_selected)
        btn_row.addWidget(remove_btn)

        clear_btn = QPushButton("Clear Completed")
        clear_btn.clicked.connect(self._clear_completed)
        btn_row.addWidget(clear_btn)

        retry_btn = QPushButton("Retry Failed")
        retry_btn.clicked.connect(self._retry_failed)
        btn_row.addWidget(retry_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        return widget

    # ── stats tab ─────────────────────────────────────────────────────

    def _build_stats_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.stats_summary = QLabel("Select an album to view statistics.")
        self.stats_summary.setStyleSheet("font-size: 14px; padding: 8px;")
        layout.addWidget(self.stats_summary)

        self.stats_table = QTableWidget(0, 4)
        self.stats_table.setHorizontalHeaderLabels(["", "Song", "Duration", ""])
        self.stats_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch
        )
        self.stats_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.stats_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
        self.stats_table.setColumnWidth(0, 34)
        self.stats_table.setColumnWidth(3, 34)
        self.stats_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.stats_table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.stats_table)

        controls_row = QHBoxLayout()
        self.play_all_btn = QPushButton("\u25b6 Play All")
        self.play_all_btn.clicked.connect(self._play_all)
        controls_row.addWidget(self.play_all_btn)

        self.shuffle_check = QCheckBox("Shuffle")
        controls_row.addWidget(self.shuffle_check)

        self.stop_btn = QPushButton("\u23f9 Stop")
        self.stop_btn.clicked.connect(self._stop_playback)
        self.stop_btn.setEnabled(False)
        controls_row.addWidget(self.stop_btn)

        self.next_btn = QPushButton("\u23ed Next")
        self.next_btn.clicked.connect(self._play_next)
        self.next_btn.setEnabled(False)
        controls_row.addWidget(self.next_btn)

        self.now_playing_label = QLabel("")
        self.now_playing_label.setStyleSheet("color: #4caf50; font-style: italic;")
        controls_row.addWidget(self.now_playing_label)

        controls_row.addStretch()

        refresh_btn = QPushButton("Refresh Stats")
        refresh_btn.clicked.connect(self._refresh_stats)
        controls_row.addWidget(refresh_btn)
        layout.addLayout(controls_row)

        return widget

    # ── settings tab ──────────────────────────────────────────────────

    def _build_settings_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Format group
        fmt_group = QGroupBox("Download Format")
        fmt_layout = QVBoxLayout(fmt_group)
        self.fmt_mp3 = QRadioButton("MP3 (audio only)")
        self.fmt_mp4 = QRadioButton("MP4 (video)")
        if self._settings["format"] == "mp4":
            self.fmt_mp4.setChecked(True)
        else:
            self.fmt_mp3.setChecked(True)
        fmt_layout.addWidget(self.fmt_mp3)
        fmt_layout.addWidget(self.fmt_mp4)
        layout.addWidget(fmt_group)

        # Quality group
        qual_group = QGroupBox("Audio Quality")
        qual_layout = QVBoxLayout(qual_group)
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(
            ["0 (best)", "1", "2", "3", "4", "5 (medium)", "6", "7", "8", "9 (worst)"]
        )
        self.quality_combo.setCurrentIndex(int(self._settings["quality"]))
        self.quality_combo.setEnabled(self.fmt_mp3.isChecked())
        qual_layout.addWidget(self.quality_combo)
        layout.addWidget(qual_group)

        # Thumbnail
        self.embed_thumb = QCheckBox("Embed thumbnail (MP3 only)")
        self.embed_thumb.setChecked(self._settings["embed_thumbnail"])
        self.fmt_mp3.toggled.connect(self.embed_thumb.setEnabled)
        self.fmt_mp3.toggled.connect(self.quality_combo.setEnabled)
        layout.addWidget(self.embed_thumb)

        # Workers
        workers_group = QGroupBox("Performance")
        workers_layout = QVBoxLayout(workers_group)
        workers_row = QHBoxLayout()
        workers_row.addWidget(QLabel("Max parallel downloads:"))
        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, 10)
        self.workers_spin.setValue(self._settings["max_workers"])
        workers_row.addWidget(self.workers_spin)
        workers_row.addStretch()
        workers_layout.addLayout(workers_row)
        layout.addWidget(workers_group)

        # Storage
        storage_group = QGroupBox("Storage")
        storage_layout = QVBoxLayout(storage_group)
        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("Albums folder:"))
        self.albums_dir_label = QLabel(
            self._settings.get("albums_dir") or album_mgr.get_albums_dir()
        )
        self.albums_dir_label.setStyleSheet("color: gray;")
        folder_row.addWidget(self.albums_dir_label, 1)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_albums_dir)
        folder_row.addWidget(browse_btn)
        storage_layout.addLayout(folder_row)
        layout.addWidget(storage_group)

        # Volume
        volume_group = QGroupBox("Volume")
        volume_layout = QHBoxLayout(volume_group)
        volume_layout.addWidget(QLabel("🔈"))
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(int(self._settings.get("volume", 80)))
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        volume_layout.addWidget(self.volume_slider)
        volume_layout.addWidget(QLabel("🔊"))
        layout.addWidget(volume_group)

        layout.addStretch()

        save_btn = QPushButton("Save Settings")
        save_btn.clicked.connect(self._on_save_settings)
        layout.addWidget(save_btn)

        return widget

    # ── album management ──────────────────────────────────────────────

    def _load_albums(self):
        self.sidebar_list.blockSignals(True)
        self.sidebar_list.clear()
        names = album_mgr.list_albums()
        saved_order = self._settings.get("album_order", [])
        # Sort: saved order first, then remaining alphabetically
        ordered = []
        for name in saved_order:
            if name in names:
                ordered.append(name)
                names.remove(name)
        ordered.extend(names)

        for name in ordered:
            item = QListWidgetItem(name)
            self.sidebar_list.addItem(item)
        self.sidebar_list.blockSignals(False)
        self._save_album_order()

        # Connect after initial load to avoid triggering during setup
        try:
            self.sidebar_list.model().rowsMoved.disconnect()
        except Exception:
            pass
        self.sidebar_list.model().rowsMoved.connect(self._save_album_order)

    def _save_album_order(self, *args):
        order = []
        for i in range(self.sidebar_list.count()):
            order.append(self.sidebar_list.item(i).text())
        self._settings["album_order"] = order
        self._save_settings()

    def _on_album_selected(self, row):
        if row < 0:
            return
        self._current_album = self.sidebar_list.item(row).text()
        self._load_queue()
        self._refresh_stats()
        self._update_status()

    def _create_album(self):
        from PySide6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(
            self, "New Album", "Album name:"
        )
        if ok and name.strip():
            name = name.strip()
            album_mgr.create_album(name)
            self._load_albums()
            for i in range(self.sidebar_list.count()):
                if self.sidebar_list.item(i).text() == name:
                    self.sidebar_list.setCurrentRow(i)
                    break

    def _delete_album(self):
        if not self._current_album:
            return
        reply = QMessageBox.question(
            self,
            "Delete Album",
            f'Delete album "{self._current_album}" and all its files?',
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            album_mgr.delete_album(self._current_album)
            self._current_album = None
            self._queue = []
            self._load_albums()
            self._refresh_queue_table()
            self._refresh_stats()
            self._update_status()

    def _rename_album(self):
        if not self._current_album:
            return
        from PySide6.QtWidgets import QInputDialog

        new_name, ok = QInputDialog.getText(
            self, "Rename Album", "New name:", text=self._current_album
        )
        if ok and new_name.strip() and new_name.strip() != self._current_album:
            album_mgr.rename_album(self._current_album, new_name.strip())
            self._load_albums()
            for i in range(self.sidebar_list.count()):
                if self.sidebar_list.item(i).text() == new_name.strip():
                    self.sidebar_list.setCurrentRow(i)
                    break

    def _open_album_folder(self):
        if self._current_album:
            album_mgr.open_folder(self._current_album)

    def _play_file(self, filepath):
        """Play/pause toggle: inline for audio, external for video."""
        ext = os.path.splitext(filepath)[1].lower()
        if not HAS_MULTIMEDIA or ext not in (".mp3", ".wav", ".ogg", ".flac", ".m4a"):
            os.startfile(filepath)
            return

        if self._current_playing == filepath:
            if self._media_player.playbackState() == QMediaPlayer.PlayingState:
                self._media_player.pause()
            else:
                self._media_player.play()
            return

        self._sync_playlist(filepath)
        self._media_player.setSource(QUrl.fromLocalFile(filepath))
        self._media_player.play()

    def _sync_playlist(self, filepath):
        """Ensure playlist context is set for the given filepath."""
        if filepath in self._playlist:
            self._playlist_index = self._playlist.index(filepath)
            return
        stats = self._stats_cache.get(self._current_album or "")
        if not stats:
            self._playlist = [filepath]
            self._playlist_index = 0
            return
        songs = [s["path"] for s in stats["songs"] if os.path.splitext(s["path"])[1].lower()
                 in (".mp3", ".wav", ".ogg", ".flac", ".m4a")]
        self._playlist = songs
        try:
            self._playlist_index = songs.index(filepath)
        except ValueError:
            self._playlist = [filepath]
            self._playlist_index = 0

    def _delete_song(self, filepath):
        name = os.path.basename(filepath)
        reply = QMessageBox.question(
            self, "Delete Song",
            f'Delete "{name}"?\nThis cannot be undone.',
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            os.remove(filepath)
            self.status_label.setText(f"Deleted: {name}")
        except OSError as e:
            self.status_label.setText(f"Error deleting: {e}")
        if self._current_album:
            self._stats_cache.pop(self._current_album, None)
        self._refresh_stats()

    def _on_playback_changed(self, state):
        """Update play/pause icons when playback state changes."""
        if self._current_playing and self._current_playing in self._play_buttons:
            old_btn = self._play_buttons[self._current_playing]
            old_btn.setText("\u25b6")

        if state == QMediaPlayer.PlayingState:
            self._current_playing = self._media_player.source().toLocalFile()
            self.stop_btn.setEnabled(True)
            self.next_btn.setEnabled(True)
            name = os.path.basename(self._current_playing)
            self.now_playing_label.setText(f"\u266b  {name}")
        elif state == QMediaPlayer.PausedState:
            self.stop_btn.setEnabled(True)
            self.next_btn.setEnabled(True)
        else:  # StoppedState
            self._current_playing = None
            self.stop_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
            self.now_playing_label.setText("")

        if self._current_playing and self._current_playing in self._play_buttons:
            btn = self._play_buttons[self._current_playing]
            if state == QMediaPlayer.PlayingState:
                btn.setText("\u23f8")   # pause symbol
            else:
                btn.setText("\u25b6")   # play symbol

    def _stop_playback(self):
        if HAS_MULTIMEDIA:
            self._media_player.stop()
            self._playlist = []
            self._playlist_index = -1
            self.now_playing_label.setText("")

    def _on_media_status_changed(self, status):
        if status == QMediaPlayer.EndOfMedia:
            self._play_next()

    def _play_all(self):
        if not self._current_album or not HAS_MULTIMEDIA:
            return
        stats = self._stats_cache.get(self._current_album)
        if not stats or not stats["songs"]:
            return
        import random
        songs = [s["path"] for s in stats["songs"] if os.path.splitext(s["path"])[1].lower()
                 in (".mp3", ".wav", ".ogg", ".flac", ".m4a")]
        if not songs:
            return
        if self.shuffle_check.isChecked():
            random.shuffle(songs)
        self._playlist = songs
        self._playlist_index = 0
        self._play_file(songs[0])

    def _play_next(self):
        if not self._playlist or self._playlist_index < 0:
            return
        self._playlist_index += 1
        if self._playlist_index >= len(self._playlist):
            self._playlist = []
            self._playlist_index = -1
            self.status_label.setText("Playback finished.")
            return
        self._play_file(self._playlist[self._playlist_index])

    # ── queue management ──────────────────────────────────────────────

    def _load_queue(self):
        if not self._current_album:
            self._queue = []
            self._refresh_queue_table()
            return

        downloaded = album_mgr.get_downloaded_ids(self._current_album, self._settings["format"])
        entries = album_mgr.read_urls(self._current_album)
        self._queue = []

        for entry in entries:
            if entry[0] == "playlist":
                self._queue.append({
                    "title": f"Playlist ({entry[2]} tracks)" if entry[2] else "Playlist",
                    "url": entry[1],
                    "status": "pending",
                    "is_playlist": True,
                    "limit": entry[2],
                })
            else:
                vid = dl.extract_id(entry[1])
                title = vid if vid else entry[1][:60]
                if vid and vid in downloaded:
                    status = "done"
                else:
                    status = "pending"
                self._queue.append({
                    "title": title,
                    "url": entry[1],
                    "status": status,
                    "is_playlist": False,
                    "limit": None,
                })

        self._refresh_queue_table()
        QTimer.singleShot(200, self._fetch_queue_titles)

    def _fetch_queue_titles(self):
        """Fetch real titles for queue items that only show video IDs."""
        if not hasattr(self, "_title_workers"):
            self._title_workers = []
        for i, item in enumerate(self._queue):
            if item["is_playlist"]:
                continue
            vid = dl.extract_id(item["url"])
            if vid and item["title"] == vid:
                worker = VideoInfoWorker(item["url"])
                worker.info_ready.connect(
                    lambda info, idx=i: self._on_queue_title_fetched(idx, info)
                )
                worker.finished.connect(lambda w=worker: self._title_workers.remove(w) if w in self._title_workers else None)
                self._title_workers.append(worker)
                worker.start()

    def _on_queue_title_fetched(self, index, info):
        if index < len(self._queue):
            self._queue[index]["title"] = info.get("title", self._queue[index]["title"])
            self._update_queue_row(index, self._queue[index])

    def _save_queue_urls(self):
        if not self._current_album:
            return
        urls = []
        for item in self._queue:
            if item["is_playlist"]:
                urls.append(("playlist", item["url"], item["limit"]))
            else:
                urls.append(("video", item["url"], None))
        album_mgr.write_urls(self._current_album, urls)

    def _refresh_queue_table(self):
        self.queue_table.setRowCount(0)
        for i, item in enumerate(self._queue):
            self.queue_table.insertRow(i)
            self._update_queue_row(i, item)

    def _update_queue_row(self, row, item):
        status_map = {
            "pending": "Pending",
            "downloading": "Downloading...",
            "done": "Done",
            "error": "Error",
        }
        status_text = status_map.get(item["status"], item["status"])

        # Play button (column 0)
        play_btn = QPushButton("\u25b6")
        play_btn.setFixedSize(28, 22)
        if item["status"] == "done":
            play_btn.setToolTip("Play in browser")
            play_btn.setStyleSheet("color: green; font-size: 10px;")
            play_btn.clicked.connect(
                lambda checked, url=item["url"]: webbrowser.open(url)
            )
        else:
            play_btn.setEnabled(False)
            play_btn.setStyleSheet("color: gray; font-size: 10px;")
        self.queue_table.setCellWidget(row, 0, play_btn)

        self.queue_table.setItem(row, 1, QTableWidgetItem(status_text))
        self.queue_table.setItem(row, 2, QTableWidgetItem(item["title"]))
        self.queue_table.setItem(row, 3, QTableWidgetItem(item["url"]))

    def _add_to_queue(self, info):
        """Add a search result or URL to the download queue."""
        if not self._current_album:
            QMessageBox.warning(
                self, "No Album", "Please select or create an album first."
            )
            return

        url = info["url"]
        title = info.get("title", url)

        # Check for duplicates
        for item in self._queue:
            if item["url"] == url and item["status"] in ("pending", "error"):
                return  # already in queue

        self._queue.append({
            "title": title,
            "url": url,
            "status": "pending",
            "is_playlist": False,
            "limit": None,
        })
        self._save_queue_urls()
        self._refresh_queue_table()
        self.tabs.setCurrentWidget(self.downloads_tab)
        self.status_label.setText(f"Added: {title}")

    def _on_result_double_click(self, index):
        row = index.row()
        url_item = self.results_table.item(row, 3)
        title_item = self.results_table.item(row, 0)
        if url_item:
            self._add_to_queue({
                "url": url_item.text(),
                "title": title_item.text() if title_item else url_item.text(),
            })

    def _add_selected_to_queue(self):
        for row in set(idx.row() for idx in self.results_table.selectedIndexes()):
            url_item = self.results_table.item(row, 3)
            title_item = self.results_table.item(row, 0)
            if url_item:
                self._add_to_queue({
                    "url": url_item.text(),
                    "title": title_item.text() if title_item else url_item.text(),
                })

    def _add_all_to_queue(self):
        for row in range(self.results_table.rowCount()):
            url_item = self.results_table.item(row, 3)
            title_item = self.results_table.item(row, 0)
            if url_item:
                self._add_to_queue({
                    "url": url_item.text(),
                    "title": title_item.text() if title_item else url_item.text(),
                })

    def _remove_selected(self):
        rows = sorted(
            set(idx.row() for idx in self.queue_table.selectedIndexes()),
            reverse=True,
        )
        for row in rows:
            if row < len(self._queue) and self._queue[row]["status"] != "downloading":
                del self._queue[row]
        self._save_queue_urls()
        self._refresh_queue_table()

    def _clear_completed(self):
        self._queue = [item for item in self._queue if item["status"] != "done"]
        self._save_queue_urls()
        self._refresh_queue_table()

    # ── search ────────────────────────────────────────────────────────

    def _on_search(self):
        query = self.search_input.text().strip()
        if not query:
            return

        # Detect if it's a URL
        if query.startswith("http://") or query.startswith("https://"):
            self._on_paste_url_given(query)
            return

        if self.platform_combo.currentText().startswith("YouTube"):
            self.status_label.setText(f"Searching: {query}")
            self.worker = SearchWorker(query, limit=15)
            self.worker.results_ready.connect(self._on_search_results)
            self.worker.error.connect(
                lambda e: self.status_label.setText(f"Search error: {e}")
            )
            self.worker.start()

    def _on_search_results(self, results):
        self.results_table.setRowCount(0)
        for i, info in enumerate(results):
            self.results_table.insertRow(i)
            title = info.get("title", "Unknown")
            channel = info.get("channel", "Unknown")
            dur = album_mgr.format_duration(info.get("duration", 0))
            url = info.get("url", "")

            self.results_table.setItem(i, 0, QTableWidgetItem(title))
            self.results_table.setItem(i, 1, QTableWidgetItem(channel))
            self.results_table.setItem(i, 2, QTableWidgetItem(dur))
            self.results_table.setItem(i, 3, QTableWidgetItem(url))

        self.status_label.setText(f"Found {len(results)} results")
        self.tabs.setCurrentWidget(self.search_tab)

    def _open_result_in_browser(self):
        for idx in self.results_table.selectedIndexes():
            if idx.column() == 3:
                webbrowser.open(idx.data())
                return
        # fallback: check row 0 and get URL from column 3
        rows = set(idx.row() for idx in self.results_table.selectedIndexes())
        for row in rows:
            url_item = self.results_table.item(row, 3)
            if url_item:
                webbrowser.open(url_item.text())

    # ── URL handling ──────────────────────────────────────────────────

    def _on_paste_url(self):
        url = self.url_input.text().strip()
        if url:
            self._on_paste_url_given(url)
            self.url_input.clear()

    def _on_paste_url_given(self, url):
        if "playlist" in url or "list=" in url:
            from PySide6.QtWidgets import QInputDialog

            limit_text, ok = QInputDialog.getText(
                self, "Playlist Limit",
                "How many tracks from this playlist? (0 = all):",
                text="25",
            )
            if not ok:
                return
            try:
                limit_val = int(limit_text) if int(limit_text) > 0 else None
            except ValueError:
                limit_val = 25

            self.status_label.setText("Resolving playlist...")
            self.playlist_worker = PlaylistWorker(url, limit_val)
            self.playlist_worker.entries_ready.connect(self._on_playlist_resolved)
            self.playlist_worker.error.connect(
                lambda e: self.status_label.setText(f"Error: {e}")
            )
            self.playlist_worker.start()
        else:
            self.status_label.setText("Fetching video info...")
            self.video_worker = VideoInfoWorker(url)
            self.video_worker.info_ready.connect(
                lambda info: self._add_to_queue(info)
            )
            self.video_worker.error.connect(
                lambda e: self.status_label.setText(f"Error: {e}")
            )
            self.video_worker.start()

    def _on_playlist_resolved(self, entries):
        count = len(entries)
        for entry in entries:
            self._add_to_queue(entry)
        self.status_label.setText(f"Added {count} videos from playlist")

    # ── downloads ─────────────────────────────────────────────────────

    def _start_downloads(self):
        if not self._current_album:
            QMessageBox.warning(self, "No Album", "Select an album first.")
            return
        self._download_all_pending()

    def _download_selected(self):
        rows = set(idx.row() for idx in self.queue_table.selectedIndexes())
        if not rows:
            return
        for row in rows:
            if row < len(self._queue) and self._queue[row]["status"] == "pending":
                self._start_single_download(row)

    def _download_all_pending(self):
        paths = album_mgr.get_album_paths(self._current_album, self._settings["format"])
        os.makedirs(paths["output"], exist_ok=True)

        self.dl_progress.setVisible(True)
        self.dl_progress.setMaximum(len(self._queue))
        self.dl_progress.setValue(0)

        pending = [
            (i, item) for i, item in enumerate(self._queue)
            if item["status"] == "pending"
        ]
        if not pending:
            self.status_label.setText("Nothing to download.")
            self.dl_progress.setVisible(False)
            return

        self._active_downloads = 0
        max_workers = self._settings["max_workers"]
        self._pending_indices = iter(pending)
        self._completed_count = 0
        self._total_pending = len(pending)

        # Start initial batch
        for _ in range(min(max_workers, self._total_pending)):
            self._start_next_download()

    def _start_next_download(self):
        try:
            i, item = next(self._pending_indices)
        except StopIteration:
            if self._active_downloads == 0:
                self._on_all_downloads_finished()
            return

        paths = album_mgr.get_album_paths(self._current_album, self._settings["format"])
        worker = DownloadWorker(
            i, item["url"], paths["output"], paths["archive"],
            self._settings["format"],
            self._settings["quality"],
            self._settings["embed_thumbnail"],
        )
        worker.finished.connect(self._on_download_finished)
        self._workers.append(worker)
        self._active_downloads += 1

        item["status"] = "downloading"
        self._update_queue_row(i, item)
        self.status_label.setText(f"Downloading: {item['title']}")

        worker.start()

    def _on_download_finished(self, index, success):
        self._active_downloads -= 1
        self._completed_count += 1
        self.dl_progress.setValue(self._completed_count)

        if index < len(self._queue):
            self._queue[index]["status"] = "done" if success else "error"
            self._update_queue_row(index, self._queue[index])

        self._save_queue_urls()

        if success:
            self.status_label.setText(
                f"Completed {self._completed_count}/{self._total_pending}"
            )
        else:
            self.status_label.setText(
                f"Error on item #{index + 1}. Retrying later..."
            )

        self._start_next_download()

        # Invalidate stats cache and refresh periodically
        if self._current_album:
            self._stats_cache.pop(self._current_album, None)
        if self._completed_count % 3 == 0:
            QTimer.singleShot(500, self._refresh_stats)

    def _on_all_downloads_finished(self):
        self.dl_progress.setVisible(False)
        self._save_queue_urls()
        self._refresh_stats()

        errors = sum(1 for item in self._queue if item["status"] == "error")
        done = sum(1 for item in self._queue if item["status"] == "done")
        self.status_label.setText(
            f"Done: {done} completed"
            + (f", {errors} failed" if errors else "")
        )

    def _retry_failed(self):
        for item in self._queue:
            if item["status"] == "error":
                item["status"] = "pending"
        self._refresh_queue_table()
        self._save_queue_urls()
        self._download_all_pending()

    # ── stats ─────────────────────────────────────────────────────────

    def _refresh_stats(self):
        if not self._current_album:
            self.stats_summary.setText("Select an album to view statistics.")
            self.stats_table.setRowCount(0)
            return

        # Show cached stats immediately if available
        cached = self._stats_cache.get(self._current_album)
        if cached:
            self._display_stats(self._current_album, cached)
        else:
            self.stats_summary.setText("Calculating statistics...")

        self.stats_worker = StatsRefreshWorker(self._current_album)
        self.stats_worker.stats_ready.connect(
            lambda stats: self._on_stats_ready(self._current_album, stats)
        )
        self.stats_worker.error.connect(
            lambda e: self.stats_summary.setText(f"Error: {e}")
        )
        self.stats_worker.start()

    def _on_stats_ready(self, album_name, stats):
        self._stats_cache[album_name] = stats
        if self._current_album == album_name:
            self._display_stats(album_name, stats)
            self._update_status()

    def _display_stats(self, album_name, stats):
        count = stats["count"]
        total_dur = album_mgr.format_duration(stats["total_duration"])

        summary = (
            f"<b>{album_name}</b><br>"
            f"Songs: {count} &nbsp;|&nbsp; "
            f"Total duration: {total_dur}"
        )
        if count > 0:
            avg = stats["total_duration"] / count
            summary += f" &nbsp;|&nbsp; Average: {album_mgr.format_duration(avg)}"
        self.stats_summary.setText(summary)

        if HAS_MULTIMEDIA:
            self._play_buttons.clear()

        self.stats_table.setRowCount(0)
        for i, song in enumerate(stats["songs"]):
            self.stats_table.insertRow(i)

            play_btn = QPushButton("\u25b6")
            play_btn.setFixedSize(28, 22)
            play_btn.setToolTip("Play")
            play_btn.setStyleSheet("color: green; font-size: 10px;")
            filepath = song["path"]
            play_btn.clicked.connect(
                lambda checked, p=filepath: self._play_file(p)
            )
            if HAS_MULTIMEDIA:
                self._play_buttons[filepath] = play_btn
            self.stats_table.setCellWidget(i, 0, play_btn)

            self.stats_table.setItem(i, 1, QTableWidgetItem(song["name"]))
            dur_str = album_mgr.format_duration(song["duration"]) if song["duration"] else "--"
            self.stats_table.setItem(i, 2, QTableWidgetItem(dur_str))

            del_btn = QPushButton("\u2715")
            del_btn.setFixedSize(28, 22)
            del_btn.setToolTip("Delete song")
            del_btn.setStyleSheet("color: red; font-size: 12px;")
            del_btn.clicked.connect(
                lambda checked, p=filepath: self._delete_song(p)
            )
            self.stats_table.setCellWidget(i, 3, del_btn)

    def _update_status(self):
        if self._current_album:
            cached = self._stats_cache.get(self._current_album, {})
            count = cached.get("count", "?")
            self.status_label.setText(
                f"Album: {self._current_album} | Songs: {count}"
            )

    # ── settings ──────────────────────────────────────────────────────

    def _browse_albums_dir(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select Albums Folder", self.albums_dir_label.text()
        )
        if folder:
            self.albums_dir_label.setText(folder)
            self._settings["albums_dir"] = folder
            album_mgr.set_albums_dir(folder)
            self._save_settings()
            self._load_albums()
            if self.sidebar_list.count() > 0:
                self.sidebar_list.setCurrentRow(0)
            self.status_label.setText(f"Albums folder: {folder}")

    def _on_volume_changed(self, value):
        self._settings["volume"] = value
        if HAS_MULTIMEDIA:
            self._audio_output.setVolume(value / 100)

    def _on_save_settings(self):
        self._settings["format"] = "mp4" if self.fmt_mp4.isChecked() else "mp3"
        self._settings["quality"] = str(self.quality_combo.currentIndex())
        self._settings["max_workers"] = self.workers_spin.value()
        self._settings["embed_thumbnail"] = self.embed_thumb.isChecked()
        self._save_settings()
        self._loaded_settings = dict(self._settings)
        self.status_label.setText("Settings saved.")


def run():
    """Launch the GUI application."""
    app = QApplication(sys.argv)
    app.setApplicationName("Music Downloader")
    window = MusicDownloader()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run()
