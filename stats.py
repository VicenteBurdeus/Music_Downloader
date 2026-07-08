"""Music statistics viewer -- command-line tool.

Displays song count, total duration, and per-song durations for downloaded music.

Usage:
    python stats.py                  Analyze ./musica/
    python stats.py "my album"       Analyze ./my album/musica/
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TextColumn
from rich.table import Table

from core import album as album_mgr

console = Console()


def main():
    # Resolve album name
    album_name = None
    if len(sys.argv) > 1:
        album_name = sys.argv[1]

    if album_name:
        stats = album_mgr.get_song_stats(album_name)
    else:
        # Scan default musica/ folder
        SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
        output_dir = os.path.join(SCRIPT_DIR, "musica")
        if not os.path.isdir(output_dir):
            console.print("[red]No musica/ folder found[/]")
            return
        stats = _scan_folder(output_dir)

    count = stats["count"]
    total_sec = stats["total_duration"]
    total_dur = album_mgr.format_duration(total_sec)
    songs = stats["songs"]

    if count == 0:
        console.print("[yellow]No songs found[/]")
        return

    avg = total_sec / count if count else 0

    tb = Table.grid(padding=(0, 1))
    tb.add_column(width=5)
    tb.add_column(style="cyan")
    tb.add_column(style="dim", justify="right")

    tb.add_row("[bold]#[/]", "[bold]Song[/]", "[bold]Duration[/]")

    WINDOW = 20
    for i, song in enumerate(songs[:WINDOW]):
        tb.add_row(
            f"[dim]#{i + 1}[/]",
            song["name"],
            album_mgr.format_duration(song["duration"]),
        )

    if len(songs) > WINDOW:
        tb.add_row("", f"[dim]... and {len(songs) - WINDOW} more[/]", "")

    tb.add_row("", "", "")
    tb.add_row("", "[bold]Total songs:[/]", f"[bold green]{count}[/]")
    tb.add_row("", "[bold]Total duration:[/]", f"[bold green]{total_dur}[/]")
    tb.add_row("", "[bold]Average:[/]", f"[bold green]{album_mgr.format_duration(avg)}[/]")

    display_name = album_name or "Musica/"
    console.print(
        Panel(
            tb,
            title=f"[bold yellow]Statistics - {display_name}[/]",
            border_style="yellow",
            padding=(1, 2),
        )
    )


def _scan_folder(folder):
    """Scan a folder directly (used when no album mode)."""
    songs = []
    for f in os.listdir(folder):
        fpath = os.path.join(folder, f)
        if os.path.isfile(fpath):
            dur = album_mgr._get_duration(fpath)
            songs.append({"name": f, "path": fpath, "duration": dur})

    songs.sort(key=lambda x: x["duration"], reverse=True)
    total = sum(s["duration"] for s in songs)

    return {"count": len(songs), "total_duration": total, "songs": songs}


if __name__ == "__main__":
    main()
