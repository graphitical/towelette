from __future__ import annotations

import asyncio
import textwrap
from pathlib import Path

import pytest

from towelette.models import DependencyCandidate


def _network_available() -> bool:
    """Check if network is available by attempting a quick connection."""
    try:
        import httpx
        with httpx.Client(timeout=3) as client:
            client.get("https://pypi.org")
        return True
    except Exception:
        return False


requires_network = pytest.mark.skipif(
    not _network_available(),
    reason="Network not available",
)


class TestParsePyproject:
    def test_parses_dependencies(self, sample_pyproject: Path):
        from towelette.discover import parse_pyproject

        project_root = sample_pyproject.parent
        deps = parse_pyproject(project_root)
        names = {d.name for d in deps}
        assert "pythonocc-core" in names
        assert "trimesh" in names
        assert "numpy" in names
        assert "pydantic" in names

    def test_includes_optional_deps(self, sample_pyproject: Path):
        from towelette.discover import parse_pyproject

        project_root = sample_pyproject.parent
        deps = parse_pyproject(project_root)
        names = {d.name for d in deps}
        assert "potpourri3d" in names
        assert "pytest" in names

    def test_extracts_version(self, sample_pyproject: Path):
        from towelette.discover import parse_pyproject

        project_root = sample_pyproject.parent
        deps = parse_pyproject(project_root)
        by_name = {d.name: d for d in deps}
        assert by_name["pythonocc-core"].version == "7.9.0"

    def test_returns_empty_when_no_file(self, tmp_path: Path):
        from towelette.discover import parse_pyproject

        deps = parse_pyproject(tmp_path)
        assert deps == []


class TestParseRequirements:
    def test_parses_requirements_txt(self, sample_requirements: Path):
        from towelette.discover import parse_requirements

        project_root = sample_requirements.parent
        deps = parse_requirements(project_root)
        names = {d.name for d in deps}
        assert "pythonocc-core" in names
        assert "trimesh" in names
        assert "potpourri3d" in names

    def test_skips_comments(self, sample_requirements: Path):
        from towelette.discover import parse_requirements

        project_root = sample_requirements.parent
        deps = parse_requirements(project_root)
        names = {d.name for d in deps}
        assert not any("#" in n for n in names)


class TestParseEnvironmentYml:
    def test_parses_conda_deps(self, sample_environment_yml: Path):
        yaml = pytest.importorskip("yaml")
        from towelette.discover import parse_environment_yml

        project_root = sample_environment_yml.parent
        deps = parse_environment_yml(project_root)
        names = {d.name for d in deps}
        assert "pythonocc-core" in names

    def test_parses_pip_deps_inside_conda(self, sample_environment_yml: Path):
        yaml = pytest.importorskip("yaml")
        from towelette.discover import parse_environment_yml

        project_root = sample_environment_yml.parent
        deps = parse_environment_yml(project_root)
        names = {d.name for d in deps}
        assert "trimesh" in names
        assert "potpourri3d" in names


class TestScanImports:
    def test_finds_imports(self, sample_python_files: Path):
        from towelette.discover import scan_imports

        imports = scan_imports(sample_python_files)
        assert "numpy" in imports
        assert "trimesh" in imports
        assert "potpourri3d" in imports

    def test_finds_occ_imports(self, sample_python_files: Path):
        from towelette.discover import scan_imports

        imports = scan_imports(sample_python_files)
        assert "OCC" in imports

    def test_ignores_stdlib(self, sample_python_files: Path):
        from towelette.discover import scan_imports

        imports = scan_imports(sample_python_files)
        assert "json" not in imports
        assert "pathlib" not in imports


class TestDiscoverDeps:
    def test_full_discovery(self, sample_pyproject: Path, sample_python_files: Path):
        from towelette.discover import discover_deps

        project_root = sample_pyproject.parent
        src = project_root / "src"
        src.mkdir(exist_ok=True)
        (src / "main.py").write_text(textwrap.dedent("""\
            import trimesh
            from potpourri3d import MeshHeatSolver
        """))

        result = discover_deps(project_root)
        candidate_names = {c.name for c in result.candidates}
        assert "trimesh" in candidate_names
        assert "potpourri3d" in candidate_names
        assert "numpy" in result.skipped
        assert "pydantic" in result.skipped

    def test_discovery_reports_dep_files(self, sample_pyproject: Path):
        from towelette.discover import discover_deps

        result = discover_deps(sample_pyproject.parent)
        assert "pyproject.toml" in result.dep_files_found


class TestResolveRepoUrl:
    @requires_network
    @pytest.mark.asyncio
    async def test_resolve_known_package(self):
        from towelette.discover import resolve_repo_url

        url = await resolve_repo_url("requests")
        assert url is not None
        assert "github.com" in url

    @requires_network
    @pytest.mark.asyncio
    async def test_resolve_nonexistent_package(self):
        from towelette.discover import resolve_repo_url

        url = await resolve_repo_url("this-package-definitely-does-not-exist-xyz123")
        assert url is None

    @requires_network
    def test_resolve_candidates(self):
        from towelette.discover import resolve_candidates

        candidates = [
            DependencyCandidate(name="requests"),
        ]
        resolved = asyncio.run(resolve_candidates(candidates))
        assert resolved[0].repo_url is not None
