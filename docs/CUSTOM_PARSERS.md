# Writing Custom Parsers for Towelette

If Towelette encounters a language it doesn't support natively (like KCL), you can author a custom parser plugin. Towelette will dynamically load and use these plugins during the indexing phase.

## Plugin Location

Custom plugins should be placed in your project's `.towelette/plugins/` directory.
The filename must follow the pattern: `<strategy>_plugin.py`.

Example: If your scout report recommends `strategy = "kcl"`, the plugin should be named `.towelette/plugins/kcl_plugin.py`.

## Plugin Interface

A Towelette plugin must implement at least `parse_file`.

```python
from pathlib import Path
from typing import Generator

def parse_file(file_path: Path) -> Generator[dict, None, None]:
    """
    Parse a file into semantic chunks.
    
    Yields dicts with:
    - content (str): The text content to index.
    - class_name (str): A name for the chunk (e.g. function name).
    - chunk_type (str): The type of chunk (e.g. "function", "class").
    - line (int): Starting line number.
    - symbols (str, optional): Comma-separated list of symbols in this chunk.
    """
    # Your parsing logic here
    pass

def extract_definitions(file_path: Path, source: str) -> list[tuple]:
    """
    (Optional) Extract symbols for the exact-lookup database.
    
    Returns list of tuples: 
    (source, symbol, qualified_name, file_path, line, kind, containing_type)
    """
    # Your symbol extraction logic here
    return []
```

## Tips for Agents

1. **Identify Analogs**: If the language is similar to JavaScript, use a JavaScript-like regex or the built-in `ast` module if it's Python-based.
2. **Chunk at Definitions**: RAG works best when chunks correspond to logical units like functions or classes.
3. **Capture Comments**: Always try to include docstrings or preceding comments in the chunk content.
4. **Use `tree-sitter`**: If a tree-sitter grammar exists for the language, you can import `tree_sitter` inside your plugin.
