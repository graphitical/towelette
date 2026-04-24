"""LocalBackend — heuristic-only scout that clones repos and inspects structure.

No LLM is required.  The backend clones the repo (if not already present),
walks the directory tree, detects Python/C++ source layout, identifies
binding indicators, and returns a ``ScoutReport`` with warnings when the
heuristics are uncertain.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from towelette.models import DependencyCandidate, IndexStrategy, ScoutReport

# --------------------------------------------------------------------------- #
# Skip patterns applied during tree walks
# --------------------------------------------------------------------------- #

_SKIP_DIR_NAMES: frozenset[str] = frozenset({
    "test", "tests", "example", "examples",
    "doc", "docs", "benchmark", "benchmarks",
    ".github", "ci", "build", "dist",
    "__pycache__", ".git",
})

# Binding indicator strings — searched in build/config files
_BINDING_KEYWORDS: tuple[str, ...] = (
    "pybind11", "nanobind", "SWIG", "swig", "cython", "cffi", "ctypes",
)

# Files that may contain binding declarations
_BINDING_FILE_GLOBS: tuple[str, ...] = (
    "setup.py", "setup.cfg", "pyproject.toml",
    "CMakeLists.txt", "meson.build", "**/*.pyx",
)

# Average chunks-per-file estimates used when an LLM isn't doing the counting
_AVG_CHUNKS_PY: int = 3
_AVG_CHUNKS_CPP: int = 5


@dataclass
class LocalScoutResult:
    """Result returned by :meth:`LocalBackend.scout_with_confidence`.

    Wraps the plain ``ScoutReport`` with extra metadata the ``AutoBackend``
    uses to decide whether to escalate to an agentic backend.
    """

    report: ScoutReport
    warnings: list[str] = field(default_factory=list)
    needs_agentic: bool = False


class LocalBackend:
    """Heuristic scout backend — no LLM required.

    Clones the repo (shallow, ``--depth=1``) into *repos_dir/<name>* if it
    is not already present, then walks the tree to determine:

    * Python source paths
    * C/C++ source paths
    * Whether C/C++ bindings are present (pybind11 / nanobind / SWIG / Cython …)
    * Skip patterns
    * Estimated chunk count

    When the heuristics are uncertain, :attr:`LocalScoutResult.needs_agentic`
    is set to ``True`` so the ``AutoBackend`` can escalate to a full LLM scout.
    """

    # ------------------------------------------------------------------ #
    # Public API (ScoutBackend protocol)
    # ------------------------------------------------------------------ #

    def scout(
        self,
        candidate: DependencyCandidate,
        repos_dir: Path,
        imports: list[str] | None = None,
    ) -> ScoutReport:
        """Return a :class:`~towelette.models.ScoutReport` for *candidate*.

        Calls :meth:`scout_with_confidence` internally and discards the
        confidence metadata.  Use :meth:`scout_with_confidence` when you need
        warnings / escalation flags (e.g. in ``AutoBackend``).
        """
        return self.scout_with_confidence(candidate, repos_dir, imports).report

    # ------------------------------------------------------------------ #
    # Confidence-aware entry point
    # ------------------------------------------------------------------ #

    def scout_with_confidence(
        self,
        candidate: DependencyCandidate,
        repos_dir: Path,
        imports: list[str] | None = None,
    ) -> LocalScoutResult:
        """Analyse *candidate* and return a :class:`LocalScoutResult`.

        The ``report`` field always contains a valid ``ScoutReport``; the
        ``warnings`` field collects non-fatal uncertainties; ``needs_agentic``
        is ``True`` when at least one *severe* warning was generated.
        """
        warnings: list[str] = []
        needs_agentic = False

        # ---- ensure we have a repo URL ------------------------------------ #
        if not candidate.repo_url:
            return LocalScoutResult(
                report=ScoutReport(
                    library=candidate.name,
                    error=(
                        "LocalBackend requires a repo_url — "
                        "URL resolution must happen before dispatch"
                    ),
                ),
                warnings=["no repo URL available"],
                needs_agentic=True,
            )

        # ---- clone if needed ---------------------------------------------- #
        repo_dir = repos_dir / candidate.name
        if not repo_dir.exists() or not any(repo_dir.iterdir()):
            clone_result = subprocess.run(
                ["git", "clone", "--depth=1", candidate.repo_url, str(repo_dir)],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if clone_result.returncode != 0:
                return LocalScoutResult(
                    report=ScoutReport(
                        library=candidate.name,
                        repo=candidate.repo_url,
                        version=candidate.version,
                        error=f"git clone failed: {clone_result.stderr[:300]}",
                    ),
                    warnings=["clone failed"],
                    needs_agentic=True,
                )

        # ---- walk the tree ------------------------------------------------ #
        py_files: list[Path] = []
        cpp_files: list[Path] = []
        init_files: list[Path] = []
        pyproject_files: list[Path] = []

        for path in repo_dir.rglob("*"):
            if path.is_dir():
                continue
            if self._should_skip(path, repo_dir):
                continue

            suffix = path.suffix.lower()
            name = path.name.lower()

            if name == "__init__.py":
                init_files.append(path)
            if name in ("pyproject.toml", "setup.py", "setup.cfg"):
                pyproject_files.append(path)

            if suffix == ".py":
                py_files.append(path)
            elif suffix in (".h", ".hpp", ".hxx", ".cpp", ".cc", ".cxx"):
                cpp_files.append(path)

        has_python = bool(py_files)
        has_cpp = bool(cpp_files)

        # ---- layout detection --------------------------------------------- #
        src_prefix = f"src/{candidate.name}"
        flat_prefix = candidate.name
        if (repo_dir / src_prefix).is_dir():
            python_root = src_prefix
        elif (repo_dir / flat_prefix).is_dir():
            python_root = flat_prefix
        else:
            # Fall back: use directory containing the first __init__.py
            if init_files:
                python_root = str(init_files[0].parent.relative_to(repo_dir))
            elif py_files:
                python_root = str(py_files[0].parent.relative_to(repo_dir))
            else:
                python_root = "."

        # ---- package name vs directory name check ------------------------- #
        if has_python:
            pkg_dir = repo_dir / python_root
            if not pkg_dir.exists():
                warnings.append(
                    f"python_root '{python_root}' does not exist in repo"
                )
                needs_agentic = True

        # ---- __init__.py check -------------------------------------------- #
        if has_python and not init_files:
            warnings.append(
                "no __init__.py found — may be a namespace package or non-standard layout"
            )
            needs_agentic = True

        # ---- monorepo / multiple pyproject.toml check --------------------- #
        all_pyprojects = list(repo_dir.rglob("pyproject.toml"))
        if len(all_pyprojects) > 1:
            warnings.append(
                f"multiple pyproject.toml files ({len(all_pyprojects)}) — possible monorepo"
            )
            needs_agentic = True

        # ---- pyproject declared paths vs disk ----------------------------- #
        if all_pyprojects:
            declared_paths = self._parse_package_dirs(all_pyprojects[0], repo_dir)
            for dp in declared_paths:
                if not (repo_dir / dp).exists():
                    warnings.append(
                        f"pyproject.toml declares package path '{dp}' but it doesn't exist on disk"
                    )
                    needs_agentic = True

        # ---- strategy determination --------------------------------------- #
        binding_detected = False
        if has_python and has_cpp:
            binding_detected = self._detect_bindings(repo_dir)
            if not binding_detected:
                warnings.append(
                    "C/C++ files present alongside Python but no binding indicator found"
                )
                needs_agentic = True

        # thin-wrapper heuristic
        if has_cpp and has_python:
            if len(py_files) < 3 and len(cpp_files) > 20:
                warnings.append(
                    f"very few Python files ({len(py_files)}) with large C++ tree "
                    f"({len(cpp_files)} files) — possible thin wrapper"
                )
                needs_agentic = True

        # package name vs directory
        if has_python:
            dir_names = {p.name.lower() for p in repo_dir.iterdir() if p.is_dir()}
            norm_name = candidate.name.lower().replace("-", "_")
            if norm_name not in dir_names:
                # also check under src/
                src_dir = repo_dir / "src"
                if src_dir.is_dir():
                    dir_names |= {p.name.lower() for p in src_dir.iterdir() if p.is_dir()}
                if norm_name not in dir_names:
                    warnings.append(
                        f"package name '{candidate.name}' doesn't match any directory in repo"
                    )
                    needs_agentic = True

        # ---- build strategy ----------------------------------------------- #
        if has_python and has_cpp and binding_detected:
            strategy = IndexStrategy.BOTH.value  # "python_ast + tree_sitter_cpp"
        elif has_cpp and not has_python:
            strategy = IndexStrategy.TREE_SITTER_CPP.value
        else:
            strategy = IndexStrategy.PYTHON_AST.value

        # ---- source paths ------------------------------------------------- #
        source_paths: list[str] = []
        cpp_paths: list[str] = []

        if has_python:
            source_paths = [python_root]
        if has_cpp:
            # Group C++ files under their common top-level directories
            cpp_top_dirs: set[str] = set()
            for cf in cpp_files:
                try:
                    rel = cf.relative_to(repo_dir)
                    top = str(rel.parts[0]) if len(rel.parts) > 1 else "."
                    cpp_top_dirs.add(top)
                except ValueError:
                    pass
            cpp_paths = sorted(cpp_top_dirs)

        # ---- skip patterns ------------------------------------------------ #
        skip_patterns = sorted(_SKIP_DIR_NAMES)

        # ---- estimated chunks --------------------------------------------- #
        estimated_chunks = (
            len(py_files) * _AVG_CHUNKS_PY
            + len(cpp_files) * _AVG_CHUNKS_CPP
        )

        report = ScoutReport(
            library=candidate.name,
            repo=candidate.repo_url,
            version=candidate.version,
            strategy=strategy,
            source_paths=source_paths,
            cpp_paths=cpp_paths,
            skip_patterns=skip_patterns,
            estimated_chunks=estimated_chunks,
            notes=(
                f"Heuristic analysis: {len(py_files)} .py, {len(cpp_files)} C/C++ files"
                + (f"; {len(warnings)} warning(s)" if warnings else "")
            ),
        )

        return LocalScoutResult(
            report=report,
            warnings=warnings,
            needs_agentic=needs_agentic,
        )

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _should_skip(path: Path, repo_dir: Path) -> bool:
        """Return True if *path* should be excluded from analysis."""
        try:
            rel = path.relative_to(repo_dir)
        except ValueError:
            return False
        for part in rel.parts[:-1]:  # directory components only
            normalized = part.lower().rstrip("s")  # strip trailing 's'
            if (
                part.lower() in _SKIP_DIR_NAMES
                or normalized in _SKIP_DIR_NAMES
                or part.startswith(".")
            ):
                return True
        return False

    @staticmethod
    def _detect_bindings(repo_dir: Path) -> bool:
        """Return True if any known binding keyword is found in build files."""
        candidate_files: list[Path] = []
        for glob in _BINDING_FILE_GLOBS:
            candidate_files.extend(repo_dir.glob(glob))

        for fpath in candidate_files:
            try:
                text = fpath.read_text(errors="ignore")
                for kw in _BINDING_KEYWORDS:
                    if kw in text:
                        return True
            except OSError:
                continue
        return False

    @staticmethod
    def _parse_package_dirs(pyproject_path: Path, repo_dir: Path) -> list[str]:
        """Try to extract declared package directories from pyproject.toml.

        Returns a (possibly empty) list of relative paths.
        Only handles the common ``[tool.setuptools.packages.find]`` and
        ``packages = [{include = "foo", from = "src"}]`` patterns.
        """
        import sys
        if sys.version_info >= (3, 11):
            import tomllib
        else:
            try:
                import tomli as tomllib  # type: ignore[no-redef]
            except ImportError:
                return []

        try:
            data = tomllib.loads(pyproject_path.read_text())
        except Exception:
            return []

        paths: list[str] = []

        # flit / hatch style: [tool.flit.module] or [project] name + src layout
        project_name = data.get("project", {}).get("name", "")
        if project_name:
            for candidate_path in (f"src/{project_name}", project_name):
                if (repo_dir / candidate_path).exists():
                    paths.append(candidate_path)

        # setuptools packages.find
        find = (
            data.get("tool", {})
                .get("setuptools", {})
                .get("packages", {})
                .get("find", {})
        )
        where = find.get("where", [])
        if isinstance(where, list):
            for w in where:
                paths.append(str(w))

        return paths
