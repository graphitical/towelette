"""Orchestrator -- coordinates discovery, scout dispatch, and indexing.

The orchestrator is the central coordinator. It:
1. Runs discovery to find dependency candidates
2. Resolves PyPI URLs to repo URLs
3. Dispatches scout subagents in parallel (one per candidate)
4. Collects scout reports
5. Chases upstream dependencies (one level deep)
6. Presents summary to the user
7. Indexes libraries based on confirmed reports
"""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import chromadb

from towelette.config import load_config, save_library_config
from towelette.index import index_cpp_source, index_python_source
from towelette.models import DependencyCandidate, IndexStrategy, ScoutReport
from towelette.scout import build_scout_prompt, parse_scout_report
from towelette.skiplist import should_skip


def _dispatch_one_scout(
    candidate: DependencyCandidate,
    repos_dir: Path,
    imports: list[str],
    model: str = "haiku",
) -> ScoutReport:
    """Dispatch a single scout as a subprocess.

    Spawns `claude` CLI as a subprocess with the scout prompt. The scout
    clones the repo, explores it, and returns a TOML report.

    Falls back to a minimal error report if the subprocess fails.
    """
    prompt = build_scout_prompt(candidate, imports, repos_dir=str(repos_dir))

    stderr_lines: list[str] = []

    def _stream_stderr(pipe) -> None:
        for line in pipe:
            stderr_lines.append(line)
            print(f"  [scout:{candidate.name}] {line}", end="", flush=True)

    try:
        proc = subprocess.Popen(
            [
                "claude",
                "--print",
                "--model", model,
                "--strict-mcp-config",  # ignore project .mcp.json -- prevents MCP tool bloat
                "--no-session-persistence",
                "--allowedTools", "Bash,Read,LS,Glob,Grep,WebFetch,WebSearch",
                "--verbose",
                "-p", prompt,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=Path.home(),        # neutral cwd -- prevents project CLAUDE.md from loading
        )
        stderr_thread = threading.Thread(target=_stream_stderr, args=(proc.stderr,), daemon=True)
        stderr_thread.start()
        try:
            stdout, _ = proc.communicate(timeout=300)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            return ScoutReport(
                library=candidate.name,
                repo=candidate.repo_url,
                version=candidate.version,
                error="Scout timed out after 300s",
            )
        stderr_thread.join()

        if proc.returncode == 0 and stdout.strip():
            return parse_scout_report(stdout)
        else:
            combined = ("".join(stderr_lines) + stdout).lower()
            if "prompt is too long" in combined:
                hint = (
                    f"Scout prompt exceeded {model}'s context limit. "
                    f"Set scout_model = \"sonnet\" in .towelette/config.toml to use a larger context "
                    f"(higher token usage)."
                )
                return ScoutReport(
                    library=candidate.name,
                    repo=candidate.repo_url,
                    version=candidate.version,
                    error=hint,
                )
            stderr_tail = "".join(stderr_lines)[-200:]
            return ScoutReport(
                library=candidate.name,
                repo=candidate.repo_url,
                version=candidate.version,
                error=f"Scout subprocess failed (exit {proc.returncode}): {stderr_tail}",
            )
    except FileNotFoundError:
        return ScoutReport(
            library=candidate.name,
            repo=candidate.repo_url,
            version=candidate.version,
            error="claude CLI not found -- install Claude Code to dispatch scouts",
        )


def _reports_dir(towelette_dir: Path) -> Path:
    """Return the directory where scout reports are persisted."""
    d = towelette_dir / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save_report(towelette_dir: Path, report: ScoutReport, candidate_name: str) -> None:
    """Persist a scout report to disk as JSON.

    Uses candidate_name for the filename (not report.library) so that
    failed parses that fall back to library="unknown" still get saved
    under the correct name.
    """
    path = _reports_dir(towelette_dir) / f"{candidate_name}.json"
    path.write_text(report.model_dump_json(indent=2))


def load_cached_reports(towelette_dir: Path) -> dict[str, ScoutReport]:
    """Load all previously saved scout reports from .towelette/reports/.

    Returns dict of normalized_name -> ScoutReport.
    """
    reports_dir = towelette_dir / "reports"
    if not reports_dir.exists():
        return {}
    cached: dict[str, ScoutReport] = {}
    for path in reports_dir.glob("*.json"):
        try:
            report = ScoutReport.model_validate_json(path.read_text())
            key = report.library.lower().replace("-", "_")
            cached[key] = report
        except Exception:
            continue
    return cached


def run_scouts(
    towelette_dir: Path,
    candidates: list[DependencyCandidate],
    imports: dict[str, list[str]] | None = None,
    max_parallel: int = 4,
    model: str | None = None,
) -> list[ScoutReport]:
    """Resolve repo URLs, then dispatch scouts in parallel.

    Each scout is a Claude Code subprocess that clones a repo, explores it,
    and returns a TOML report. After all scouts return, upstream dependencies
    are chased one level deep with additional scouts.

    Cached reports from previous runs are reused -- only new candidates
    trigger scout dispatch.

    Returns list of ScoutReports for all candidates + discovered upstreams.
    """
    from towelette.discover import resolve_candidates

    if imports is None:
        imports = {}

    repos_dir = towelette_dir / "repos"
    repos_dir.mkdir(parents=True, exist_ok=True)

    # Resolve model from config if not explicitly provided
    config = load_config(towelette_dir)
    scout_model = model or config.get("settings", {}).get("scout_model", "haiku")

    # Load cached reports from previous (possibly crashed) runs
    cached = load_cached_reports(towelette_dir)

    # Split candidates into cached vs needing scouts
    reports: list[ScoutReport] = []
    to_scout: list[DependencyCandidate] = []
    processed_names: set[str] = set()

    for c in candidates:
        key = c.name.lower().replace("-", "_")
        processed_names.add(key)
        if key in cached and not cached[key].error:
            reports.append(cached[key])
        else:
            to_scout.append(c)

    if to_scout:
        # Resolve repo URLs in parallel
        resolved = asyncio.run(resolve_candidates(to_scout))

        with ThreadPoolExecutor(max_workers=max_parallel) as pool:
            futures = {
                pool.submit(
                    _dispatch_one_scout,
                    candidate,
                    repos_dir,
                    imports.get(candidate.name, []),
                    scout_model,
                ): candidate
                for candidate in resolved
            }
            for future in as_completed(futures):
                candidate = futures[future]
                try:
                    report = future.result()
                except Exception as e:
                    report = ScoutReport(
                        library=candidate.name,
                        error=f"Scout dispatch failed: {e}",
                    )
                _prefix_paths(report, candidate.name)
                _warn_missing_paths(report, towelette_dir)
                _save_report(towelette_dir, report, candidate.name)
                reports.append(report)
                if report.error:
                    print(f"  ERR  {candidate.name} -- {report.error[:80]}", flush=True)
                else:
                    print(f"  ok   {candidate.name} -- {report.strategy}, ~{report.estimated_chunks} chunks", flush=True)

    # Chase upstream dependencies (one level deep) -- opt-in via upstream_chase = true
    if not config.get("settings", {}).get("upstream_chase", False):
        return reports

    user_skiplist = set(config.get("skiplist", {}).get("extra", []))

    upstream_candidates: list[DependencyCandidate] = []
    for report in reports:
        for upstream in report.upstream_dependencies:
            if not upstream.recommended:
                continue
            name_key = upstream.library.lower().replace("-", "_")
            if name_key in processed_names:
                continue
            if should_skip(upstream.library, user_skiplist):
                continue
            processed_names.add(name_key)
            # Check cache for upstreams too
            if name_key in cached and not cached[name_key].error:
                reports.append(cached[name_key])
            else:
                upstream_candidates.append(
                    DependencyCandidate(
                        name=upstream.library,
                        repo_url=upstream.repo or None,
                    )
                )

    if upstream_candidates:
        upstream_resolved = asyncio.run(resolve_candidates(upstream_candidates))
        with ThreadPoolExecutor(max_workers=max_parallel) as pool:
            futures = {
                pool.submit(
                    _dispatch_one_scout,
                    candidate,
                    repos_dir,
                    imports.get(candidate.name, []),
                    scout_model,
                ): candidate
                for candidate in upstream_resolved
            }
            for future in as_completed(futures):
                candidate = futures[future]
                try:
                    report = future.result()
                except Exception as e:
                    report = ScoutReport(
                        library=candidate.name,
                        error=f"Scout dispatch failed: {e}",
                    )
                _prefix_paths(report, candidate.name)
                _warn_missing_paths(report, towelette_dir)
                _save_report(towelette_dir, report, candidate.name)
                reports.append(report)
                if report.error:
                    print(f"  ERR  {candidate.name} (upstream) -- {report.error[:80]}", flush=True)
                else:
                    print(f"  ok   {candidate.name} (upstream) -- {report.strategy}, ~{report.estimated_chunks} chunks", flush=True)

    return reports


def _sanitize_collection_name(raw: str) -> str:
    """Sanitize a string into a valid ChromaDB collection name.

    ChromaDB requires: 3-512 chars from [a-zA-Z0-9._-], starting and
    ending with [a-zA-Z0-9].
    """
    name = re.sub(r"[^a-zA-Z0-9._-]", "_", raw)
    name = re.sub(r"_+", "_", name)
    name = name.strip("_.-")
    if len(name) < 3:
        name = name.ljust(3, "x")
    return name[:512]


def _warn_missing_paths(report: ScoutReport, towelette_dir: Path) -> None:
    """Warn if any declared source_paths or cpp_paths don't exist on disk."""
    if report.error:
        return
    for p in report.source_paths + report.cpp_paths:
        full = towelette_dir / p
        if not full.exists():
            print(f"  WARN {report.library} -- declared path missing: {p}", flush=True)


def _prefix_paths(report: ScoutReport, library_name: str) -> None:
    """Prefix source_paths/cpp_paths with repos/<name> for index_from_reports."""
    if report.error:
        return
    prefix = f"repos/{library_name}"

    def _do_prefix(paths: list[str]) -> list[str]:
        result = []
        for p in paths:
            if p == ".":
                result.append(prefix)
            elif not p.startswith("repos/"):
                result.append(f"{prefix}/{p}")
            else:
                result.append(p)
        return result

    report.source_paths = _do_prefix(report.source_paths)
    report.cpp_paths = _do_prefix(report.cpp_paths)


def index_from_reports(
    towelette_dir: Path,
    reports: list[ScoutReport],
) -> dict[str, int]:
    """Index libraries based on scout reports.

    Returns dict of library_name -> chunk_count.
    """
    client = chromadb.PersistentClient(path=str(towelette_dir / "chroma"))
    db_path = towelette_dir / "definitions.db"
    results: dict[str, int] = {}

    for report in reports:
        if report.error:
            continue

        collection_name = _sanitize_collection_name(f"{report.library}_code")

        source_paths = [towelette_dir / p for p in report.source_paths]
        cpp_paths = [towelette_dir / p for p in report.cpp_paths]

        # Detect scouts that described repos via WebFetch without cloning locally.
        # Auto-clone if all source paths are missing and we have a repo URL.
        all_paths = source_paths + cpp_paths
        missing = [p for p in all_paths if not p.exists()]
        if missing and len(missing) == len(all_paths):
            clone_dest = towelette_dir / "repos" / report.library
            if not clone_dest.exists() or not any(clone_dest.iterdir()):
                if report.repo:
                    print(f"  clone {report.library} -- repo not present, cloning...", flush=True)
                    clone_result = subprocess.run(
                        ["git", "clone", "--depth=1", report.repo, str(clone_dest)],
                        capture_output=True, text=True, timeout=300,
                    )
                    if clone_result.returncode != 0:
                        print(f"  ERR  {report.library} -- clone failed: {clone_result.stderr[:120]}", flush=True)
                        continue
                    # Refresh path lists after clone
                    source_paths = [towelette_dir / p for p in report.source_paths]
                    cpp_paths = [towelette_dir / p for p in report.cpp_paths]
                    still_missing = [p for p in source_paths + cpp_paths if not p.exists()]
                    if still_missing:
                        print(f"  WARN {report.library} -- paths still missing after clone: {[p.name for p in still_missing]}", flush=True)
                else:
                    print(f"  SKIP {report.library} -- repo not cloned and no URL available", flush=True)
                    continue

        total_chunks = 0

        if report.strategy in (IndexStrategy.PYTHON_AST, IndexStrategy.BOTH, "python_ast", "python_ast + tree_sitter_cpp"):
            paths_to_index = source_paths if source_paths else cpp_paths
            if paths_to_index:
                count = index_python_source(
                    client=client,
                    collection_name=collection_name,
                    source=report.library,
                    source_paths=paths_to_index,
                    db_path=db_path,
                    version=report.version,
                )
                total_chunks += count

        if report.strategy in (IndexStrategy.TREE_SITTER_CPP, IndexStrategy.BOTH, "tree_sitter_cpp", "python_ast + tree_sitter_cpp"):
            paths_to_index = cpp_paths if cpp_paths else source_paths
            if paths_to_index:
                cpp_collection = (
                    collection_name
                    if report.strategy in (IndexStrategy.BOTH, "python_ast + tree_sitter_cpp")
                    else _sanitize_collection_name(f"{report.library}_code_cpp")
                )
                count = index_cpp_source(
                    client=client,
                    collection_name=cpp_collection,
                    source=report.library,
                    source_paths=paths_to_index,
                    db_path=db_path,
                    version=report.version,
                )
                total_chunks += count

        save_library_config(towelette_dir, report.library, {
            "collection": collection_name,
            "version": report.version or "",
            "strategy": report.strategy,
            "source_paths": report.source_paths,
        })

        results[report.library] = total_chunks

    return results


def index_project(
    project_root: Path,
    towelette_dir: Path,
) -> int:
    """Index the project's own Python source."""
    client = chromadb.PersistentClient(path=str(towelette_dir / "chroma"))
    db_path = towelette_dir / "definitions.db"

    skip_dirs = {".venv", "venv", "node_modules", ".towelette", "__pycache__", ".git", ".tox"}

    count = index_python_source(
        client=client,
        collection_name="project_code",
        source="project",
        source_paths=[project_root],
        db_path=db_path,
        version="local",
        skip_dirs=skip_dirs,
    )

    save_library_config(towelette_dir, "project", {
        "collection": "project_code",
        "version": "local",
        "strategy": "python_ast",
        "source_paths": ["."],
    })

    return count


def write_mcp_config(project_root: Path) -> None:
    """Write MCP server config to both .mcp.json and .claude/settings.json.

    .mcp.json (project root) is what Claude Code reads for MCP server discovery.
    .claude/settings.json is written for completeness / other tooling.
    """
    mcp_entry = {"command": "towelette", "args": ["serve"]}

    # .mcp.json -- primary: this is what Claude Code's /mcp dialog reads
    mcp_json_path = project_root / ".mcp.json"
    if mcp_json_path.exists():
        mcp_config = json.loads(mcp_json_path.read_text())
    else:
        mcp_config = {}
    if "mcpServers" not in mcp_config:
        mcp_config["mcpServers"] = {}
    mcp_config["mcpServers"]["towelette"] = mcp_entry
    mcp_json_path.write_text(json.dumps(mcp_config, indent=2) + "\n")

    # .claude/settings.json -- secondary: for permissions/hooks config
    claude_dir = project_root / ".claude"
    claude_dir.mkdir(exist_ok=True)
    settings_path = claude_dir / "settings.json"
    if settings_path.exists():
        settings = json.loads(settings_path.read_text())
    else:
        settings = {}
    if "mcpServers" not in settings:
        settings["mcpServers"] = {}
    settings["mcpServers"]["towelette"] = mcp_entry
    settings_path.write_text(json.dumps(settings, indent=2) + "\n")


def add_to_gitignore(project_root: Path) -> None:
    """Ensure .towelette/ and .mcp.json are in .gitignore."""
    gitignore = project_root / ".gitignore"
    content = gitignore.read_text() if gitignore.exists() else ""
    additions = []
    if ".towelette/" not in content:
        additions.append(".towelette/")
    if ".mcp.json" not in content:
        additions.append(".mcp.json")
    if additions:
        with open(gitignore, "a") as f:
            f.write("\n" + "\n".join(additions) + "\n")
