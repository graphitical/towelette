from __future__ import annotations

from pathlib import Path

import pytest


class TestParsePythonFile:
    def test_extracts_classes(self, sample_python_module: Path):
        from towelette.index import parse_python_file

        chunks = list(parse_python_file(sample_python_module))
        class_chunks = [c for c in chunks if c["chunk_type"] == "class"]
        assert len(class_chunks) == 1
        assert class_chunks[0]["class_name"] == "MeshProcessor"
        assert "compute_normals" in class_chunks[0]["content"]
        assert "simplify" in class_chunks[0]["content"]

    def test_extracts_functions(self, sample_python_module: Path):
        from towelette.index import parse_python_file

        chunks = list(parse_python_file(sample_python_module))
        func_chunks = [c for c in chunks if c["chunk_type"] == "function"]
        names = {c["class_name"] for c in func_chunks}
        assert "load_mesh" in names
        assert "_private_helper" in names

    def test_chunk_has_required_fields(self, sample_python_module: Path):
        from towelette.index import parse_python_file

        chunks = list(parse_python_file(sample_python_module))
        for chunk in chunks:
            assert "content" in chunk
            assert "class_name" in chunk
            assert "chunk_type" in chunk
            assert "symbols" in chunk
            assert "line" in chunk

    def test_class_symbols_include_methods(self, sample_python_module: Path):
        from towelette.index import parse_python_file

        chunks = list(parse_python_file(sample_python_module))
        class_chunk = [c for c in chunks if c["class_name"] == "MeshProcessor"][0]
        assert "compute_normals" in class_chunk["symbols"]
        assert "simplify" in class_chunk["symbols"]

    def test_handles_syntax_error(self, tmp_path: Path):
        from towelette.index import parse_python_file

        bad_file = tmp_path / "bad.py"
        bad_file.write_text("def broken(\n")
        chunks = list(parse_python_file(bad_file))
        assert len(chunks) == 1
        assert chunks[0]["chunk_type"] == "file"


class TestExtractPythonDefinitions:
    def test_extracts_class_definition(self, sample_python_module: Path):
        from towelette.index import extract_python_definitions

        defs = extract_python_definitions(sample_python_module, source="test")
        class_defs = [d for d in defs if d[5] == "class"]
        assert any(d[1] == "MeshProcessor" for d in class_defs)

    def test_extracts_method_definitions(self, sample_python_module: Path):
        from towelette.index import extract_python_definitions

        defs = extract_python_definitions(sample_python_module, source="test")
        method_defs = [d for d in defs if d[5] == "method"]
        method_names = {d[1] for d in method_defs}
        assert "compute_normals" in method_names
        assert "simplify" in method_names

    def test_extracts_function_definitions(self, sample_python_module: Path):
        from towelette.index import extract_python_definitions

        defs = extract_python_definitions(sample_python_module, source="test")
        func_defs = [d for d in defs if d[5] == "function"]
        func_names = {d[1] for d in func_defs}
        assert "load_mesh" in func_names

    def test_definition_tuple_format(self, sample_python_module: Path):
        from towelette.index import extract_python_definitions

        defs = extract_python_definitions(sample_python_module, source="test")
        for d in defs:
            assert len(d) == 7
            assert d[0] == "test"
            assert isinstance(d[4], int)
