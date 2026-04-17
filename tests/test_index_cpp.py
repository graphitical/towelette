from __future__ import annotations

import textwrap
from pathlib import Path

import pytest


class TestParseCppHeader:
    def test_extracts_class(self, sample_cpp_header: Path):
        from towelette.index import parse_cpp_header

        chunks = list(parse_cpp_header(sample_cpp_header))
        class_chunks = [c for c in chunks if c["chunk_type"] in ("class", "class_section")]
        assert len(class_chunks) >= 1
        names = {c["class_name"] for c in class_chunks}
        assert "BRepPrimAPI_MakeBox" in names

    def test_class_content_includes_methods(self, sample_cpp_header: Path):
        from towelette.index import parse_cpp_header

        chunks = list(parse_cpp_header(sample_cpp_header))
        makebox_chunks = [c for c in chunks if c["class_name"] == "BRepPrimAPI_MakeBox"]
        all_content = " ".join(c["content"] for c in makebox_chunks)
        assert "Shell" in all_content
        assert "Solid" in all_content

    def test_includes_preceding_comment(self, sample_cpp_header: Path):
        from towelette.index import parse_cpp_header

        chunks = list(parse_cpp_header(sample_cpp_header))
        makebox_chunks = [c for c in chunks if c["class_name"] == "BRepPrimAPI_MakeBox"]
        all_content = " ".join(c["content"] for c in makebox_chunks)
        assert "Builds a box solid" in all_content

    def test_chunk_has_required_fields(self, sample_cpp_header: Path):
        from towelette.index import parse_cpp_header

        chunks = list(parse_cpp_header(sample_cpp_header))
        for chunk in chunks:
            assert "content" in chunk
            assert "class_name" in chunk
            assert "chunk_type" in chunk
            assert "line" in chunk


class TestExtractCppDefinitions:
    def test_extracts_class(self, sample_cpp_header: Path):
        from towelette.index import extract_cpp_definitions

        defs = extract_cpp_definitions(sample_cpp_header, source="occt")
        class_defs = [d for d in defs if d[5] == "class"]
        assert any(d[1] == "BRepPrimAPI_MakeBox" for d in class_defs)

    def test_extracts_methods(self, sample_cpp_header: Path):
        from towelette.index import extract_cpp_definitions

        defs = extract_cpp_definitions(sample_cpp_header, source="occt")
        method_defs = [d for d in defs if d[5] == "method"]
        method_names = {d[1] for d in method_defs}
        assert "Shell" in method_names
        assert "Solid" in method_names


class TestSplitLargeClass:
    def test_splits_by_access_specifiers(self):
        from towelette.index import split_class_by_access_specifiers

        content = textwrap.dedent("""\
            class BigClass : public Base
            {
            public:
                void method_a();
                void method_b();
                void method_c();
            protected:
                int protected_field;
            private:
                int private_field;
            };
        """)
        sections = split_class_by_access_specifiers("BigClass", content, threshold=10)
        assert len(sections) >= 2
