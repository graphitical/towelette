"""Indexing strategies -- Python AST and tree-sitter C++."""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Generator

CHUNK_LIMIT = 8000
FALLBACK_LIMIT = 5000


def parse_python_file(file_path: Path) -> Generator[dict, None, None]:
    """Parse a Python file into chunks using the AST.

    Yields dicts with: content, class_name, chunk_type, symbols, line, file_path.
    """
    source = file_path.read_text()
    lines = source.splitlines()

    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError:
        yield {
            "content": source[:FALLBACK_LIMIT],
            "class_name": file_path.stem,
            "chunk_type": "file",
            "symbols": file_path.stem,
            "line": 1,
            "file_path": str(file_path),
        }
        return

    yielded = False
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            start = node.lineno - 1
            end = node.end_lineno or start + 1
            content = "\n".join(lines[start:end])

            methods = []
            for item in ast.walk(node):
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods.append(item.name)

            yield {
                "content": content[:CHUNK_LIMIT],
                "class_name": node.name,
                "chunk_type": "class",
                "symbols": ",".join(methods),
                "line": node.lineno,
                "file_path": str(file_path),
            }
            yielded = True

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.lineno - 1
            end = node.end_lineno or start + 1
            content = "\n".join(lines[start:end])

            yield {
                "content": content[:CHUNK_LIMIT],
                "class_name": node.name,
                "chunk_type": "function",
                "symbols": node.name,
                "line": node.lineno,
                "file_path": str(file_path),
            }
            yielded = True

    # Fall back to whole-file chunk for files with no class/function definitions
    # (e.g. thin wrappers, re-export modules, constants-only files)
    if not yielded and source.strip():
        yield {
            "content": source[:FALLBACK_LIMIT],
            "class_name": file_path.stem,
            "chunk_type": "file",
            "symbols": file_path.stem,
            "line": 1,
            "file_path": str(file_path),
        }


def extract_python_definitions(
    file_path: Path,
    source: str,
    module_prefix: str = "",
) -> list[tuple]:
    """Extract symbol definitions from a Python file for the definitions DB.

    Returns list of tuples: (source, symbol, qualified_name, file_path, line, kind, containing_type)
    """
    text = file_path.read_text()
    try:
        tree = ast.parse(text, filename=str(file_path))
    except SyntaxError:
        return []

    defs: list[tuple] = []
    rel_path = str(file_path)
    prefix = f"{module_prefix}." if module_prefix else ""

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            qualified = f"{prefix}{node.name}"
            defs.append((source, node.name, qualified, rel_path, node.lineno, "class", None))

            for item in ast.iter_child_nodes(node):
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    method_qualified = f"{qualified}.{item.name}"
                    defs.append((source, item.name, method_qualified, rel_path, item.lineno, "method", node.name))

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qualified = f"{prefix}{node.name}"
            defs.append((source, node.name, qualified, rel_path, node.lineno, "function", None))

    return defs


# --- Tree-sitter C++ indexer ---

import re

LARGE_CLASS_THRESHOLD = 3000
TARGET_CHUNK_SIZE = 4000

_cpp_parser = None
_cpp_language = None


def _get_cpp_parser():
    """Lazy-load tree-sitter C++ parser."""
    global _cpp_parser, _cpp_language
    if _cpp_parser is None:
        import tree_sitter_cpp as tscpp
        from tree_sitter import Language, Parser

        _cpp_language = Language(tscpp.language())
        _cpp_parser = Parser(_cpp_language)
    return _cpp_parser, _cpp_language


def _get_preceding_comment(source_bytes: bytes, node) -> str:
    """Extract the comment block immediately before a node."""
    lines = source_bytes[:node.start_byte].decode("utf-8", errors="replace").splitlines()
    comment_lines = []
    for line in reversed(lines):
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("/*") or stripped.startswith("*"):
            comment_lines.insert(0, line)
        elif stripped == "":
            continue
        else:
            break
    return "\n".join(comment_lines)


def split_class_by_access_specifiers(
    class_name: str,
    content: str,
    threshold: int = LARGE_CLASS_THRESHOLD,
) -> list[dict]:
    """Split a large class by public:/protected:/private: sections."""
    if len(content) <= threshold:
        return [{"content": content, "section": "all", "class_name": class_name, "chunk_type": "class"}]

    pattern = re.compile(r"^(public|protected|private)\s*:", re.MULTILINE)
    matches = list(pattern.finditer(content))

    if not matches:
        return [{"content": content[:CHUNK_LIMIT], "section": "all", "class_name": class_name, "chunk_type": "class"}]

    header = content[:matches[0].start()].rstrip()

    sections = []
    for i, match in enumerate(matches):
        section_name = match.group(1)
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        section_content = content[start:end].rstrip()

        chunk_content = f"{header}\n{{\n{section_content}\n}};"
        sections.append({
            "content": chunk_content[:CHUNK_LIMIT],
            "section": section_name,
            "class_name": class_name,
            "chunk_type": "class_section",
        })

    overview = content[:TARGET_CHUNK_SIZE]
    if len(content) > TARGET_CHUNK_SIZE:
        overview += f"\n// ... [{class_name} truncated, {len(content)} chars total]"
    sections.insert(0, {
        "content": overview[:CHUNK_LIMIT],
        "section": "overview",
        "class_name": class_name,
        "chunk_type": "class",
    })

    return sections


def _walk_top_level_nodes(node):
    """Yield top-level declaration nodes, recursing into preprocessor blocks and namespaces."""
    for child in node.children:
        if child.type in ("class_specifier", "struct_specifier", "function_definition", "declaration"):
            yield child
        elif child.type in ("preproc_ifdef", "preproc_if", "preproc_else", "preproc_elif"):
            yield from _walk_top_level_nodes(child)
        elif child.type == "namespace_definition":
            body = child.child_by_field_name("body")
            if body:
                yield from _walk_top_level_nodes(body)


def parse_cpp_header(file_path: Path) -> Generator[dict, None, None]:
    """Parse a C++ header file into chunks using tree-sitter."""
    source = file_path.read_bytes()
    source_text = source.decode("utf-8", errors="replace")

    try:
        parser, language = _get_cpp_parser()
    except (ImportError, Exception):
        yield {
            "content": source_text[:CHUNK_LIMIT],
            "class_name": file_path.stem,
            "chunk_type": "file",
            "line": 1,
            "file_path": str(file_path),
        }
        return

    tree = parser.parse(source)

    for node in _walk_top_level_nodes(tree.root_node):
        if node.type in ("class_specifier", "struct_specifier"):
            name_node = node.child_by_field_name("name")
            class_name = name_node.text.decode() if name_node else file_path.stem

            comment = _get_preceding_comment(source, node)
            content = source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
            full_content = f"{comment}\n{content}" if comment else content

            if len(full_content) > LARGE_CLASS_THRESHOLD:
                for section in split_class_by_access_specifiers(class_name, full_content):
                    section["line"] = node.start_point[0] + 1
                    section["file_path"] = str(file_path)
                    yield section
            else:
                yield {
                    "content": full_content[:CHUNK_LIMIT],
                    "class_name": class_name,
                    "chunk_type": "class",
                    "line": node.start_point[0] + 1,
                    "file_path": str(file_path),
                }

        elif node.type in ("function_definition", "declaration"):
            name = _extract_function_name(node)
            if not name:
                continue

            comment = _get_preceding_comment(source, node)
            content = source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
            full_content = f"{comment}\n{content}" if comment else content

            yield {
                "content": full_content[:CHUNK_LIMIT],
                "class_name": name,
                "chunk_type": "function",
                "line": node.start_point[0] + 1,
                "file_path": str(file_path),
            }


def _extract_function_name(node) -> str | None:
    """Extract the function/declaration name from a tree-sitter node."""
    declarator = node.child_by_field_name("declarator")
    if declarator is None:
        return None

    current = declarator
    while current:
        if current.type in ("identifier", "field_identifier"):
            return current.text.decode()
        if current.type == "qualified_identifier":
            name_node = current.child_by_field_name("name")
            if name_node:
                return name_node.text.decode()
        # For reference_declarator/pointer_declarator, the function_declarator
        # is a regular child (not a named field), so walk children too.
        if current.type in ("reference_declarator", "pointer_declarator"):
            for child in current.children:
                if child.type in ("function_declarator", "identifier", "field_identifier"):
                    current = child
                    break
            else:
                break
            continue
        next_node = (
            current.child_by_field_name("declarator")
            or current.child_by_field_name("name")
        )
        if next_node is None or next_node == current:
            break
        current = next_node

    return None


def extract_cpp_definitions(
    file_path: Path,
    source: str,
) -> list[tuple]:
    """Extract symbol definitions from a C++ header for the definitions DB."""
    file_source = file_path.read_bytes()

    try:
        parser, language = _get_cpp_parser()
    except (ImportError, Exception):
        return []

    tree = parser.parse(file_source)
    defs: list[tuple] = []
    rel_path = str(file_path)

    for node in _walk_top_level_nodes(tree.root_node):
        if node.type in ("class_specifier", "struct_specifier"):
            name_node = node.child_by_field_name("name")
            if not name_node:
                continue
            class_name = name_node.text.decode()
            defs.append((source, class_name, class_name, rel_path, node.start_point[0] + 1, "class", None))

            body = node.child_by_field_name("body")
            if body:
                for child in body.children:
                    if child.type in ("function_definition", "declaration", "field_declaration"):
                        method_name = _extract_function_name(child)
                        if method_name and not method_name.startswith("_"):
                            qualified = f"{class_name}::{method_name}"
                            defs.append((source, method_name, qualified, rel_path, child.start_point[0] + 1, "method", class_name))

        elif node.type in ("function_definition", "declaration"):
            name = _extract_function_name(node)
            if name:
                defs.append((source, name, name, rel_path, node.start_point[0] + 1, "function", None))

    return defs


# --- Index pipeline functions ---

import chromadb

from towelette.definitions import clear_source, create_db, insert_definitions
from towelette.embed import get_embedding_function

BATCH_SIZE = 500


def index_python_source(
    client: chromadb.ClientAPI,
    collection_name: str,
    source: str,
    source_paths: list[Path],
    db_path: Path,
    version: str | None = None,
    file_extensions: tuple[str, ...] = (".py", ".pyi"),
    skip_dirs: set[str] | None = None,
) -> int:
    """Index Python source files into ChromaDB and definitions DB.

    Returns the number of chunks inserted.
    """
    if skip_dirs is None:
        skip_dirs = {"__pycache__", ".git", "test", "tests", "examples", ".venv", "venv"}

    ef = get_embedding_function()
    metadata = {"source": source}
    if version:
        metadata["version"] = version

    collection = client.get_or_create_collection(
        name=collection_name,
        embedding_function=ef,
        metadata=metadata,
    )

    all_docs: list[str] = []
    all_ids: list[str] = []
    all_metadatas: list[dict] = []
    all_definitions: list[tuple] = []

    chunk_idx = 0
    for src_path in source_paths:
        if src_path.is_file():
            py_files = [src_path] if src_path.suffix in file_extensions else []
        else:
            py_files = [
                f for f in src_path.rglob("*")
                if f.suffix in file_extensions
                and not any(part in skip_dirs for part in f.parts)
            ]

        for py_file in sorted(py_files):
            rel_path = str(py_file.relative_to(src_path)) if src_path.is_dir() else py_file.name

            for chunk in parse_python_file(py_file):
                doc_id = f"{source}_{chunk_idx}"
                all_docs.append(chunk["content"])
                all_ids.append(doc_id)
                all_metadatas.append({
                    "source": source,
                    "file_path": rel_path,
                    "class_name": chunk["class_name"],
                    "chunk_type": chunk["chunk_type"],
                    "symbols": chunk.get("symbols", ""),
                })
                chunk_idx += 1

            module_prefix = rel_path.replace("/", ".").removesuffix(".pyi").removesuffix(".py")
            all_definitions.extend(
                extract_python_definitions(py_file, source=source, module_prefix=module_prefix)
            )

    for i in range(0, len(all_docs), BATCH_SIZE):
        batch_end = min(i + BATCH_SIZE, len(all_docs))
        collection.add(
            documents=all_docs[i:batch_end],
            ids=all_ids[i:batch_end],
            metadatas=all_metadatas[i:batch_end],
        )

    if all_definitions:
        conn = create_db(db_path)
        clear_source(conn, source)
        insert_definitions(conn, all_definitions)
        conn.close()

    return len(all_docs)


def index_cpp_source(
    client: chromadb.ClientAPI,
    collection_name: str,
    source: str,
    source_paths: list[Path],
    db_path: Path,
    version: str | None = None,
    file_extensions: tuple[str, ...] = (".hxx", ".h", ".hpp", ".hh", ".cpp", ".cc", ".cxx"),
    skip_dirs: set[str] | None = None,
) -> int:
    """Index C++ header files into ChromaDB and definitions DB.

    Returns the number of chunks inserted.
    """
    if skip_dirs is None:
        skip_dirs = {"test", "tests", "examples", "cmake", "build"}

    ef = get_embedding_function()
    metadata = {"source": source}
    if version:
        metadata["version"] = version

    collection = client.get_or_create_collection(
        name=collection_name,
        embedding_function=ef,
        metadata=metadata,
    )

    all_docs: list[str] = []
    all_ids: list[str] = []
    all_metadatas: list[dict] = []
    all_definitions: list[tuple] = []

    chunk_idx = 0
    for src_path in source_paths:
        if src_path.is_file():
            cpp_files = [src_path] if src_path.suffix in file_extensions else []
        else:
            cpp_files = [
                f for f in src_path.rglob("*")
                if f.suffix in file_extensions
                and not any(part in skip_dirs for part in f.parts)
            ]

        for cpp_file in sorted(cpp_files):
            rel_path = str(cpp_file.relative_to(src_path)) if src_path.is_dir() else cpp_file.name

            for chunk in parse_cpp_header(cpp_file):
                doc_id = f"{source}_{chunk_idx}"
                all_docs.append(chunk["content"])
                all_ids.append(doc_id)
                meta = {
                    "source": source,
                    "file_path": rel_path,
                    "class_name": chunk["class_name"],
                    "chunk_type": chunk["chunk_type"],
                }
                if "section" in chunk:
                    meta["section"] = chunk["section"]
                all_metadatas.append(meta)
                chunk_idx += 1

            all_definitions.extend(extract_cpp_definitions(cpp_file, source=source))

    for i in range(0, len(all_docs), BATCH_SIZE):
        batch_end = min(i + BATCH_SIZE, len(all_docs))
        collection.add(
            documents=all_docs[i:batch_end],
            ids=all_ids[i:batch_end],
            metadatas=all_metadatas[i:batch_end],
        )

    if all_definitions:
        conn = create_db(db_path)
        clear_source(conn, source)
        insert_definitions(conn, all_definitions)
        conn.close()

    return len(all_docs)
