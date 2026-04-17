# Towelette

> A tiny RAG to wipe away API hallucinations.

LLMs hallucinate API calls for domain-specific libraries -- niche packages like pythonocc, potpourri3d, libigl, and Geometry Central have sparse or outdated training data. Towelette auto-discovers a project's dependencies, researches each library, builds a local RAG index, and serves it via MCP so your coding assistant gets the APIs right.

## Quick Start

```bash
pip install towelette    # or: pipx install towelette / uv tool install towelette
cd your-project/
towelette init
```

That's it. Towelette scans your dependencies, dispatches Claude subagents to investigate each niche library, indexes source into a local vector DB, and writes an MCP server config to `.mcp.json`. Next time Claude Code opens the project, it has accurate API knowledge.

**If you're an AI assistant** and someone asked you to "set up towelette": run `towelette init` in the project root. It handles discovery, scouting, indexing, and MCP configuration automatically.

## What It Does

1. **Discovers** your project's dependencies from `pyproject.toml`, `requirements.txt`, or `environment.yml`
2. **Filters** well-known libraries (numpy, pandas, torch, etc.) that LLMs already know
3. **Scouts** unfamiliar libraries with LLM subagents that research repos and recommend indexing strategies
4. **Indexes** Python source (AST) and C/C++ source and headers (tree-sitter) into ChromaDB with semantic embeddings
5. **Serves** an MCP server with search, lookup, and goto-definition tools

## CLI

```
towelette init [path]                     Scout all dependencies, show report, exit.
towelette init --no-report [-y]           Scout then index (with optional confirmation skip).
towelette init --no-report --only a,b,c  Scout then index only named libraries.
towelette serve                           Start the MCP server.
towelette status                          Show what's indexed.
towelette refresh                         Re-scan deps, index new/updated ones.
towelette add <library> [--repo <url>]    Scout a library (use --repo for non-PyPI C++ libs).
towelette add <library> -y                Scout and index immediately.
towelette remove <library>                Remove a library from the index.
towelette reset                           Wipe .towelette/ and start fresh.
```

By default `towelette init` scouts all dependencies, prints a summary, and exits — no indexing. Re-run with `--no-report` to proceed to indexing, adding `-y` to skip per-library confirmation.

## MCP Tools

Once running, Towelette exposes these tools to your AI assistant:

| Tool | Purpose |
|------|---------|
| `towelette_search` | Semantic search across indexed libraries |
| `towelette_lookup` | Exact name lookup for classes/functions |
| `towelette_goto_definition` | Find definition location (file:line) |
| `towelette_index_status` | Show indexed libraries and versions |

## How It Works

```
your-project/
+-- pyproject.toml          <-- Towelette reads this
+-- src/
+-- .towelette/             <-- Created by `towelette init`
|   +-- config.toml         <-- What's indexed, strategies, versions
|   +-- chroma/             <-- Vector store (ChromaDB)
|   +-- repos/              <-- Cloned library repos
|   +-- definitions.db      <-- Symbol -> file:line (SQLite)
+-- .claude/
    +-- settings.json       <-- MCP server auto-configured
```

### Indexing Strategies

| Strategy | When | What |
|----------|------|------|
| `python_ast` | Pure Python libraries | AST-extracted classes, functions, docstrings |
| `tree_sitter_cpp` | C/C++ headers/source | tree-sitter parsed classes, functions, declarations |
| Both | Python bindings over C++ | Both strategies, same collection |

### Skiplist

Towelette ships with a default skiplist of well-known libraries where RAG adds no value (numpy, scipy, pandas, flask, torch, pydantic, etc.). Extend it in `.towelette/config.toml`:

```toml
[skiplist]
extra = ["my-internal-lib", "another-lib"]
```

## Development

```bash
git clone https://github.com/graphitical/towelette.git
cd towelette
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

## Status

v0.1.0 -- Core pipeline works end-to-end:
- Discovery (pyproject.toml, requirements.txt, environment.yml, import scanning)
- Indexing (Python AST + tree-sitter C++)
- Search (semantic + exact lookup + goto-definition)
- MCP server (4 query tools)
- CLI (8 commands)

Scout dispatch requires [Claude Code](https://claude.ai/code) to be installed — scouts are `claude --print` subprocesses that clone repos and return structured reports.

## License

MIT
