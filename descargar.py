"""YouTube music downloader -- command-line version with Rich terminal UI.

Downloads audio from YouTube videos/playlists as high-quality MP3 files.
Supports per-album subfolders via command-line argument.

Usage:
    python descargar.py            Use ./urls.txt -> ./musica/
    python descargar.py "my album" Use ./my album/urls.txt -> ./my album/musica/
"""

import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn
from rich.table import Table
from rich.text import Text

from core import album as album_mgr
from core import downloader as dl

MAX_WORKERS = 3
MAX_RETRIES = 2

console = Console()


def build_panel(items, total, completed):
    tb = Table.grid(padding=(0, 1))
    tb.add_column(width=2)
    tb.add_column(width=13)
    tb.add_column()

    WINDOW = 12
    current = completed
    start = max(0, current - WINDOW // 2)
    end = min(len(items), start + WINDOW)

    pending = sum(1 for s, _ in items if s == "pending")
    errors = sum(1 for s, _ in items if s == "error")

    info_parts = []
    if pending:
        info_parts.append(f"[dim]{pending} pending[/]")
    if errors:
        info_parts.append(f"[red]{errors} failed[/]")
    info_extra = "  |  ".join(info_parts) if info_parts else ""

    tb.add_row("", f"[dim]{start + 1}-{end} / {len(items)}[/]  {info_extra}", "")

    for i in range(start, end):
        status, url = items[i]
        vid = dl.extract_id(url) or url[-11:]

        if status == "pending":
            icon = "[dim].[/]"
            style = "dim"
        elif status == "downloading":
            icon = "[yellow]>>[/]"
            style = "bold yellow"
        elif status == "skipped":
            icon = "[cyan]::[/]"
            style = "cyan"
        elif status == "done":
            icon = "[green]OK[/]"
            style = "green"
        else:
            icon = "[red]!![/]"
            style = "bold red"

        tb.add_row(icon, f"[{style}]{vid}[/]", "")

    if start > 0:
        tb.add_row("", f"[dim]... {start} above[/]", "")
    if end < len(items):
        tb.add_row("", f"[dim]... {len(items) - end} below[/]", "")

    progress = Progress(
        TextColumn("Progress"),
        BarColumn(bar_width=30, style="grey23", complete_style="green"),
        TextColumn("[bold]{task.completed}/{task.total}[/]"),
    )
    task = progress.add_task("", total=total)
    progress.update(task, completed=completed)

    tb.add_row("", progress)
    return tb


def main():
    # Resolve album paths
    album_name = None
    if len(sys.argv) > 1:
        album_name = sys.argv[1]
        album_mgr.create_album(album_name)
        paths = album_mgr.get_album_paths(album_name)
    else:
        SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
        paths = {
            "urls": os.path.join(SCRIPT_DIR, "urls.txt"),
            "archive": os.path.join(SCRIPT_DIR, "descargados.txt"),
            "output": os.path.join(SCRIPT_DIR, "musica"),
        }

    os.makedirs(paths["output"], exist_ok=True)

    title_prefix = f"[bold yellow]{album_name}[/] - " if album_name else ""
    with console.status(
        f"[bold yellow]{title_prefix}Extracting songs from playlists...[/]"
    ):

        if not os.path.isfile(paths["urls"]):
            console.print("[red]urls.txt is empty or not found[/]")
            return

        urls = album_mgr.read_urls(album_name) if album_name else _read_urls_raw(paths["urls"])

    if not urls:
        console.print("[red]urls.txt is empty[/]")
        return

    downloaded = set()
    if os.path.isfile(paths["archive"]):
        downloaded = album_mgr.get_downloaded_ids(album_name) if album_name else _read_archive_raw(paths["archive"])

    items = []
    for entry in urls:
        if entry[0] == "playlist":
            playlist_url = entry[1]
            limit = entry[2]
            vid_list = dl.resolve_playlist(playlist_url)
            for vid_info in vid_list[:limit] if limit else vid_list:
                vid = vid_info["id"]
                url = vid_info["url"]
                if vid in downloaded:
                    items.append(("skipped", url))
                else:
                    items.append(("pending", url))
        else:
            url = entry[1]
            vid = dl.extract_id(url)
            if vid and vid in downloaded:
                items.append(("skipped", url))
            else:
                items.append(("pending", url))

    total = len(items)
    completed = sum(1 for s, _ in items if s == "skipped")

    with Live(
        Panel("", title=f"[bold yellow]{album_name or 'Music'}[/]"),
        refresh_per_second=10,
        console=console,
        transient=False,
    ) as live:

        items_lock = threading.Lock()
        completed_ref = [completed]
        title_ref = [
            f"[bold yellow]{'Downloading ' + album_name if album_name else 'Downloading music'}[/]"
        ]

        def render():
            with items_lock:
                items_copy = list(items)
                comp = completed_ref[0]
            return Panel(
                build_panel(items_copy, total, comp),
                title=title_ref[0],
                border_style="yellow",
                padding=(0, 1),
            )

        live.update(render())

        def worker(idx, url, is_retry=False):
            try:
                with items_lock:
                    items[idx] = ("downloading", items[idx][1])
                live.update(render())

                ok = dl.download_video(url, paths["output"], paths["archive"])

                with items_lock:
                    items[idx] = ("done" if ok else "error", items[idx][1])
                    if not is_retry:
                        completed_ref[0] += 1
                live.update(render())
            except Exception:
                with items_lock:
                    items[idx] = ("error", items[idx][1])
                    if not is_retry:
                        completed_ref[0] += 1
                live.update(render())

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            pending = {}
            for i, (status, url) in enumerate(items):
                if status != "pending":
                    continue
                pending[executor.submit(worker, i, url)] = i

            for future in as_completed(pending):
                try:
                    future.result()
                except Exception:
                    pass

        for attempt in range(MAX_RETRIES):
            with items_lock:
                retry = [
                    (i, url) for i, (s, url) in enumerate(items) if s == "error"
                ]
            if not retry:
                break

            title_ref[0] = (
                f"[bold yellow]Retrying failures... ({attempt + 1}/{MAX_RETRIES})[/]"
            )
            live.update(render())

            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                retry_pending = {}
                for i, url in retry:
                    retry_pending[executor.submit(worker, i, url, True)] = i
                for future in as_completed(retry_pending):
                    try:
                        future.result()
                    except Exception:
                        pass

        color = "green" if completed_ref[0] == total else "yellow"
        live.update(
            Panel(
                build_panel(items, total, completed_ref[0]),
                title="[bold green]Complete![/]",
                border_style=color,
                padding=(0, 1),
            )
        )


def _read_urls_raw(filepath):
    """Read urls.txt directly (used when no album mode)."""
    urls = []
    with open(filepath, "r", encoding="utf-8") as f:
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


def _read_archive_raw(filepath):
    """Read descargados.txt directly (used when no album mode)."""
    ids = set()
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("youtube "):
                ids.add(line.split()[1])
    return ids


if __name__ == "__main__":
    main()
