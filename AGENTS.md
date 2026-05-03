# Towelette Agent Instructions

This project is a RAG-based tool to help AI assistants understand niche libraries. As an AI assistant, you have a special role in maintaining and extending Towelette's capabilities.

## Mandates for Agents

### 1. Dynamic Language Support (Plugins)
Towelette is designed to be pluggable. If you encounter a language without a native tree-sitter or AST parser (like KCL, Lisp, or a proprietary DSL), **author a plugin** in `.towelette/plugins/<name>_plugin.py`.

- **Identify Analogs**: Use well-known languages as syntactical templates.
- **Semantic Chunking**: Split code at logical boundaries (functions/classes) and capture preceding doc-comments.
- **Definitions DB**: Always implement `extract_definitions` in your plugins to enable exact-symbol lookup (`towelette_lookup`).

See [docs/CUSTOM_PARSERS.md](docs/CUSTOM_PARSERS.md) for the technical interface and templates.

### 2. Agent Agnosticism
When implementing features that involve spawning subagents (scouts), always use the configurable `agent_cmd` pattern established in `orchestrator.py`. This ensures Towelette works regardless of the specific AI CLI environment.

## Key Commands
- `towelette init [path]`: Discover deps and index. Use `--agent-cmd` to specify your CLI if not using Claude.
- `towelette serve`: Start the MCP server.
- `towelette add <lib>`: Manually add and index a library.

## Technical Reference
- **Languages**: Python (AST), C++ (tree-sitter), Rust (tree-sitter), Markdown (headers).
- **Storage**: ChromaDB (vectors), SQLite (symbol definitions).
- **Architecture**: Discovery -> Scout Dispatch -> Indexing -> MCP Server.
