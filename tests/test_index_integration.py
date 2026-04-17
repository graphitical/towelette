# tests/test_index_integration.py
from __future__ import annotations

from pathlib import Path

import chromadb
import pytest

from towelette.embed import get_embedding_function


@pytest.fixture
def chroma_client(tmp_path: Path):
    return chromadb.PersistentClient(path=str(tmp_path / "chroma"))


class TestIndexPythonLibrary:
    def test_indexes_python_files(self, chroma_client, sample_python_module: Path, tmp_path: Path):
        from towelette.index import index_python_source

        db_path = tmp_path / "definitions.db"
        count = index_python_source(
            client=chroma_client,
            collection_name="test_lib",
            source="test",
            source_paths=[sample_python_module.parent],
            db_path=db_path,
            version="1.0.0",
        )
        assert count > 0

        collection = chroma_client.get_collection("test_lib", embedding_function=get_embedding_function())
        assert collection.count() > 0

    def test_stores_metadata(self, chroma_client, sample_python_module: Path, tmp_path: Path):
        from towelette.index import index_python_source

        db_path = tmp_path / "definitions.db"
        index_python_source(
            client=chroma_client,
            collection_name="test_lib",
            source="test",
            source_paths=[sample_python_module.parent],
            db_path=db_path,
            version="1.0.0",
        )

        collection = chroma_client.get_collection("test_lib", embedding_function=get_embedding_function())
        result = collection.get(include=["metadatas"])
        assert all("source" in m for m in result["metadatas"])
        assert all("chunk_type" in m for m in result["metadatas"])

    def test_populates_definitions_db(self, chroma_client, sample_python_module: Path, tmp_path: Path):
        from towelette.definitions import lookup_symbol
        from towelette.index import index_python_source

        db_path = tmp_path / "definitions.db"
        index_python_source(
            client=chroma_client,
            collection_name="test_lib",
            source="test",
            source_paths=[sample_python_module.parent],
            db_path=db_path,
            version="1.0.0",
        )

        results = lookup_symbol(db_path, "MeshProcessor")
        assert len(results) >= 1


class TestIndexCppSource:
    def test_indexes_cpp_headers(self, chroma_client, sample_cpp_header: Path, tmp_path: Path):
        from towelette.index import index_cpp_source

        db_path = tmp_path / "definitions.db"
        count = index_cpp_source(
            client=chroma_client,
            collection_name="test_cpp",
            source="occt",
            source_paths=[sample_cpp_header.parent],
            db_path=db_path,
            version="7.9.0",
        )
        assert count > 0

    def test_populates_definitions_db(self, chroma_client, sample_cpp_header: Path, tmp_path: Path):
        from towelette.definitions import lookup_symbol
        from towelette.index import index_cpp_source

        db_path = tmp_path / "definitions.db"
        index_cpp_source(
            client=chroma_client,
            collection_name="test_cpp",
            source="occt",
            source_paths=[sample_cpp_header.parent],
            db_path=db_path,
            version="7.9.0",
        )

        results = lookup_symbol(db_path, "BRepPrimAPI_MakeBox")
        assert len(results) >= 1
