from pathlib import Path
from typing import Annotated
import json

import typer
from rich.console import Console
from rich.table import Table
from sqlmodel import Session, select

from vault_purge.api.settings import DEFAULT_PORT, Settings
from vault_purge.api.runtime import run_server
from vault_purge.core.grouper import group_images
from vault_purge.core.scanner import scan as scan_folder
from vault_purge.storage.database import open_database
from vault_purge.storage.models import ImageRecord

app = typer.Typer(no_args_is_help=True, help="Find duplicate images, videos, and audio. Moves are manual.")
console = Console()


def show_report(engine, root=None, threshold=10):
    with Session(engine) as session:
        query = select(ImageRecord).where(ImageRecord.status == "active")
        if root:
            query = query.where(ImageRecord.root == str(root.resolve()))
        groups = group_images(session.exec(query).all(), threshold)
    table = Table("Kind", "Files", "Suggested keeper", "Reason")
    for group in groups:
        winner = next(r for r in group["members"] if r.id == group["recommendation"]["id"])
        table.add_row(group["kind"], str(len(group["members"])), winner.path, group["recommendation"]["reason"])
    console.print(table)
    return groups


@app.command()
def scan(path: Annotated[Path, typer.Option(exists=True, file_okay=False, help="Folder to inspect")],
         database: Path | None = None,
         max_workers: Annotated[int | None, typer.Option(min=1, max=61)] = None,
         classify_only: bool = False, recursive: bool = True, force: bool = False,
         serve: bool = False):
    """Scan and report without moving any files. Optionally launch the GUI."""
    settings = Settings()
    if database:
        settings.database = database
    if max_workers:
        settings.workers = max_workers
    engine = open_database(settings.database)
    try:
        with console.status("Inspecting images…") as status:
            result = scan_folder(path, engine, settings.workers, classify_only, recursive, force,
                                 lambda stats: status.update(f"Analyzed {stats['analyzed']} · cached {stats['cached']} · errors {stats['errors']}"))
        console.print(result)
        show_report(engine, path, settings.phash_threshold)
    finally:
        engine.dispose()
    if serve:
        from vault_purge.api.server import create_app
        console.print(f"Open http://127.0.0.1:{DEFAULT_PORT} in your browser")
        run_server(create_app(settings), settings, DEFAULT_PORT)


@app.command()
def serve(database: Path | None = None, port: Annotated[int, typer.Option(min=1024, max=65535)] = DEFAULT_PORT,
          open_browser: bool = True):
    """Open the local review server. You can start scans from its browser UI."""
    import threading
    import webbrowser
    from vault_purge.api.server import create_app
    settings = Settings()
    if database:
        settings.database = database
    url = f"http://127.0.0.1:{port}"
    console.print(f"Open [bold green]{url}[/bold green] in your browser")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    run_server(create_app(settings), settings, port)


@app.command()
def report(database: Path | None = None, path: Path | None = None, output: Path | None = None):
    """Show cached duplicate groups; optionally export JSON."""
    settings = Settings()
    engine = open_database(database or settings.database)
    try:
        groups = show_report(engine, path, settings.phash_threshold)
        if output:
            output.write_text(json.dumps([{**g, "members": [r.model_dump() for r in g["members"]]} for g in groups], indent=2), encoding="utf-8")
            console.print(f"Saved {output}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    from multiprocessing import freeze_support
    freeze_support()
    import sys
    if len(sys.argv) == 1:
        serve()
    else:
        app()

