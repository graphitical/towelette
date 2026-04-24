from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from typer.testing import CliRunner


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def project_with_deps(tmp_path: Path) -> Path:
    """Create a project directory with a pyproject.toml."""
    (tmp_path / "pyproject.toml").write_text(textwrap.dedent("""\
        [project]
        name = "test-project"
        version = "0.1.0"
        dependencies = [
            "pythonocc-core>=7.9.0",
            "numpy>=1.24.0",
        ]
    """))
    (tmp_path / "main.py").write_text("from OCC.Core.gp import gp_Pnt\n")
    return tmp_path


class TestInitCommand:
    def test_init_creates_towelette_dir(self, runner, project_with_deps):
        from towelette.cli import app

        result = runner.invoke(app, ["init", str(project_with_deps), "--skip-scouts"])
        assert result.exit_code == 0
        assert (project_with_deps / ".towelette").is_dir()
        assert (project_with_deps / ".towelette" / "config.toml").is_file()

    def test_init_runs_discovery(self, runner, project_with_deps):
        from towelette.cli import app

        result = runner.invoke(app, ["init", str(project_with_deps), "--skip-scouts"])
        assert result.exit_code == 0
        assert "pythonocc-core" in result.output or "pythonocc" in result.output


class TestStatusCommand:
    def test_status_without_index(self, runner, tmp_path: Path):
        from towelette.cli import app

        result = runner.invoke(app, ["status", "--path", str(tmp_path)])
        assert result.exit_code == 0
        assert "no .towelette" in result.output.lower() or "not found" in result.output.lower() or "no collections" in result.output.lower()

    def test_status_with_index(self, runner, project_with_deps):
        from towelette.cli import app

        runner.invoke(app, ["init", str(project_with_deps), "--skip-scouts"])
        result = runner.invoke(app, ["status", "--path", str(project_with_deps)])
        assert result.exit_code == 0


class TestInitIntegration:
    def test_init_with_project_indexing(self, runner, project_with_deps):
        from towelette.cli import app
        from towelette.config import find_towelette_dir
        import chromadb

        result = runner.invoke(app, ["init", str(project_with_deps), "--skip-scouts"])
        assert result.exit_code == 0

        towelette_dir = find_towelette_dir(project_with_deps)
        assert towelette_dir is not None

        client = chromadb.PersistentClient(path=str(towelette_dir / "chroma"))
        collections = [c.name for c in client.list_collections()]
        assert "project_code" in collections

    def test_init_writes_mcp_config(self, runner, project_with_deps):
        from towelette.cli import app
        import json

        result = runner.invoke(app, ["init", str(project_with_deps), "--skip-scouts"])
        assert result.exit_code == 0

        # .mcp.json is always written
        mcp_json_path = project_with_deps / ".mcp.json"
        assert mcp_json_path.exists()
        config = json.loads(mcp_json_path.read_text())
        assert "mcpServers" in config
        assert "towelette" in config["mcpServers"]

        # .claude/ is NOT created if it didn't already exist
        assert not (project_with_deps / ".claude").exists()


class TestResetCommand:
    def test_reset_removes_towelette_dir(self, runner, project_with_deps):
        from towelette.cli import app

        runner.invoke(app, ["init", str(project_with_deps), "--skip-scouts"])
        assert (project_with_deps / ".towelette").is_dir()

        result = runner.invoke(app, ["reset", "--path", str(project_with_deps)], input="y\n")
        assert result.exit_code == 0
        assert not (project_with_deps / ".towelette").is_dir()
