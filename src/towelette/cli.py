"""Typer CLI -- towelette init, serve, refresh, status, tune, add, remove, reset."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console

from towelette.config import find_towelette_dir, init_towelette_dir, load_config
from towelette.discover import discover_deps

app = typer.Typer(
    name="towelette",
    help="A tiny RAG to wipe away API hallucinations. Indexes niche Python libraries into a local vector DB and serves them via MCP so your coding assistant stops hallucinating APIs. Run `towelette init` in your project to get started.",
)
console = Console()


def _resolve_path(path: Optional[str]) -> Path:
    """Resolve project path, defaulting to cwd."""
    return Path(path).resolve() if path else Path.cwd()


@app.command()
def init(
    path: Optional[str] = typer.Argument(None, help="Project root (defaults to cwd)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Index all scouted libraries without confirmation"),
    skip_scouts: bool = typer.Option(False, "--skip-scouts", help="Skip scout dispatch (discovery only)"),
    only: Optional[str] = typer.Option(None, "--only", help="Comma-separated list of libraries to index (e.g. --only trimesh,open3d,libigl)"),
    report_only: bool = typer.Option(True, "--report/--no-report", help="Print scout report and exit without indexing (default: True)"),
):
    """Discover dependencies, analyze each library, and build a searchable RAG index.

    Scans pyproject.toml / requirements.txt / environment.yml for dependencies, skips
    well-known libraries (numpy, pandas, etc.), dispatches Claude subagents to investigate
    each remaining library, then pauses to review scout findings before indexing. Pass
    --yes to skip confirmation and index everything automatically.
    """
    project_root = _resolve_path(path)
    console.print(f"\n[bold]Scanning project dependencies in {project_root}...[/bold]\n")

    # Step 1: Init .towelette dir
    towelette_dir = init_towelette_dir(project_root)

    # Step 2: Run discovery
    from towelette.config import get_user_skiplist
    user_skiplist = get_user_skiplist(towelette_dir)
    result = discover_deps(project_root, user_skiplist=user_skiplist)

    if result.dep_files_found:
        console.print(f"Found: {', '.join(result.dep_files_found)}\n")

    if result.candidates:
        console.print("[bold]Candidates for indexing:[/bold]")
        for c in result.candidates:
            version_str = f" ({c.version})" if c.version else ""
            import_str = f" -- {c.import_count} imports" if c.import_count else ""
            console.print(f"  - {c.name}{version_str}{import_str}")
    else:
        console.print("[yellow]No candidates found for indexing.[/yellow]")

    if result.skipped:
        console.print(f"\n[dim]Skipped (well-known): {', '.join(result.skipped)}[/dim]")

    # Step 3: Index project source
    from towelette.orchestrator import add_to_gitignore, index_project, write_mcp_config

    console.print("\n[bold]Indexing project source...[/bold]")
    project_chunks = index_project(project_root, towelette_dir)
    console.print(f"  ok  project (local) -- {project_chunks} chunks")

    # Step 4: Write MCP config
    write_mcp_config(project_root)
    console.print("\n[green]MCP config written to .mcp.json and .claude/settings.json[/green]")

    # Step 5: Update .gitignore
    add_to_gitignore(project_root)

    if not result.candidates:
        console.print("\n[green]Done. No libraries to scout.[/green]")
        return

    # Step 6: Resolve repo URLs and dispatch scouts
    from towelette.orchestrator import index_from_reports, load_cached_reports, run_scouts
    from towelette.scout import format_scout_summary

    cached = load_cached_reports(towelette_dir)
    cached_names = [c.name for c in result.candidates
                    if c.name.lower().replace("-", "_") in cached
                    and not cached[c.name.lower().replace("-", "_")].error]
    new_names = [c.name for c in result.candidates
                 if c.name.lower().replace("-", "_") not in cached
                 or cached[c.name.lower().replace("-", "_")].error]

    all_cached = not new_names
    if skip_scouts or all_cached:
        if all_cached and not skip_scouts:
            console.print("\n[dim]All scout reports cached — skipping dispatch.[/dim]")
        elif skip_scouts:
            console.print("\n[dim]Scouts skipped (--skip-scouts).[/dim]")
        reports = list(cached.values())
    else:
        if cached_names:
            console.print(f"\n[dim]Reusing cached reports: {', '.join(cached_names)}[/dim]")
        console.print(f"\n[bold]Dispatching scouts for: {', '.join(new_names)}...[/bold]")
        reports = run_scouts(towelette_dir, result.candidates)

    # Show scout summary
    summary = format_scout_summary(reports)
    console.print(f"\n{summary}\n")

    if report_only:
        console.print("[dim]--report: exiting before indexing. Re-run with --no-report --only <libs> to index.[/dim]")
        return

    # Count valid reports
    valid_reports = [r for r in reports if not r.error]
    if not valid_reports:
        console.print("[yellow]No libraries could be scouted successfully.[/yellow]")
        return

    # Filter to --only set if specified
    if only:
        only_set = {name.strip().lower().replace("-", "_") for name in only.split(",")}
        valid_reports = [r for r in valid_reports if r.library.lower().replace("-", "_") in only_set]

    # Pause and confirm per library unless --yes was passed
    if not yes and not only:
        console.print("\n[bold]Review each library before indexing:[/bold]\n")
        confirmed = []
        for report in valid_reports:
            version_str = f" ({report.version})" if report.version else ""
            console.print(f"[bold]{report.library}{version_str}[/bold]")
            console.print(f"  Strategy : {report.strategy}")
            if report.estimated_chunks:
                console.print(f"  Est. size: ~{report.estimated_chunks} chunks")
            if report.source_paths:
                console.print(f"  Paths    : {', '.join(report.source_paths)}")
            if report.notes:
                console.print(f"  Notes    : {report.notes}")
            if report.upstream_dependencies:
                for ud in report.upstream_dependencies:
                    tag = " [recommended]" if ud.recommended else ""
                    console.print(f"  Depends on: {ud.library} ({ud.significance} significance){tag}")
            if typer.confirm(f"\nIndex {report.library}?", default=True):
                confirmed.append(report)
            console.print()
        valid_reports = confirmed

    if not valid_reports:
        console.print("[yellow]No libraries selected for indexing.[/yellow]")
        return

    # Step 7: Index libraries from reports
    console.print(f"\n[bold]Indexing {len(valid_reports)} libraries...[/bold]")
    index_results = index_from_reports(towelette_dir, valid_reports)
    for lib, count in index_results.items():
        if count == 0:
            console.print(f"  [yellow]warn[/yellow]  {lib} -- 0 chunks (no indexable content found)")
        else:
            console.print(f"  ok  {lib} -- {count} chunks")

    console.print(f"\n[green]Done. {len(index_results)} libraries indexed.[/green]")


@app.command()
def serve(
    path: Optional[str] = typer.Option(None, "--path", help="Project root (defaults to cwd)"),
):
    """Start the MCP server (usually auto-configured -- you shouldn't need to run this manually)."""
    project_root = _resolve_path(path)
    towelette_dir = find_towelette_dir(project_root)

    if not towelette_dir:
        console.print("[red]No .towelette/ directory found. Run `towelette init` first.[/red]")
        raise typer.Exit(1)

    from towelette.server import create_server
    server = create_server(towelette_dir)
    console.print(f"[green]Starting MCP server bound to {towelette_dir}[/green]")
    server.run()


@app.command()
def status(
    path: Optional[str] = typer.Option(None, "--path", help="Project root (defaults to cwd)"),
):
    """Show what's indexed -- libraries, versions, chunk counts, and index health."""
    project_root = _resolve_path(path)
    towelette_dir = find_towelette_dir(project_root)

    if not towelette_dir:
        console.print("[yellow]No .towelette/ directory found. Run `towelette init` first.[/yellow]")
        return

    import asyncio
    from towelette.server import _do_index_status
    result = asyncio.run(_do_index_status(towelette_dir))
    console.print(result)


@app.command()
def refresh(
    path: Optional[str] = typer.Option(None, "--path", help="Project root (defaults to cwd)"),
):
    """Re-scan dependencies and index any new ones added since last init."""
    project_root = _resolve_path(path)
    towelette_dir = find_towelette_dir(project_root)

    if not towelette_dir:
        console.print("[red]No .towelette/ directory found. Run `towelette init` first.[/red]")
        raise typer.Exit(1)

    from towelette.config import get_user_skiplist
    user_skiplist = get_user_skiplist(towelette_dir)
    result = discover_deps(project_root, user_skiplist=user_skiplist)
    config = load_config(towelette_dir)
    existing = set(config.get("libraries", {}).keys())

    new_candidates = [c for c in result.candidates if c.name.lower().replace("-", "_") not in existing]

    if not new_candidates:
        console.print("[green]All dependencies already indexed.[/green]")
        return

    console.print("[bold]New dependencies found:[/bold]")
    for c in new_candidates:
        console.print(f"  - {c.name} ({c.version or 'unknown'})")

    # Scout and index new deps
    from towelette.orchestrator import index_from_reports, run_scouts
    from towelette.scout import format_scout_summary

    console.print("\n[bold]Dispatching scouts...[/bold]")
    reports = run_scouts(towelette_dir, new_candidates)
    summary = format_scout_summary(reports)
    console.print(f"\n{summary}\n")

    valid_reports = [r for r in reports if not r.error]
    if valid_reports:
        console.print(f"[bold]Indexing {len(valid_reports)} libraries...[/bold]")
        index_results = index_from_reports(towelette_dir, valid_reports)
        for lib, count in index_results.items():
            if count == 0:
                console.print(f"  [yellow]warn[/yellow]  {lib} -- 0 chunks (no indexable content found)")
            else:
                console.print(f"  ok  {lib} -- {count} chunks")
        console.print(f"\n[green]Done. {len(index_results)} new libraries indexed.[/green]")


@app.command()
def reset(
    path: Optional[str] = typer.Option(None, "--path", help="Project root (defaults to cwd)"),
):
    """Wipe .towelette/ and start fresh."""
    project_root = _resolve_path(path)
    towelette_dir = find_towelette_dir(project_root)

    if not towelette_dir:
        console.print("[yellow]No .towelette/ directory found.[/yellow]")
        return

    confirm = typer.confirm(f"Delete {towelette_dir}?")
    if confirm:
        shutil.rmtree(towelette_dir)
        console.print("[green]Removed .towelette/ directory.[/green]")


@app.command()
def add(
    library: str = typer.Argument(..., help="Library name to add"),
    repo: Optional[str] = typer.Option(None, "--repo", help="Git repo URL (required for non-PyPI C++ libraries)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Index immediately without confirmation"),
    path: Optional[str] = typer.Option(None, "--path", help="Project root"),
):
    """Scout a library and optionally index it. Pass -y to index immediately."""
    project_root = _resolve_path(path)
    towelette_dir = find_towelette_dir(project_root)
    if not towelette_dir:
        console.print("[red]No .towelette/ directory found. Run `towelette init` first.[/red]")
        raise typer.Exit(1)

    from towelette.models import DependencyCandidate
    from towelette.orchestrator import index_from_reports, run_scouts
    from towelette.scout import format_scout_summary

    console.print(f"\n[bold]Scouting '{library}'...[/bold]")
    candidate = DependencyCandidate(name=library, repo_url=repo)
    reports = run_scouts(towelette_dir, [candidate])

    summary = format_scout_summary(reports)
    console.print(f"\n{summary}\n")

    valid = [r for r in reports if not r.error]
    if not valid:
        console.print(f"[red]Scout failed for '{library}'. See errors above.[/red]")
        raise typer.Exit(1)

    if not yes:
        console.print("[dim]--report: exiting before indexing. Re-run with -y to index.[/dim]")
        return

    results = index_from_reports(towelette_dir, valid)
    for lib, count in results.items():
        console.print(f"  ok  {lib} -- {count} chunks")
    console.print(f"\n[green]Done.[/green]")


@app.command()
def remove(
    library: str = typer.Argument(..., help="Library name to remove"),
    path: Optional[str] = typer.Option(None, "--path", help="Project root"),
):
    """Remove a library from the index."""
    project_root = _resolve_path(path)
    towelette_dir = find_towelette_dir(project_root)
    if not towelette_dir:
        console.print("[red]No .towelette/ directory found.[/red]")
        raise typer.Exit(1)

    import chromadb
    config = load_config(towelette_dir)
    lib_config = config.get("libraries", {}).get(library)
    if not lib_config:
        console.print(f"[yellow]Library '{library}' not found in config.[/yellow]")
        return

    collection_name = lib_config.get("collection", f"{library}_code")
    client = chromadb.PersistentClient(path=str(towelette_dir / "chroma"))
    try:
        client.delete_collection(collection_name)
        console.print(f"[green]Removed collection '{collection_name}'.[/green]")
    except Exception as e:
        console.print(f"[red]Error removing collection: {e}[/red]")


@app.command()
def tune(
    library: str = typer.Argument(..., help="Library name to re-index"),
    path: Optional[str] = typer.Option(None, "--path", help="Project root"),
):
    """Re-index a specific library with different settings."""
    console.print(f"[yellow]Tune for '{library}' -- not yet implemented.[/yellow]")
