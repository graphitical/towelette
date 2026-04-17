# tests/test_server.py
from __future__ import annotations

import textwrap
from pathlib import Path

import chromadb
import pytest

from towelette.embed import get_embedding_function


@pytest.fixture
def server_env(tmp_path: Path):
    """Set up a .towelette directory with a small index for testing the server."""
    from towelette.config import init_towelette_dir, save_library_config
    from towelette.index import index_python_source

    d = init_towelette_dir(tmp_path)

    lib_dir = d / "repos" / "testlib"
    lib_dir.mkdir(parents=True)
    (lib_dir / "core.py").write_text(textwrap.dedent('''\
        """Test library core module."""

        class Widget:
            """A test widget."""

            def activate(self):
                """Activate the widget."""
                pass

            def deactivate(self):
                """Deactivate the widget."""
                pass

        def create_widget(name: str) -> Widget:
            """Factory function for widgets."""
            return Widget()
    '''))

    client = chromadb.PersistentClient(path=str(d / "chroma"))
    db_path = d / "definitions.db"
    index_python_source(
        client=client,
        collection_name="testlib_code",
        source="testlib",
        source_paths=[lib_dir],
        db_path=db_path,
        version="1.0.0",
    )

    save_library_config(d, "testlib", {
        "collection": "testlib_code",
        "version": "1.0.0",
        "strategy": "python_ast",
        "source_paths": ["repos/testlib"],
    })

    return tmp_path, d


class TestCreateServer:
    def test_creates_mcp_server(self, server_env):
        from towelette.server import create_server

        project_root, towelette_dir = server_env
        server = create_server(towelette_dir)
        assert server is not None


class TestSearchTool:
    @pytest.mark.asyncio
    async def test_search_tool(self, server_env):
        from towelette.server import _do_search

        project_root, towelette_dir = server_env
        result = await _do_search(towelette_dir, query="widget", limit=5)
        assert "Widget" in result or "widget" in result.lower()


class TestLookupTool:
    @pytest.mark.asyncio
    async def test_lookup_tool(self, server_env):
        from towelette.server import _do_lookup

        project_root, towelette_dir = server_env
        result = await _do_lookup(towelette_dir, name="Widget")
        assert "Widget" in result


class TestGotoDefinitionTool:
    @pytest.mark.asyncio
    async def test_goto_definition(self, server_env):
        from towelette.server import _do_goto_definition

        project_root, towelette_dir = server_env
        result = await _do_goto_definition(towelette_dir, symbol="Widget")
        assert "Widget" in result
        assert "core.py" in result


class TestIndexStatusTool:
    @pytest.mark.asyncio
    async def test_index_status(self, server_env):
        from towelette.server import _do_index_status

        project_root, towelette_dir = server_env
        result = await _do_index_status(towelette_dir)
        assert "testlib" in result
