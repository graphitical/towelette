# Towelette Agent Instructions

This project is a RAG-based tool to help AI assistants understand niche libraries. As an AI assistant, you have a special role in maintaining and extending Towelette's capabilities.

## Mandate: Dynamic Language Support

Towelette is designed to be pluggable. If you are using Towelette to index a project that uses a niche or custom language (like KCL, Lisp, or a proprietary DSL), **do not settle for generic text indexing.**

1.  **Author a Plugin**: Create a custom parser plugin in `.towelette/plugins/<name>_plugin.py`.
2.  **Use Analogs**: Identify a well-known language that is syntactically similar to the target DSL. Use its parsing patterns (regex or tree-sitter) as a base.
3.  **Chunk Semantically**: Ensure your parser chunks the code into logical units (functions, classes, blocks) and captures preceding documentation comments.
4.  **Register the Strategy**: Recommend your custom strategy name in the `ScoutReport`.

See [docs/CUSTOM_PARSERS.md](docs/CUSTOM_PARSERS.md) for the technical interface and templates.

## Scouting Workflow

When dispatching scouts (`towelette init` or `towelette add`), Towelette defaults to using the `claude` CLI. 

-   If you are running in an environment where a different agent CLI is preferred (e.g., `gemini chat`), use the `--agent-cmd` flag or set the `TOWELETTE_AGENT_CMD` environment variable.
-   Example: `towelette init --agent-cmd "gemini chat -p"`

## Project Knowledge

-   **Rust Support**: Native support is available via `tree_sitter_rust`.
-   **Markdown Support**: Native support is available for semantic header-based chunking.
-   **Definitions DB**: Always implement `extract_definitions` in your plugins to enable exact-symbol lookup (`towelette_lookup` and `towelette_goto_definition`).
