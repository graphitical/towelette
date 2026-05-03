"""Scout prompt generation, report parsing, and summary formatting.

Scouts are LLM subagents dispatched by the orchestrator — one per candidate
library. Each scout clones a repo, explores its structure, and returns a
structured TOML report recommending an indexing strategy.

This module builds the prompts that scouts receive, parses the reports they
return, and formats summaries for the user. The actual dispatch (spawning
subagents) is handled by the orchestrator.
"""
from __future__ import annotations

import json
import sys

from towelette.models import DependencyCandidate, ScoutReport, UpstreamDependency

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


def build_scout_prompt(
    candidate: DependencyCandidate,
    imports: list[str] | None = None,
    repos_dir: str | None = None,
) -> str:
    """Build the prompt dispatched to a scout subagent.

    The scout receives this prompt and is expected to:
    1. Clone the repo (shallow, at the tagged version)
    2. Explore the directory structure
    3. Reason about indexing strategy, source paths, skip patterns
    4. Check for significant upstream dependencies
    5. Return a structured TOML report
    """
    version_str = f"v{candidate.version}" if candidate.version else "latest (main branch)"
    imports_str = ", ".join(imports) if imports else "(no specific imports detected)"

    if candidate.repo_url:
        repo_section = f"Repo: {candidate.repo_url}\nVersion: {version_str}"
        clone_instruction = "1. Clone the repo (shallow, at the tagged version) into the clone destination below"
    else:
        repo_section = (
            f"Package name: {candidate.name}\nVersion: {version_str}\n"
            f"No repo URL was provided."
        )
        clone_instruction = (
            "1. Search for the canonical source repo:\n"
            "   a. Search PyPI for the package and check its `project_urls` for a repository link\n"
            "   b. If not on PyPI, do a web search for \"<library> github\" or \"<library> source code\"\n"
            "   c. If a git repo is found, clone it (shallow) into the clone destination below\n"
            "   d. If the package is Python-only with no public git repo, use `pip download --no-deps --no-binary :all:` to get the sdist and extract it\n"
            "   e. If no source can be found, set repo = \"\" and strategy = \"none\" in the report and explain in notes"
        )

    clone_dest = ""
    if repos_dir:
        clone_dest = f"\n\nClone destination: {repos_dir}/{candidate.name}"

    return f"""\
You are a Towelette scout researching the library "{candidate.name}".

{repo_section}
The project imports: {imports_str}{clone_dest}

Your job:
{clone_instruction}
2. Explore the directory structure
3. Identify: Python source paths, C/C++ binding paths, Rust source paths, doc paths
4. Recommend an indexing strategy (python_ast, tree_sitter_cpp, tree_sitter_rust, or markdown)
5. Identify files/dirs to skip (tests, examples, CI, build scripts)
6. Check for significant upstream dependencies (dependency chasing -- one level deep only)
7. Return a structured TOML report in this exact format:

```toml
[report]
library = "{candidate.name}"
repo = "<repo_url or empty string>"
version = "{version_str}"
strategy = "<python_ast | tree_sitter_cpp | tree_sitter_rust | markdown | custom_plugin_name>"
source_paths = ["<path1>", "<path2>"]
cpp_paths = ["<path1>"]
doc_paths = ["<path1>"]
skip_patterns = ["test_*", "setup.py"]
estimated_chunks = <number>
notes = "<brief description>"

[[upstream_dependencies]]
library = "<name>"
repo = "<url>"
reason = "<why it matters>"
significance = "high"
recommended = true
```

Rules:
- You are running non-interactively. Execute all operations directly -- do not ask for permission or confirmation before running any command.
- You MUST clone or download the repo locally before writing your report. Do not describe the repo using WebFetch/GitHub alone -- the local clone is required for indexing.
- source_paths and cpp_paths should be relative to the repo root
- doc_paths should contain Markdown files or other documentation/examples
- VERIFY every path you put in source_paths, cpp_paths, and doc_paths actually exists with `ls <clone_dest>/<path>` before writing the report. Do not guess paths from GitHub -- confirm them locally.
- Strategy heuristics: 
  - .py files -> python_ast
  - .h/.hpp/.hxx/.cpp/.cc -> tree_sitter_cpp
  - .rs files -> tree_sitter_rust
  - .md/.markdown -> markdown
  - For niche languages, recommend a "custom_<name>" strategy and briefly explain the language in notes.
- Watch for src-layout packages (pyproject.toml with `packages = [{{include = "foo", from = "src"}}]`) -- the Python source will be under `src/foo/`, not `foo/`.
- Only include [[upstream_dependencies]] if you find significant upstream deps with domain logic
- Skip Eigen, Boost, STL, numpy, etc. as upstream deps -- only recommend libs with unique domain logic
- Return ONLY the TOML report block in your final response
"""


def parse_scout_report(report_text: str) -> ScoutReport:
    """Parse a scout report from TOML or JSON text.

    Tries to extract a TOML code block first, then raw TOML, then JSON.
    Returns an error ScoutReport if nothing parses.
    """
    cleaned = report_text
    if "```toml" in cleaned:
        start = cleaned.index("```toml") + 7
        end = cleaned.index("```", start)
        cleaned = cleaned[start:end].strip()
    elif "```" in cleaned:
        start = cleaned.index("```") + 3
        end = cleaned.index("```", start)
        cleaned = cleaned[start:end].strip()

    # Try TOML
    try:
        data = tomllib.loads(cleaned)
        if "report" in data:
            report_data = data["report"]
            if "upstream_dependencies" in data:
                report_data["upstream_dependencies"] = data["upstream_dependencies"]
            elif "upstream_dependencies" not in report_data:
                report_data["upstream_dependencies"] = []
        else:
            report_data = data

        upstream = [UpstreamDependency(**ud) for ud in report_data.get("upstream_dependencies", [])]

        return ScoutReport(
            library=report_data.get("library", "unknown"),
            repo=report_data.get("repo"),
            version=report_data.get("version"),
            strategy=report_data.get("strategy", "python_ast"),
            source_paths=report_data.get("source_paths", []),
            cpp_paths=report_data.get("cpp_paths", []),
            doc_paths=report_data.get("doc_paths", []),
            skip_patterns=report_data.get("skip_patterns", []),
            estimated_chunks=report_data.get("estimated_chunks", 0),
            notes=report_data.get("notes", ""),
            upstream_dependencies=upstream,
        )
    except Exception:
        pass

    # Try JSON
    try:
        data = json.loads(cleaned)
        upstream = [UpstreamDependency(**ud) for ud in data.get("upstream_dependencies", [])]
        return ScoutReport(
            library=data.get("library", "unknown"),
            repo=data.get("repo"),
            version=data.get("version"),
            strategy=data.get("strategy", "python_ast"),
            source_paths=data.get("source_paths", []),
            cpp_paths=data.get("cpp_paths", []),
            doc_paths=data.get("doc_paths", []),
            skip_patterns=data.get("skip_patterns", []),
            estimated_chunks=data.get("estimated_chunks", 0),
            notes=data.get("notes", ""),
            upstream_dependencies=upstream,
        )
    except Exception:
        pass

    return ScoutReport(
        library="unknown",
        error=f"Could not parse scout report. Raw text:\n{report_text[:500]}",
    )


def format_scout_summary(reports: list[ScoutReport]) -> str:
    """Format scout reports into a human-readable summary."""
    lines = ["Towelette Scout Report", chr(9472) * 40]

    for report in reports:
        if report.error:
            lines.append(f"  ERR  {report.library} -- {report.error}")
            continue

        version_str = f" ({report.version})" if report.version else ""
        chunk_str = f"~{report.estimated_chunks} chunks" if report.estimated_chunks else ""
        lines.append(f"  ok   {report.library}{version_str} -- {report.strategy}, {chunk_str}")
        if report.notes:
            lines.append(f"       {report.notes}")

        for ud in report.upstream_dependencies:
            tag = " [recommended]" if ud.recommended else ""
            lines.append(f"       depends on: {ud.library} ({ud.significance} significance){tag}")

    return "\n".join(lines)
