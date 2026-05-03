# Towelette

> A tiny RAG to wipe away API hallucinations.

LLMs hallucinate API calls for domain-specific libraries -- niche packages like pythonocc, potpourri3d, libigl, and Geometry Central have sparse or outdated training data. Towelette auto-discovers a project's dependencies, researches each library, builds a local RAG index, and serves it via MCP so your coding assistant gets the APIs right.

## Quick Start

```bash
pip install towelette    # or: pipx install towelette / uv tool install towelette
cd your-project/
towelette init
```

That's it. Towelette scans your dependencies, dispatches AI scouts to investigate each niche library, indexes source into a local vector DB, and writes an MCP server config to `.mcp.json`. Next time your AI assistant opens the project, it has accurate API knowledge.

**If you're an AI assistant** and someone asked you to "set up towelette": run `towelette init` in the project root. It handles discovery, scouting, indexing, and MCP configuration automatically.

## What It Does

1. **Discovers** your project's dependencies from `pyproject.toml`, `requirements.txt`, or `environment.yml`
2. **Filters** well-known libraries (numpy, pandas, torch, etc.) that LLMs already know
3. **Scouts** unfamiliar libraries with LLM subagents that research repos and recommend indexing strategies
4. **Indexes** source code (Python, C++, Rust) and documentation (Markdown) into ChromaDB with semantic embeddings
5. **Plugins** Support for custom language parsers via a dynamic plugin system
6. **Serves** an MCP server with search, lookup, and goto-definition tools

## CLI

```
towelette init [path]                     Scout all dependencies, show report, exit.
towelette init --agent-cmd "cmd"          Use a specific agent CLI for scouting.
towelette serve                           Start the MCP server.
towelette status                          Show what's indexed.
towelette refresh                         Re-scan deps, index new/updated ones.
towelette add <library> [--repo <url>]    Scout a library (use --repo for non-PyPI libs).
towelette add <library> -y                Scout and index immediately.
towelette remove <library>                Remove a library from the index.
towelette reset                           Wipe .towelette/ and start fresh.
```

### Agent-Agnostic Scouting

Towelette is agent-agnostic. While it defaults to `claude`, you can use any agent CLI that supports a prompt flag:

```bash
# Use Gemini CLI
towelette init --agent-cmd "gemini chat -p"

# Or set it globally
export TOWELETTE_AGENT_CMD="gemini chat -p"
```

## Indexing Strategies

| Strategy | When | What |
|----------|------|------|
| `python_ast` | Pure Python libraries | AST-extracted classes, functions, docstrings |
| `tree_sitter_cpp` | C/C++ headers/source | tree-sitter parsed classes, functions, declarations |
| `tree_sitter_rust` | Rust source code | tree-sitter parsed structs, enums, functions |
| `markdown` | Documentation | Semantic chunks based on headers (#, ##) |
| `custom` | Niche languages | User-defined plugins in `.towelette/plugins/` |

### Custom Parsers (Plugins)

You can extend Towelette to handle any language by adding a plugin to `.towelette/plugins/`. For example, a `kcl_plugin.py` allows Towelette to index KittyCAD Language files. See [docs/CUSTOM_PARSERS.md](docs/CUSTOM_PARSERS.md) for details.

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
|   +-- plugins/            <-- Custom language parsers (*_plugin.py)
|   +-- definitions.db      <-- Symbol -> file:line (SQLite)
+-- .claude/
    +-- settings.json       <-- MCP server auto-configured
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

v0.2.0 -- Pluggable & Agent-Agnostic:
- Discovery (pyproject.toml, requirements.txt, environment.yml, import scanning)
- Indexing (Python, C++, Rust, Markdown + Custom Plugins)
- Search (semantic + exact lookup + goto-definition)
- MCP server (4 query tools)
- CLI (Agent-agnostic scouting via `--agent-cmd`)

## License

MIT
