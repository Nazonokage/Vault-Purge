from pathlib import Path
from typing import Annotated
import json

import typer
import uvicorn
from rich.console import Console
from rich.table import Table
from sqlmodel import Session, select

from image_dedup.api.settings import Settings
from image_dedup.core.grouper import group_images
from image_dedup.core.scanner import scan as scan_folder
from image_dedup.storage.database import open_database
from image_dedup.storage.models import ImageRecord

app = typer.Typer(no_args_is_help=True, help="Find duplicate and blurry images. Review locally; moves are manual.")
console = Console()


def show_report(engine, root=None, threshold=10):
    with Session(engine) as session:
        query = select(ImageRecord).where(ImageRecord.status == "active")
        if root:
            query = query.where(ImageRecord.root == str(root.resolve()))
        groups = group_images(session.exec(query).all(), threshold)
    table = Table("Kind", "Images", "Suggested keeper", "Reason")
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
        from image_dedup.api.server import create_app
        console.print("Open http://127.0.0.1:8000 in your browser")
        uvicorn.run(create_app(settings), host="127.0.0.1", port=8000)


@app.command()
def serve(database: Path | None = None, port: Annotated[int, typer.Option(min=1024, max=65535)] = 8000):
    """Open the local review server. You can start scans from its browser UI."""
    from image_dedup.api.server import create_app
    settings = Settings()
    if database:
        settings.database = database
    console.print(f"Open http://127.0.0.1:{port} in your browser")
    uvicorn.run(create_app(settings), host="127.0.0.1", port=port)


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
    app()
