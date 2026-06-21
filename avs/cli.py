import signal
import threading

import typer
from rich.console import Console

from avs.engine import pipeline as engine
from avs.models.db import init_db

_current_session_id: str | None = None


def _sigint_handler(sig, frame):
    if _current_session_id:
        engine.cancel_current(_current_session_id)
    raise KeyboardInterrupt


signal.signal(signal.SIGINT, _sigint_handler)

app = typer.Typer(
    name="avs",
    help="Action camera footage editing tool.",
    no_args_is_help=True,
)
console = Console()


def _make_rich_handler(cons: "Console"):
    """Return an on_event callback that renders pipeline events as rich progress."""
    from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[bold]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=cons,
        transient=True,
    )
    _tasks: dict[tuple, int] = {}  # (clip_id, stage) -> rich task id
    _started = [False]

    def on_event(clip_id, stage, status, message, completed, total):
        if not _started[0]:
            progress.start()
            _started[0] = True

        if message:
            cons.log(message)

        if clip_id is None:
            if stage == 'session' and status == 'done':
                progress.stop()
            return  # session-level events: message already logged above

        key = (clip_id, stage)
        if status == 'running':
            task_id = progress.add_task(f"  {stage}", total=total or 100)
            _tasks[key] = task_id
        elif status == 'progress' and key in _tasks:
            progress.update(_tasks[key], completed=completed or 0)
        elif status in ('done', 'skipped') and key in _tasks:
            progress.update(_tasks[key], completed=total or 100)
            progress.remove_task(_tasks.pop(key))

    return on_event


def _startup() -> None:
    init_db()


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


@app.command()
def ingest(
    path: str = typer.Argument(..., help="Path to SD card, folder, or a single video file"),
    sport: str = typer.Option(..., "--sport", "-s", help="Sport type (mtb, surf, ski, skydive, moto, trail, cycling)"),
) -> None:
    """Scan a folder or SD card and create a new session."""
    _startup()
    from pathlib import Path

    source = Path(path)
    if not source.exists():
        console.print(f"[red]Path not found:[/red] {path}")
        raise typer.Exit(1)

    console.print(f"[bold]Scanning[/bold] {source} …")
    session = engine.ingest_folder(source, sport=sport)
    console.print(f"[green]Session created:[/green] {session.id}")
    console.print(f"  Camera : {session.camera or 'unknown'}")
    console.print(f"  Clips  : {session.total_clips}")
    console.print(f"  Duration: {session.total_duration_s:.0f}s")
    console.print(f"\nNext step: [bold]avs analyze {session.id}[/bold]")


def _wait(token, label: str) -> None:
    """Block until token completes; exit on error."""
    error = token.wait()
    if error:
        console.print(f"[red]{label} failed:[/red] {error}")
        raise typer.Exit(1)


@app.command()
def analyze(
    session_id: str = typer.Argument(..., help="Session ID returned by ingest"),
    jpg: bool = typer.Option(False, "--jpg", help="Motion via JPEG extraction (faster, adds jpg marks)"),
    proxy: bool = typer.Option(False, "--proxy", help="Force recompute proxy-based motion"),
) -> None:
    """Run the full analysis pipeline on an imported session."""
    _startup()
    global _current_session_id
    method = "jpg" if jpg else "proxy"
    on_prog = _make_rich_handler(console)
    console.print(f"[bold]Analyzing session[/bold] {session_id} … (motion: {method})")
    console.print("[dim]Ctrl-C to cancel[/dim]")
    _current_session_id = session_id
    try:
        _wait(engine.run_proxy(session_id, on_progress=on_prog, on_done=None), "Proxy")
        _wait(engine.run_scan(session_id, method, on_progress=on_prog, on_done=None), "Scan")
        _wait(engine.run_peaks(session_id, method, on_progress=on_prog, on_done=None), "Peaks")
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled.[/yellow]")
        raise typer.Exit(0)
    finally:
        _current_session_id = None
    console.print(f"\nNext step: [bold]avs review {session_id}[/bold]")


@app.command()
def review(
    session_id: str = typer.Argument(..., help="Session ID to review"),
) -> None:
    """Open candidate clip review in the browser (static HTML)."""
    _startup()
    from avs.processing.review import open_review

    console.print(f"[bold]Opening review for session[/bold] {session_id} …")
    open_review(session_id, console=console)
    console.print(f"\nNext step: [bold]avs assemble {session_id}[/bold]")


@app.command()
def assemble(
    session_id: str = typer.Argument(..., help="Session ID to assemble"),
    source: str | None = typer.Option(None, "--source", help="Mark source to use: proxy, jpg, telemetry (default: all)"),
) -> None:
    """Assemble accepted marks into a preview video."""
    _startup()
    console.print(f"[bold]Assembling session[/bold] {session_id} …")
    _wait(
        engine.run_assemble(session_id, grade=None, source_filter=source,
                            remove_mark_ids=[], swap_music=False, disable_overlay=False,
                            on_progress=None, on_done=None),
        "Assemble",
    )
    console.print(f"\nNext step: [bold]avs export {session_id}[/bold]")


@app.command()
def refine(
    session_id: str = typer.Argument(..., help="Session ID to refine"),
    remove: list[str] = typer.Option([], "--remove", help="Mark ID to remove"),
    swap_music: bool = typer.Option(False, "--swap-music", help="Use next music track"),
    grade: str | None = typer.Option(None, "--grade", help="Color grade: punchy, cinematic, natural, warm, cool, vibrant"),
    no_overlay: bool = typer.Option(False, "--no-overlay", help="Disable telemetry overlays"),
    source: str | None = typer.Option(None, "--source", help="Mark source to use: proxy, jpg, telemetry (default: all)"),
) -> None:
    """Re-assemble with adjustments (remove clips, swap music, change grade)."""
    _startup()
    console.print(f"[bold]Refining session[/bold] {session_id} …")
    _wait(
        engine.run_assemble(session_id, grade=grade, source_filter=source,
                            remove_mark_ids=list(remove), swap_music=swap_music,
                            disable_overlay=no_overlay, on_progress=None, on_done=None),
        "Refine",
    )


@app.command()
def export(
    session_id: str = typer.Argument(..., help="Session ID to export"),
    aspect: list[str] = typer.Option(["16:9"], "--aspect", "-a", help="Aspect ratio(s): 16:9 and/or 9:16"),
) -> None:
    """Export the approved preview to final output files."""
    _startup()
    console.print(f"[bold]Exporting session[/bold] {session_id} …")
    _wait(
        engine.run_export(session_id, aspects=list(aspect), output_dir=None,
                          on_progress=None, on_done=None),
        "Export",
    )


@app.command()
def sessions(
    status: str | None = typer.Option(None, "--status", help="Filter by status"),
) -> None:
    """List all sessions."""
    _startup()
    from rich.table import Table
    from avs.models.db import get_session as db_session
    from avs.models.schema import Session as SessionModel

    with db_session() as s:
        q = s.query(SessionModel)
        if status:
            q = q.filter(SessionModel.status == status)
        rows = q.order_by(SessionModel.created_at.desc()).all()

    table = Table(title="Sessions")
    table.add_column("ID", style="dim")
    table.add_column("Date")
    table.add_column("Sport")
    table.add_column("Camera")
    table.add_column("Clips")
    table.add_column("Status")

    for r in rows:
        table.add_row(
            r.id[:8],
            r.created_at.strftime("%Y-%m-%d %H:%M"),
            r.sport or "—",
            r.camera or "—",
            str(r.total_clips or "—"),
            r.status,
        )
    console.print(table)


@app.command()
def ui(
    port: int = typer.Option(8765, "--port", help="Port for the local web server"),
) -> None:
    """Launch the aVs desktop UI."""
    _startup()
    from avs.ui.app import start
    start(port=port)


@app.command()
def profile(
    sport: str = typer.Argument(..., help="Sport to show or update"),
    grade: str | None = typer.Option(None, "--grade", help="Set color grade"),
    music_energy: str | None = typer.Option(None, "--music-energy", help="Set music energy: high, medium, chill"),
) -> None:
    """Show or update a sport profile."""
    _startup()
    from avs.models.db import get_session as db_session
    from avs.models.schema import Profile
    from avs.presets.sports import DEFAULT_PROFILES
    from datetime import datetime

    with db_session() as s:
        p = s.query(Profile).filter(Profile.sport == sport).first()
        if p is None:
            if sport not in DEFAULT_PROFILES:
                console.print(f"[red]Unknown sport:[/red] {sport}")
                raise typer.Exit(1)
            defaults = DEFAULT_PROFILES[sport]
            p = Profile(sport=sport, **defaults)
            s.add(p)

        if grade:
            p.color_grade = grade
            p.updated_at = datetime.utcnow()
        if music_energy:
            p.music_energy = music_energy
            p.updated_at = datetime.utcnow()

        console.print(f"[bold]Profile:[/bold] {sport}")
        console.print(f"  Color grade  : {p.color_grade}")
        console.print(f"  Music energy : {p.music_energy}")
        console.print(f"  YT duration  : {p.target_duration_youtube_s}s")
        console.print(f"  Overlays     : speed={p.overlay_speed} altitude={p.overlay_altitude}")
