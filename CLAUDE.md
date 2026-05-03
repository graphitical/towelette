# Towelette Agent Guide

This file provides instructions for AI assistants (Claude, Gemini, etc.) working on the Towelette project.

## Project Vision
Towelette is a pluggable RAG pipeline that auto-indexes niche libraries. It is designed to be **agent-agnostic** and **extensible**.

## Key Commands
- `towelette init [path]`: Discover deps and index. Use `--agent-cmd` to specify your CLI if not using Claude.
- `towelette serve`: Start the MCP server.
- `towelette add <lib>`: Manually add and index a library.

## Mandates for Agents
1. **Dynamic Language Support**: If you encounter a language without a native tree-sitter or AST parser (like KCL), **author a plugin** in `.towelette/plugins/<name>_plugin.py`. 
2. **Semantic Chunking**: Plugins should split code at logical boundaries (functions/classes) and capture preceding comments.
3. **Agent Agnosticism**: When implementing features that involve spawning subagents, always use the configurable `agent_cmd` pattern established in `orchestrator.py`.

## Technical Reference
- **Languages**: Python (AST), C++ (tree-sitter), Rust (tree-sitter), Markdown (headers).
- **Storage**: ChromaDB (vectors), SQLite (symbol definitions).
- **Plugins**: See `docs/CUSTOM_PARSERS.md` for the plugin interface.
- **Project Context**: Foundation instructions are kept in `GEMINI.md`. Always adhere to them.
