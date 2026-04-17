from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from towelette.models import DependencyCandidate, ScoutReport, UpstreamDependency


@pytest.fixture
def project_with_lib(tmp_path: Path) -> tuple[Path, Path]:
    """Set up a project with a .towelette dir and a fake library to index."""
    from towelette.config import init_towelette_dir

    project_root = tmp_path / "project"
    project_root.mkdir()
    d = init_towelette_dir(project_root)

    lib_dir = d / "repos" / "testlib"
    lib_dir.mkdir(parents=True)
    (lib_dir / "core.py").write_text(textwrap.dedent('''\
        """Core module."""

        class Engine:
            """Main engine class."""
            def start(self):
                pass
            def stop(self):
                pass
    '''))
    return project_root, d


class TestIndexFromReports:
    def test_indexes_python_library(self, project_with_lib):
        from towelette.orchestrator import index_from_reports

        project_root, towelette_dir = project_with_lib
        reports = [
            ScoutReport(
                library="testlib",
                version="1.0.0",
                strategy="python_ast",
                source_paths=["repos/testlib"],
            ),
        ]
        results = index_from_reports(towelette_dir, reports)
        assert "testlib" in results
        assert results["testlib"] > 0

    def test_updates_config(self, project_with_lib):
        from towelette.config import load_config
        from towelette.orchestrator import index_from_reports

        project_root, towelette_dir = project_with_lib
        reports = [
            ScoutReport(
                library="testlib",
                version="1.0.0",
                strategy="python_ast",
                source_paths=["repos/testlib"],
            ),
        ]
        index_from_reports(towelette_dir, reports)

        config = load_config(towelette_dir)
        assert "testlib" in config["libraries"]


class TestIndexProject:
    def test_indexes_project_source(self, project_with_lib):
        from towelette.orchestrator import index_project

        project_root, towelette_dir = project_with_lib
        (project_root / "app.py").write_text(textwrap.dedent('''\
            """App module."""
            class App:
                def run(self):
                    pass
        '''))

        count = index_project(project_root, towelette_dir)
        assert count > 0


class TestWriteMcpConfig:
    def test_writes_claude_settings(self, project_with_lib):
        from towelette.orchestrator import write_mcp_config

        project_root, towelette_dir = project_with_lib
        write_mcp_config(project_root)

        settings_path = project_root / ".claude" / "settings.json"
        assert settings_path.exists()

        import json
        settings = json.loads(settings_path.read_text())
        assert "mcpServers" in settings
        assert "towelette" in settings["mcpServers"]


def _make_mock_proc(stdout: str, returncode: int = 0, stderr_lines: list[str] | None = None):
    """Build a mock Popen process for scout tests."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.stderr = iter(stderr_lines or [])
    proc.communicate.return_value = (stdout, "")
    return proc


class TestDispatchOneScout:
    def test_parses_successful_subprocess(self):
        from towelette.orchestrator import _dispatch_one_scout

        candidate = DependencyCandidate(name="mylib", version="1.0.0", repo_url="https://github.com/user/mylib")
        toml_output = textwrap.dedent("""\
            [report]
            library = "mylib"
            strategy = "python_ast"
            source_paths = ["mylib/"]
            estimated_chunks = 50
            notes = "Simple Python lib"
        """)

        mock_proc = _make_mock_proc(stdout=toml_output, returncode=0)
        with patch("towelette.orchestrator.subprocess.Popen", return_value=mock_proc):
            report = _dispatch_one_scout(candidate, Path("/tmp/repos"), [])

        assert report.library == "mylib"
        assert report.strategy == "python_ast"
        assert report.error is None

    def test_returns_error_on_subprocess_failure(self):
        from towelette.orchestrator import _dispatch_one_scout

        candidate = DependencyCandidate(name="mylib", version="1.0.0")

        mock_proc = _make_mock_proc(stdout="", returncode=1, stderr_lines=["something broke\n"])
        with patch("towelette.orchestrator.subprocess.Popen", return_value=mock_proc):
            report = _dispatch_one_scout(candidate, Path("/tmp/repos"), [])

        assert report.error is not None

    def test_returns_error_when_claude_not_found(self):
        from towelette.orchestrator import _dispatch_one_scout

        candidate = DependencyCandidate(name="mylib")

        with patch("towelette.orchestrator.subprocess.Popen", side_effect=FileNotFoundError):
            report = _dispatch_one_scout(candidate, Path("/tmp/repos"), [])

        assert report.error is not None
        assert "claude CLI not found" in report.error


class TestRunScouts:
    def _make_towelette_dir(self, tmp_path: Path, upstream_chase: bool = False) -> Path:
        from towelette.config import init_towelette_dir
        project_root = tmp_path / "project"
        project_root.mkdir()
        d = init_towelette_dir(project_root)
        if upstream_chase:
            config_path = d / "config.toml"
            config_path.write_text("[settings]\nupstream_chase = true\n")
        return d

    def test_dispatches_scouts_in_parallel(self, tmp_path: Path):
        from towelette.orchestrator import run_scouts

        towelette_dir = self._make_towelette_dir(tmp_path, upstream_chase=False)
        candidates = [
            DependencyCandidate(name="trimesh", version="4.8.2"),
            DependencyCandidate(name="mylib", version="1.0.0"),
        ]

        trimesh_report = ScoutReport(library="trimesh", strategy="python_ast", source_paths=["trimesh/"], estimated_chunks=800)
        mylib_report = ScoutReport(library="mylib", strategy="python_ast", source_paths=["mylib/"], estimated_chunks=50)

        def fake_dispatch(candidate, repos_dir, imports):
            if candidate.name == "trimesh":
                return trimesh_report
            return mylib_report

        with patch("towelette.orchestrator.asyncio.run", side_effect=lambda coro: candidates), \
             patch("towelette.orchestrator._dispatch_one_scout", side_effect=fake_dispatch):
            reports = run_scouts(towelette_dir, candidates)

        assert len(reports) == 2
        names = {r.library for r in reports}
        assert "trimesh" in names
        assert "mylib" in names

    def test_chases_recommended_upstream_deps(self, tmp_path: Path):
        from towelette.orchestrator import run_scouts

        towelette_dir = self._make_towelette_dir(tmp_path, upstream_chase=True)
        candidates = [
            DependencyCandidate(name="potpourri3d", version="1.4.0"),
        ]

        upstream_dep = UpstreamDependency(
            library="geometry_central",
            repo="https://github.com/nmwsharp/geometry-central",
            reason="C++ bindings",
            significance="high",
            recommended=True,
        )
        potpourri_report = ScoutReport(
            library="potpourri3d",
            strategy="python_ast + tree_sitter_cpp",
            source_paths=["src/"],
            estimated_chunks=120,
            upstream_dependencies=[upstream_dep],
        )
        upstream_report = ScoutReport(
            library="geometry_central",
            strategy="tree_sitter_cpp",
            source_paths=["src/"],
            estimated_chunks=500,
        )

        call_count = {"n": 0}

        def fake_dispatch(candidate, repos_dir, imports, model="haiku"):
            call_count["n"] += 1
            if candidate.name == "potpourri3d":
                return potpourri_report
            return upstream_report

        upstream_candidate = DependencyCandidate(
            name="geometry_central",
            repo_url="https://github.com/nmwsharp/geometry-central",
        )
        asyncio_call = {"n": 0}

        def fake_asyncio_run(coro):
            asyncio_call["n"] += 1
            if asyncio_call["n"] == 1:
                return candidates
            return [upstream_candidate]

        with patch("towelette.orchestrator.asyncio.run", side_effect=fake_asyncio_run), \
             patch("towelette.orchestrator._dispatch_one_scout", side_effect=fake_dispatch):
            reports = run_scouts(towelette_dir, candidates)

        assert call_count["n"] == 2
        names = {r.library for r in reports}
        assert "potpourri3d" in names
        assert "geometry_central" in names

    def test_skips_non_recommended_upstreams(self, tmp_path: Path):
        from towelette.orchestrator import run_scouts

        towelette_dir = self._make_towelette_dir(tmp_path, upstream_chase=True)
        candidates = [
            DependencyCandidate(name="somelib", version="1.0.0"),
        ]

        upstream_dep = UpstreamDependency(
            library="low_prio_lib",
            significance="low",
            recommended=False,
        )
        somelib_report = ScoutReport(
            library="somelib",
            strategy="python_ast",
            source_paths=["src/"],
            estimated_chunks=100,
            upstream_dependencies=[upstream_dep],
        )

        call_count = {"n": 0}

        def fake_dispatch(candidate, repos_dir, imports, model="haiku"):
            call_count["n"] += 1
            return somelib_report

        with patch("towelette.orchestrator.asyncio.run", side_effect=lambda coro: candidates), \
             patch("towelette.orchestrator._dispatch_one_scout", side_effect=fake_dispatch):
            reports = run_scouts(towelette_dir, candidates)

        assert call_count["n"] == 1
        assert len(reports) == 1

    def test_skips_skiplist_libraries_in_upstream_deps(self, tmp_path: Path):
        """Upstream deps on the DEFAULT_SKIPLIST must not be scouted or indexed."""
        from towelette.orchestrator import run_scouts

        towelette_dir = self._make_towelette_dir(tmp_path, upstream_chase=True)
        candidates = [
            DependencyCandidate(name="somelib", version="1.0.0"),
        ]

        # pydantic is on DEFAULT_SKIPLIST — scout recommends it as upstream
        upstream_dep = UpstreamDependency(
            library="pydantic",
            significance="high",
            recommended=True,
        )
        somelib_report = ScoutReport(
            library="somelib",
            strategy="python_ast",
            source_paths=["src/"],
            estimated_chunks=100,
            upstream_dependencies=[upstream_dep],
        )

        call_count = {"n": 0}

        def fake_dispatch(candidate, repos_dir, imports, model="haiku"):
            call_count["n"] += 1
            return somelib_report

        with patch("towelette.orchestrator.asyncio.run", side_effect=lambda coro: candidates), \
             patch("towelette.orchestrator._dispatch_one_scout", side_effect=fake_dispatch):
            reports = run_scouts(towelette_dir, candidates)

        # pydantic must not have triggered a scout dispatch
        assert call_count["n"] == 1
        names = {r.library for r in reports}
        assert "pydantic" not in names
