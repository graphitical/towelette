# tests/test_e2e.py
from __future__ import annotations

import asyncio
import textwrap
from pathlib import Path

import pytest
from typer.testing import CliRunner


@pytest.fixture
def full_project(tmp_path: Path) -> Path:
    """Create a realistic project for e2e testing."""
    project = tmp_path / "my-cad-project"
    project.mkdir()

    (project / "pyproject.toml").write_text(textwrap.dedent("""\
        [project]
        name = "my-cad-project"
        version = "0.1.0"
        dependencies = [
            "numpy>=1.24.0",
            "pydantic>=2.0.0",
        ]
    """))

    src = project / "src"
    src.mkdir()
    (src / "__init__.py").write_text("")
    (src / "geometry.py").write_text(textwrap.dedent('''\
        """Geometry processing module."""

        class BoundingBox:
            """Axis-aligned bounding box."""

            def __init__(self, min_pt, max_pt):
                self.min_pt = min_pt
                self.max_pt = max_pt

            def volume(self):
                """Compute the volume of the bounding box."""
                dx = self.max_pt[0] - self.min_pt[0]
                dy = self.max_pt[1] - self.min_pt[1]
                dz = self.max_pt[2] - self.min_pt[2]
                return dx * dy * dz

            def contains(self, point):
                """Check if a point is inside the bounding box."""
                for i in range(3):
                    if point[i] < self.min_pt[i] or point[i] > self.max_pt[i]:
                        return False
                return True


        class MeshData:
            """Container for mesh vertices and faces."""

            def __init__(self, vertices, faces):
                self.vertices = vertices
                self.faces = faces

            def face_count(self):
                return len(self.faces)


        def compute_centroid(points):
            """Compute the centroid of a set of points."""
            n = len(points)
            return tuple(sum(p[i] for p in points) / n for i in range(3))
    '''))

    return project


def test_full_pipeline(full_project: Path):
    """End-to-end: init -> status -> search."""
    from towelette.cli import app

    runner = CliRunner()

    # 1. Init
    result = runner.invoke(app, ["init", str(full_project), "--skip-scouts"])
    assert result.exit_code == 0
    assert (full_project / ".towelette").is_dir()
    assert "project (local)" in result.output

    # 2. Status
    result = runner.invoke(app, ["status", "--path", str(full_project)])
    assert result.exit_code == 0
    assert "project" in result.output

    # 3. Search via internal API
    from towelette.config import find_towelette_dir
    from towelette.server import _do_search, _do_lookup, _do_goto_definition

    towelette_dir = find_towelette_dir(full_project)

    search_result = asyncio.run(_do_search(towelette_dir, query="bounding box volume"))
    assert "BoundingBox" in search_result

    lookup_result = asyncio.run(_do_lookup(towelette_dir, name="BoundingBox"))
    assert "BoundingBox" in lookup_result
    assert "volume" in lookup_result

    goto_result = asyncio.run(_do_goto_definition(towelette_dir, symbol="BoundingBox"))
    assert "BoundingBox" in goto_result
    assert "geometry.py" in goto_result


def test_reset_and_reinit(full_project: Path):
    """Test that reset + re-init works cleanly."""
    from towelette.cli import app

    runner = CliRunner()

    runner.invoke(app, ["init", str(full_project), "--skip-scouts"])
    assert (full_project / ".towelette").is_dir()

    result = runner.invoke(app, ["reset", "--path", str(full_project)], input="y\n")
    assert result.exit_code == 0
    assert not (full_project / ".towelette").is_dir()

    # Clear ChromaDB's class-level system cache so the re-init creates a fresh client
    import chromadb.api.client as _chroma_client
    _chroma_client.Client.clear_system_cache()

    result = runner.invoke(app, ["init", str(full_project), "--skip-scouts"])
    assert result.exit_code == 0
    assert (full_project / ".towelette").is_dir()
