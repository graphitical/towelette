# tests/test_search.py
from __future__ import annotations

from pathlib import Path

import chromadb
import pytest

from towelette.embed import get_embedding_function


@pytest.fixture
def indexed_collection(tmp_path: Path):
    """Create a ChromaDB collection with some test data."""
    client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
    ef = get_embedding_function()
    collection = client.get_or_create_collection(
        name="test_lib",
        embedding_function=ef,
        metadata={"source": "test", "version": "1.0.0"},
    )
    collection.add(
        documents=[
            "class MeshProcessor: processes mesh data, compute normals, simplify",
            "class BRepBuilder: builds boundary representation solids, boolean operations",
            "def load_mesh(path): loads a mesh from file, returns MeshProcessor instance",
        ],
        ids=["test_0", "test_1", "test_2"],
        metadatas=[
            {"source": "test", "class_name": "MeshProcessor", "chunk_type": "class", "file_path": "mesh.py", "symbols": "compute_normals,simplify"},
            {"source": "test", "class_name": "BRepBuilder", "chunk_type": "class", "file_path": "brep.py", "symbols": "build,fuse"},
            {"source": "test", "class_name": "load_mesh", "chunk_type": "function", "file_path": "mesh.py", "symbols": "load_mesh"},
        ],
    )
    return client, ef


class TestSemanticSearch:
    def test_search_returns_results(self, indexed_collection):
        from towelette.search import semantic_search

        client, ef = indexed_collection
        results = semantic_search(client, "mesh processing", limit=3)
        assert len(results) > 0

    def test_search_ranks_relevant_first(self, indexed_collection):
        from towelette.search import semantic_search

        client, ef = indexed_collection
        results = semantic_search(client, "mesh normals", limit=3)
        assert results[0]["class_name"] == "MeshProcessor"

    def test_search_with_scope(self, indexed_collection):
        from towelette.search import semantic_search

        client, ef = indexed_collection
        results = semantic_search(client, "mesh", scope="test", limit=3)
        assert all(r["source"] == "test" for r in results)

    def test_search_respects_limit(self, indexed_collection):
        from towelette.search import semantic_search

        client, ef = indexed_collection
        results = semantic_search(client, "mesh", limit=1)
        assert len(results) == 1

    def test_search_returns_empty_for_no_match(self, tmp_path: Path):
        from towelette.search import semantic_search

        client = chromadb.PersistentClient(path=str(tmp_path / "chroma_empty"))
        results = semantic_search(client, "anything")
        assert results == []


class TestExactLookup:
    def test_lookup_by_class_name(self, indexed_collection):
        from towelette.search import exact_lookup

        client, ef = indexed_collection
        results = exact_lookup(client, "MeshProcessor")
        assert len(results) >= 1
        assert results[0]["class_name"] == "MeshProcessor"

    def test_lookup_by_symbol(self, indexed_collection):
        from towelette.search import exact_lookup

        client, ef = indexed_collection
        results = exact_lookup(client, "compute_normals")
        assert len(results) >= 1

    def test_lookup_not_found_falls_back_to_search(self, indexed_collection):
        from towelette.search import exact_lookup

        client, ef = indexed_collection
        results = exact_lookup(client, "mesh")
        assert len(results) >= 1
