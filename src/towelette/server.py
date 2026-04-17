"""MCP server -- query and management tools."""
from __future__ import annotations

from pathlib import Path

import chromadb
from mcp.server.fastmcp import FastMCP

from towelette.config import load_config
from towelette.definitions import lookup_symbol
from towelette.embed import get_embedding_function
from towelette.search import exact_lookup, semantic_search


async def _do_search(
    towelette_dir: Path,
    query: str,
    scope: str = "all",
    limit: int = 5,
    max_per_class: int = 1,
) -> str:
    """Run semantic search and format results as markdown."""
    client = chromadb.PersistentClient(path=str(towelette_dir / "chroma"))
    results = semantic_search(client, query, scope=scope if scope != "all" else None, limit=limit, max_per_class=max_per_class)

    if not results:
        return f"No results found for '{query}'."

    lines = [f"## Search results for '{query}'\n"]
    for i, r in enumerate(results, 1):
        relevance = max(0, 1 - r.get("distance", 1))
        lines.append(f"### {i}. {r['class_name']} ({r['source']})")
        lines.append(f"**File:** `{r['file_path']}` | **Relevance:** {relevance:.2f}\n")

        content = r.get("content", "")
        if relevance >= 0.5:
            preview = content[:2000]
        elif relevance >= 0.35:
            preview = content[:300] + ("\n..." if len(content) > 300 else "")
        else:
            preview = f"*Low relevance -- use lookup for `{r['class_name']}` for details*"

        lines.append(f"```\n{preview}\n```\n")

    return "\n".join(lines)


async def _do_lookup(
    towelette_dir: Path,
    name: str,
    scope: str = "all",
) -> str:
    """Run exact lookup and format results."""
    client = chromadb.PersistentClient(path=str(towelette_dir / "chroma"))
    results = exact_lookup(client, name, scope=scope if scope != "all" else None)

    if not results:
        return f"No results found for '{name}'."

    lines = [f"## Lookup: {name}\n"]
    for r in results:
        lines.append(f"### {r['class_name']} ({r['source']})")
        lines.append(f"**File:** `{r['file_path']}` | **Type:** {r.get('chunk_type', 'unknown')}\n")
        content = r.get("content", "")[:3000]
        lines.append(f"```\n{content}\n```\n")

    return "\n".join(lines)


async def _do_goto_definition(
    towelette_dir: Path,
    symbol: str,
    scope: str | None = None,
    kind: str | None = None,
) -> str:
    """Look up symbol in definitions DB and format results."""
    db_path = towelette_dir / "definitions.db"
    if not db_path.exists():
        return "No definitions database found. Run `towelette init` first."

    results = lookup_symbol(db_path, symbol, source=scope, kind=kind)

    if not results:
        return f"No definition found for '{symbol}'."

    lines = [f"## Definition: {symbol}\n"]
    lines.append("| Qualified Name | Location | Kind | Source |")
    lines.append("|---|---|---|---|")

    repos_dir = towelette_dir / "repos"
    for r in results:
        file_path = r["file_path"]
        line = r["line"]
        full_path = repos_dir / r["source"] / file_path
        if full_path.exists():
            location = f"`{full_path}:{line}`"
        else:
            location = f"`{file_path}:{line}`"
        lines.append(f"| {r['qualified_name']} | {location} | {r['kind']} | {r['source']} |")

    return "\n".join(lines)


async def _do_index_status(towelette_dir: Path) -> str:
    """Report what's indexed, versions, chunk counts."""
    client = chromadb.PersistentClient(path=str(towelette_dir / "chroma"))

    collections = client.list_collections()
    if not collections:
        return "No collections indexed. Run `towelette init` to get started."

    ef = get_embedding_function()
    lines = ["## Towelette Index Status\n"]
    lines.append("| Library | Collection | Chunks | Version |")
    lines.append("|---|---|---|---|")

    for col_meta in collections:
        col = client.get_collection(col_meta.name, embedding_function=ef)
        count = col.count()
        version = (col.metadata or {}).get("version", "unknown")
        source = (col.metadata or {}).get("source", col_meta.name)
        lines.append(f"| {source} | {col_meta.name} | {count} | {version} |")

    return "\n".join(lines)


def create_server(towelette_dir: Path) -> FastMCP:
    """Create and configure the MCP server bound to a .towelette directory."""
    config = load_config(towelette_dir)
    prefix = config.get("settings", {}).get("tool_prefix", "towelette")

    mcp = FastMCP(f"{prefix}_mcp")

    # --- Query tools (normal coding) ---

    @mcp.tool(name=f"{prefix}_search")
    async def search_tool(query: str, scope: str = "all", limit: int = 5, max_per_class: int = 1) -> str:
        """Semantic search across indexed libraries. Use scope to target a specific library."""
        return await _do_search(towelette_dir, query=query, scope=scope, limit=limit, max_per_class=max_per_class)

    @mcp.tool(name=f"{prefix}_lookup")
    async def lookup_tool(name: str, scope: str = "all") -> str:
        """Exact name lookup for a class, function, or symbol."""
        return await _do_lookup(towelette_dir, name=name, scope=scope)

    @mcp.tool(name=f"{prefix}_goto_definition")
    async def goto_definition_tool(symbol: str, scope: str | None = None, kind: str | None = None) -> str:
        """Find the definition location (file:line) of a symbol."""
        return await _do_goto_definition(towelette_dir, symbol=symbol, scope=scope, kind=kind)

    @mcp.tool(name=f"{prefix}_index_status")
    async def index_status_tool() -> str:
        """Show what's indexed: libraries, versions, chunk counts."""
        return await _do_index_status(towelette_dir)

    # --- Management tools (setup and maintenance) ---

    @mcp.tool(name=f"{prefix}_init")
    async def init_tool(project_path: str) -> str:
        """Run discovery on a project. Returns candidates with scout prompts.

        After calling this, dispatch a scout subagent for each candidate using the
        provided prompts. Each scout should clone the repo, explore it, and return a
        TOML report. Then call towelette_index with the collected reports.
        """
        return await _do_init(towelette_dir, Path(project_path))

    @mcp.tool(name=f"{prefix}_index")
    async def index_tool(reports_toml: str) -> str:
        """Index libraries from scout reports.

        Pass the TOML reports collected from scout subagents. Each report should be
        a [report] block as returned by the scouts. Multiple reports can be
        separated by '---'.
        """
        return await _do_index_from_reports(towelette_dir, reports_toml)

    @mcp.tool(name=f"{prefix}_refresh")
    async def refresh_tool(project_path: str) -> str:
        """Re-run discovery and return new candidates needing scouts."""
        return await _do_refresh(towelette_dir, Path(project_path))

    return mcp


# --- Management tool implementations ---


async def _do_init(towelette_dir: Path, project_path: Path) -> str:
    """Run discovery and return candidates with scout prompts."""
    from towelette.config import get_user_skiplist, init_towelette_dir
    from towelette.discover import discover_deps
    from towelette.orchestrator import index_project, write_mcp_config, add_to_gitignore
    from towelette.scout import build_scout_agent_prompt

    init_towelette_dir(project_path)
    user_skiplist = get_user_skiplist(towelette_dir)
    result = discover_deps(project_path, user_skiplist=user_skiplist)

    # Index project source
    project_chunks = index_project(project_path, towelette_dir)
    write_mcp_config(project_path)
    add_to_gitignore(project_path)

    lines = [f"Project source indexed: {project_chunks} chunks\n"]

    if not result.candidates:
        lines.append("No dependency candidates found for indexing.")
        if result.skipped:
            lines.append(f"Skipped (well-known): {', '.join(result.skipped)}")
        return "\n".join(lines)

    lines.append("Candidates for indexing:")
    for c in result.candidates:
        v = f" ({c.version})" if c.version else ""
        lines.append(f"  - {c.name}{v} -- {c.import_count} imports")

    if result.skipped:
        lines.append(f"\nSkipped (well-known): {', '.join(result.skipped)}")

    lines.append("\nScout prompts for each candidate follow. Dispatch one subagent per candidate.")
    lines.append("Each scout should clone the repo, explore it, and return a TOML report.")
    lines.append("Then call towelette_index with all collected reports.\n")

    for c in result.candidates:
        prompt = build_scout_agent_prompt(c, towelette_dir)
        lines.append(f"--- SCOUT: {c.name} ---")
        lines.append(prompt)
        lines.append("")

    return "\n".join(lines)


async def _do_index_from_reports(towelette_dir: Path, reports_toml: str) -> str:
    """Parse and index from scout report text."""
    from towelette.orchestrator import index_from_reports
    from towelette.scout import parse_scout_report

    # Split on --- separator if multiple reports
    report_blocks = [b.strip() for b in reports_toml.split("---") if b.strip()]

    reports = []
    for block in report_blocks:
        report = parse_scout_report(block)
        if report.library != "unknown" or not report.error:
            reports.append(report)

    if not reports:
        return "No valid reports found in the input."

    results = index_from_reports(towelette_dir, reports)

    lines = ["Indexing complete:\n"]
    for lib, count in results.items():
        lines.append(f"  ok  {lib} -- {count} chunks")

    return "\n".join(lines)


async def _do_refresh(towelette_dir: Path, project_path: Path) -> str:
    """Re-run discovery and return only new candidates."""
    from towelette.config import get_user_skiplist
    from towelette.discover import discover_deps
    from towelette.scout import build_scout_agent_prompt

    user_skiplist = get_user_skiplist(towelette_dir)
    result = discover_deps(project_path, user_skiplist=user_skiplist)
    config = load_config(towelette_dir)
    existing = set(config.get("libraries", {}).keys())

    new_candidates = [c for c in result.candidates if c.name.lower().replace("-", "_") not in existing]

    if not new_candidates:
        return "All dependencies already indexed."

    lines = ["New dependencies found:\n"]
    for c in new_candidates:
        lines.append(f"  - {c.name} ({c.version or 'unknown'})")

    lines.append("\nScout prompts:")
    for c in new_candidates:
        prompt = build_scout_agent_prompt(c, towelette_dir)
        lines.append(f"\n--- SCOUT: {c.name} ---")
        lines.append(prompt)

    return "\n".join(lines)
