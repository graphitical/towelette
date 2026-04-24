"""Tests for the pluggable scout backend subsystem.

Covers:
- LocalBackend heuristics (strategy detection, layout, warnings)
- AutoBackend escalation logic
- get_backend() factory
"""
from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from towelette.models import DependencyCandidate, ScoutReport


# =========================================================================== #
# Helpers
# =========================================================================== #


def _make_candidate(name: str = "mylib", repo_url: str | None = "https://github.com/user/mylib") -> DependencyCandidate:
    return DependencyCandidate(name=name, repo_url=repo_url)


def _make_repo(tmp_path: Path, name: str = "mylib") -> tuple[Path, Path]:
    """Create a minimal fake repo directory.  Returns (repos_dir, repo_dir)."""
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    repo_dir = repos_dir / name
    repo_dir.mkdir()
    return repos_dir, repo_dir


# =========================================================================== #
# LocalBackend — strategy detection
# =========================================================================== #


class TestLocalBackendStrategyDetection:
    """Verify that LocalBackend picks the right strategy from directory layout."""

    def _run(self, tmp_path: Path, name: str = "mylib") -> "LocalScoutResult":
        from towelette.backends.local import LocalBackend

        repos_dir, repo_dir = _make_repo(tmp_path, name)
        candidate = _make_candidate(name)

        backend = LocalBackend()
        # Patch git clone to be a no-op (repo_dir already exists)
        return backend.scout_with_confidence(candidate, repos_dir)

    # ---- pure Python ------------------------------------------------------- #

    def test_python_only_gets_python_ast(self, tmp_path: Path):
        repos_dir, repo_dir = _make_repo(tmp_path)
        pkg = repo_dir / "mylib"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "core.py").write_text("class Foo: pass\n")

        from towelette.backends.local import LocalBackend
        result = LocalBackend().scout_with_confidence(_make_candidate(), repos_dir)

        assert result.report.strategy == "python_ast"
        assert result.report.error is None

    def test_python_only_no_cpp_paths(self, tmp_path: Path):
        repos_dir, repo_dir = _make_repo(tmp_path)
        pkg = repo_dir / "mylib"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "utils.py").write_text("pass\n")

        from towelette.backends.local import LocalBackend
        result = LocalBackend().scout_with_confidence(_make_candidate(), repos_dir)

        assert result.report.cpp_paths == []

    # ---- pure C++ ---------------------------------------------------------- #

    def test_cpp_only_gets_tree_sitter_cpp(self, tmp_path: Path):
        repos_dir, repo_dir = _make_repo(tmp_path)
        src = repo_dir / "src"
        src.mkdir()
        (src / "engine.cpp").write_text("int main(){}")
        (src / "engine.h").write_text("")

        from towelette.backends.local import LocalBackend
        result = LocalBackend().scout_with_confidence(_make_candidate(), repos_dir)

        assert result.report.strategy == "tree_sitter_cpp"

    # ---- Python + C++ with binding ----------------------------------------- #

    def test_python_and_cpp_with_pybind11_gets_both(self, tmp_path: Path):
        repos_dir, repo_dir = _make_repo(tmp_path)
        pkg = repo_dir / "mylib"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "wrapper.py").write_text("import _mylib\n")
        src = repo_dir / "src"
        src.mkdir()
        (src / "binding.cpp").write_text("pybind11::module m;")
        (repo_dir / "pyproject.toml").write_text(
            "[build-system]\nrequires = [\"pybind11\"]\n"
        )

        from towelette.backends.local import LocalBackend
        result = LocalBackend().scout_with_confidence(_make_candidate(), repos_dir)

        assert result.report.strategy == "python_ast + tree_sitter_cpp"

    def test_python_and_cpp_without_binding_gets_python_ast_and_warning(self, tmp_path: Path):
        repos_dir, repo_dir = _make_repo(tmp_path)
        pkg = repo_dir / "mylib"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "core.py").write_text("pass\n")
        src = repo_dir / "src_c"
        src.mkdir()
        (src / "internal.cpp").write_text("// internal")

        from towelette.backends.local import LocalBackend
        result = LocalBackend().scout_with_confidence(_make_candidate(), repos_dir)

        assert result.report.strategy == "python_ast"
        assert result.needs_agentic is True
        assert any("binding" in w for w in result.warnings)

    # ---- src-layout -------------------------------------------------------- #

    def test_src_layout_detected(self, tmp_path: Path):
        repos_dir, repo_dir = _make_repo(tmp_path)
        pkg = repo_dir / "src" / "mylib"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("")
        (pkg / "api.py").write_text("class API: pass\n")

        from towelette.backends.local import LocalBackend
        result = LocalBackend().scout_with_confidence(_make_candidate(), repos_dir)

        assert "src/mylib" in result.report.source_paths
        assert result.report.strategy == "python_ast"

    # ---- skip patterns applied --------------------------------------------- #

    def test_test_files_are_skipped(self, tmp_path: Path):
        """Files under 'tests/' should not count toward py_files."""
        repos_dir, repo_dir = _make_repo(tmp_path)
        pkg = repo_dir / "mylib"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "core.py").write_text("class X: pass\n")
        tests = repo_dir / "tests"
        tests.mkdir()
        (tests / "test_core.py").write_text("assert True\n")

        from towelette.backends.local import LocalBackend
        result = LocalBackend().scout_with_confidence(_make_candidate(), repos_dir)

        # Should not escalate just because tests exist
        assert result.report.strategy == "python_ast"


# =========================================================================== #
# LocalBackend — warning triggers
# =========================================================================== #


class TestLocalBackendWarnings:
    def test_no_init_py_triggers_warning(self, tmp_path: Path):
        repos_dir, repo_dir = _make_repo(tmp_path)
        pkg = repo_dir / "mylib"
        pkg.mkdir()
        (pkg / "core.py").write_text("pass\n")

        from towelette.backends.local import LocalBackend
        result = LocalBackend().scout_with_confidence(_make_candidate(), repos_dir)

        assert result.needs_agentic is True
        assert any("__init__.py" in w for w in result.warnings)

    def test_thin_wrapper_triggers_warning(self, tmp_path: Path):
        """<3 py files with >20 cpp files should trigger the thin-wrapper warning."""
        repos_dir, repo_dir = _make_repo(tmp_path)
        pkg = repo_dir / "mylib"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        cpp_dir = repo_dir / "cpp"
        cpp_dir.mkdir()
        for i in range(25):
            (cpp_dir / f"file{i}.cpp").write_text(f"// file {i}")
        (repo_dir / "pyproject.toml").write_text(
            "[build-system]\nrequires=[\"pybind11\"]\n"
        )

        from towelette.backends.local import LocalBackend
        result = LocalBackend().scout_with_confidence(_make_candidate(), repos_dir)

        assert result.needs_agentic is True
        assert any("thin wrapper" in w for w in result.warnings)

    def test_multiple_pyproject_toml_triggers_warning(self, tmp_path: Path):
        repos_dir, repo_dir = _make_repo(tmp_path)
        pkg = repo_dir / "mylib"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "a.py").write_text("")
        (pkg / "b.py").write_text("")
        (pkg / "c.py").write_text("")
        (repo_dir / "pyproject.toml").write_text("[project]\nname=\"mylib\"\n")
        sub = repo_dir / "sub"
        sub.mkdir()
        (sub / "pyproject.toml").write_text("[project]\nname=\"sub\"\n")

        from towelette.backends.local import LocalBackend
        result = LocalBackend().scout_with_confidence(_make_candidate(), repos_dir)

        assert result.needs_agentic is True
        assert any("pyproject.toml" in w for w in result.warnings)

    def test_missing_repo_url_returns_error(self, tmp_path: Path):
        from towelette.backends.local import LocalBackend

        candidate = DependencyCandidate(name="mylib", repo_url=None)
        repos_dir = tmp_path / "repos"
        repos_dir.mkdir()

        result = LocalBackend().scout_with_confidence(candidate, repos_dir)

        assert result.report.error is not None
        assert result.needs_agentic is True


# =========================================================================== #
# AutoBackend — escalation logic
# =========================================================================== #


class TestAutoBackend:
    def _local_result(self, needs_agentic: bool, warnings: list[str] | None = None):
        from towelette.backends.local import LocalScoutResult
        report = ScoutReport(library="mylib", strategy="python_ast")
        return LocalScoutResult(
            report=report,
            warnings=warnings or [],
            needs_agentic=needs_agentic,
        )

    def test_uses_local_when_confident(self, tmp_path: Path):
        from towelette.backends.auto import AutoBackend
        from towelette.backends.local import LocalBackend

        local = MagicMock(spec=LocalBackend)
        local.scout_with_confidence.return_value = self._local_result(needs_agentic=False)
        fallback = MagicMock()

        backend = AutoBackend(local=local, fallback=fallback)
        report = backend.scout(_make_candidate(), tmp_path / "repos")

        assert report.library == "mylib"
        fallback.scout.assert_not_called()

    def test_escalates_to_fallback_when_uncertain(self, tmp_path: Path):
        from towelette.backends.auto import AutoBackend
        from towelette.backends.local import LocalBackend

        local = MagicMock(spec=LocalBackend)
        local.scout_with_confidence.return_value = self._local_result(
            needs_agentic=True, warnings=["no __init__.py found"]
        )
        fallback = MagicMock()
        fallback.scout.return_value = ScoutReport(library="mylib", strategy="python_ast")

        backend = AutoBackend(local=local, fallback=fallback)
        backend.scout(_make_candidate(), tmp_path / "repos")

        fallback.scout.assert_called_once()

    def test_no_escalation_when_no_fallback_configured(self, tmp_path: Path):
        from towelette.backends.auto import AutoBackend
        from towelette.backends.local import LocalBackend

        local = MagicMock(spec=LocalBackend)
        local.scout_with_confidence.return_value = self._local_result(
            needs_agentic=True, warnings=["some warning"]
        )

        backend = AutoBackend(local=local, fallback=None)
        report = backend.scout(_make_candidate(), tmp_path / "repos")

        # Should still return the local result
        assert report.library == "mylib"

    def test_non_escalating_warnings_returned_without_fallback_call(self, tmp_path: Path):
        from towelette.backends.auto import AutoBackend
        from towelette.backends.local import LocalBackend

        local = MagicMock(spec=LocalBackend)
        local.scout_with_confidence.return_value = self._local_result(
            needs_agentic=False, warnings=["package name doesn't match"]
        )
        fallback = MagicMock()

        backend = AutoBackend(local=local, fallback=fallback)
        report = backend.scout(_make_candidate(), tmp_path / "repos")

        assert report.library == "mylib"
        fallback.scout.assert_not_called()


# =========================================================================== #
# get_backend() factory
# =========================================================================== #


class TestGetBackend:
    def test_local_backend(self):
        from towelette.backends import get_backend
        from towelette.backends.local import LocalBackend

        config = {"settings": {"scout_backend": "local"}}
        backend = get_backend(config)
        assert isinstance(backend, LocalBackend)

    def test_claude_backend(self):
        from towelette.backends import get_backend
        from towelette.backends.claude import ClaudeBackend

        config = {"settings": {"scout_backend": "claude", "scout_model": "sonnet"}}
        backend = get_backend(config)
        assert isinstance(backend, ClaudeBackend)
        assert backend.model == "sonnet"

    def test_generic_backend(self):
        from towelette.backends import get_backend
        from towelette.backends.generic import GenericBackend

        config = {"settings": {"scout_backend": "generic", "scout_command": "echo {prompt}"}}
        backend = get_backend(config)
        assert isinstance(backend, GenericBackend)
        assert backend.command_template == "echo {prompt}"

    def test_generic_backend_requires_command(self):
        from towelette.backends import get_backend

        config = {"settings": {"scout_backend": "generic", "scout_command": ""}}
        with pytest.raises(ValueError, match="scout_command"):
            get_backend(config)

    def test_auto_backend_default(self):
        from towelette.backends import get_backend
        from towelette.backends.auto import AutoBackend

        config = {"settings": {}}
        backend = get_backend(config)
        assert isinstance(backend, AutoBackend)

    def test_auto_backend_explicit(self):
        from towelette.backends import get_backend
        from towelette.backends.auto import AutoBackend

        config = {"settings": {"scout_backend": "auto"}}
        backend = get_backend(config)
        assert isinstance(backend, AutoBackend)

    def test_unknown_backend_falls_back_to_auto(self):
        """Unknown scout_backend value should fall through to auto."""
        from towelette.backends import get_backend
        from towelette.backends.auto import AutoBackend

        config = {"settings": {"scout_backend": "unknown_future_backend"}}
        backend = get_backend(config)
        # Falls through the if-chain and returns AutoBackend
        assert isinstance(backend, AutoBackend)


# =========================================================================== #
# GenericBackend
# =========================================================================== #


class TestGenericBackend:
    def test_parses_successful_output(self, tmp_path: Path):
        import textwrap
        from towelette.backends.generic import GenericBackend

        toml_output = textwrap.dedent("""\
            [report]
            library = "mylib"
            strategy = "python_ast"
            source_paths = ["mylib/"]
            estimated_chunks = 10
            notes = "via generic backend"
        """)

        with patch("towelette.backends.generic.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout=toml_output, stderr=""
            )
            backend = GenericBackend(command_template="echo {prompt}")
            report = backend.scout(_make_candidate(), tmp_path)

        assert report.library == "mylib"
        assert report.error is None

    def test_returns_error_on_nonzero_exit(self, tmp_path: Path):
        from towelette.backends.generic import GenericBackend

        with patch("towelette.backends.generic.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="boom")
            backend = GenericBackend(command_template="fail {prompt}")
            report = backend.scout(_make_candidate(), tmp_path)

        assert report.error is not None

    def test_empty_command_template_raises(self):
        from towelette.backends.generic import GenericBackend

        with pytest.raises(ValueError):
            GenericBackend(command_template="")
