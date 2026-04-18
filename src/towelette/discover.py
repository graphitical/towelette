"""Dependency discovery: parse dep files, scan imports, filter skiplist."""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

from towelette.models import DependencyCandidate, DiscoveryResult
from towelette.skiplist import should_skip

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

_STDLIB = frozenset({
    "__future__", "abc", "argparse", "ast", "asyncio", "base64", "bisect", "builtins",
    "calendar", "cmath", "codecs", "collections", "colorsys", "contextlib",
    "copy", "csv", "ctypes", "dataclasses", "datetime", "decimal",
    "difflib", "email", "enum", "errno", "faulthandler", "fileinput",
    "fnmatch", "fractions", "functools", "gc", "getpass", "glob",
    "gzip", "hashlib", "heapq", "hmac", "html", "http", "importlib",
    "inspect", "io", "itertools", "json", "keyword", "linecache",
    "locale", "logging", "lzma", "math", "mimetypes", "multiprocessing",
    "operator", "os", "pathlib", "platform", "pprint",
    "profile", "pstats", "queue", "random", "re", "readline",
    "reprlib", "secrets", "select", "shelve", "shlex", "shutil",
    "signal", "site", "socket", "sqlite3", "ssl", "stat", "statistics",
    "string", "struct", "subprocess", "sys", "sysconfig", "tempfile",
    "textwrap", "threading", "time", "timeit", "token", "tokenize",
    "traceback", "types", "typing", "unicodedata", "unittest", "urllib",
    "uuid", "venv", "warnings", "weakref", "xml", "xmlrpc", "zipfile",
    "zipimport", "zlib", "_thread", "concurrent", "configparser",
    "dbm", "dis", "distutils",
})

_IMPORT_TO_PACKAGE: dict[str, str] = {
    "OCC": "pythonocc-core",
    "sklearn": "scikit-learn",
    "cv2": "opencv-python",
    "PIL": "Pillow",
    "bs4": "beautifulsoup4",
    "yaml": "PyYAML",
    "attr": "attrs",
    "gi": "PyGObject",
}

_CXX_STDLIB: frozenset[str] = frozenset({
    "algorithm", "any", "array", "atomic", "barrier", "bit", "bitset",
    "cassert", "cctype", "cerrno", "cfenv", "cfloat", "charconv",
    "chrono", "cinttypes", "climits", "clocale", "cmath", "codecvt",
    "compare", "complex", "concepts", "condition_variable", "coroutine",
    "csetjmp", "csignal", "cstdarg", "cstddef", "cstdint", "cstdio",
    "cstdlib", "cstring", "ctime", "cuchar", "cwchar", "cwctype",
    "deque", "exception", "execution", "expected", "filesystem",
    "format", "forward_list", "fstream", "functional", "future",
    "initializer_list", "iomanip", "ios", "iosfwd", "iostream",
    "istream", "iterator", "latch", "limits", "list", "locale",
    "map", "memory", "memory_resource", "mutex", "new", "numbers",
    "numeric", "optional", "ostream", "print", "queue", "random",
    "ranges", "ratio", "regex", "scoped_allocator", "semaphore", "set",
    "shared_mutex", "source_location", "span", "spanstream", "sstream",
    "stack", "stacktrace", "stdexcept", "stop_token", "streambuf",
    "string", "string_view", "strstream", "syncstream", "system_error",
    "thread", "tuple", "type_traits", "typeindex", "typeinfo",
    "unordered_map", "unordered_set", "utility", "valarray", "variant",
    "vector", "version",
    # C compat headers
    "assert.h", "ctype.h", "errno.h", "float.h", "limits.h",
    "locale.h", "math.h", "setjmp.h", "signal.h", "stdarg.h",
    "stddef.h", "stdio.h", "stdlib.h", "string.h", "time.h",
})

_INCLUDE_TO_PACKAGE: dict[str, str] = {
    # Geometry / math
    "Eigen": "eigen3",
    "igl": "libigl",
    "CGAL": "cgal",
    "geometrycentral": "geometry-central",
    "glm": "glm",
    "polyscope": "polyscope",
    "OpenMesh": "openmesh",
    "assimp": "assimp",
    "VCG": "vcglib",
    # General
    "boost": "boost",
    "nlohmann": "nlohmann-json",
    "spdlog": "spdlog",
    "fmt": "fmt",
    "pybind11": "pybind11",
}

_CMAKE_SKIP_DIRS: frozenset[str] = frozenset({
    "build", "cmake-build-debug", "cmake-build-release",
    "cmake-build-relwithdebinfo", "cmake-build-minsizerel",
    "CMakeFiles", ".cmake",
})


def parse_cmakelists(project_root: Path) -> list[DependencyCandidate]:
    deps: list[DependencyCandidate] = []
    seen: set[str] = set()

    for cmake_file in project_root.rglob("CMakeLists.txt"):
        if any(part in _CMAKE_SKIP_DIRS for part in cmake_file.parts):
            continue
        text = cmake_file.read_text(errors="replace")

        for name in re.findall(r"find_package\s*\(\s*(\w+)", text):
            key = name.lower().replace("-", "_")
            if key not in seen:
                seen.add(key)
                deps.append(DependencyCandidate(name=name))

        for block in re.finditer(r"FetchContent_Declare\s*\(\s*(\w+)(.*?)\)", text, re.DOTALL | re.IGNORECASE):
            name = block.group(1)
            body = block.group(2)
            key = name.lower().replace("-", "_")
            url_m = re.search(r"GIT_REPOSITORY\s+([^\s\)]+)", body)
            tag_m = re.search(r"GIT_TAG\s+([^\s\)]+)", body)
            repo_url = url_m.group(1) if url_m else None
            version = _parse_version(tag_m.group(1)) if tag_m else None
            if key not in seen:
                seen.add(key)
                deps.append(DependencyCandidate(name=name, version=version, repo_url=repo_url))

    return deps


def parse_conanfile(project_root: Path) -> list[DependencyCandidate]:
    path = project_root / "conanfile.txt"
    if not path.exists():
        return []

    deps: list[DependencyCandidate] = []
    seen: set[str] = set()
    in_requires = False

    for line in path.read_text().splitlines():
        line = line.strip()
        if line.startswith("["):
            in_requires = line == "[requires]"
            continue
        if not in_requires or not line or line.startswith("#"):
            continue
        # Strip @user/channel suffix, then split name/version
        line = re.sub(r"@[^\s]+", "", line).strip()
        parts = line.split("/")
        name = parts[0].strip()
        version = parts[1].strip() if len(parts) > 1 else None
        key = name.lower().replace("-", "_")
        if name and key not in seen:
            seen.add(key)
            deps.append(DependencyCandidate(name=name, version=version))

    return deps


def parse_vcpkg_json(project_root: Path) -> list[DependencyCandidate]:
    path = project_root / "vcpkg.json"
    if not path.exists():
        return []

    deps: list[DependencyCandidate] = []
    seen: set[str] = set()

    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    for item in data.get("dependencies", []):
        if isinstance(item, str):
            name, version = item, None
        elif isinstance(item, dict):
            name = item.get("name", "")
            version = item.get("version>=") or item.get("version") or None
        else:
            continue
        key = name.lower().replace("-", "_")
        if name and key not in seen:
            seen.add(key)
            deps.append(DependencyCandidate(name=name, version=version))

    return deps


def scan_includes(project_root: Path) -> set[str]:
    packages: set[str] = set()
    extensions = {".cpp", ".cc", ".cxx", ".h", ".hpp", ".hxx"}
    skip_dirs = {".venv", "venv", "node_modules", ".towelette", "__pycache__", ".git"} | _CMAKE_SKIP_DIRS

    for src_file in project_root.rglob("*"):
        if src_file.suffix not in extensions:
            continue
        if any(part in skip_dirs for part in src_file.parts):
            continue
        try:
            text = src_file.read_text(errors="replace")
        except OSError:
            continue
        for m in re.finditer(r'#include\s*<([^>]+)>', text):
            header = m.group(1)
            top = header.split("/")[0]
            if top in _CXX_STDLIB:
                continue
            package = _INCLUDE_TO_PACKAGE.get(top, top)
            packages.add(package)

    return packages


def _parse_version(spec: str) -> str | None:
    m = re.search(r"(\d+\.\d+(?:\.\d+)?)", spec)
    return m.group(1) if m else None


def _parse_dep_string(dep_str: str) -> tuple[str, str | None]:
    dep_str = re.sub(r"\[.*?\]", "", dep_str).strip()
    m = re.match(r"^([a-zA-Z0-9_.-]+)\s*(.*)", dep_str)
    if not m:
        return dep_str, None
    name = m.group(1)
    version = _parse_version(m.group(2)) if m.group(2) else None
    return name, version


def parse_pyproject(project_root: Path) -> list[DependencyCandidate]:
    path = project_root / "pyproject.toml"
    if not path.exists():
        return []

    with open(path, "rb") as f:
        data = tomllib.load(f)

    deps: list[DependencyCandidate] = []
    seen: set[str] = set()

    for dep_str in data.get("project", {}).get("dependencies", []):
        name, version = _parse_dep_string(dep_str)
        normalized = name.lower().replace("-", "_")
        if normalized not in seen:
            seen.add(normalized)
            deps.append(DependencyCandidate(name=name, version=version))

    for group_deps in data.get("project", {}).get("optional-dependencies", {}).values():
        for dep_str in group_deps:
            name, version = _parse_dep_string(dep_str)
            normalized = name.lower().replace("-", "_")
            if normalized not in seen:
                seen.add(normalized)
                deps.append(DependencyCandidate(name=name, version=version))

    return deps


def parse_requirements(project_root: Path) -> list[DependencyCandidate]:
    deps: list[DependencyCandidate] = []
    seen: set[str] = set()

    for filename in ("requirements.txt", "requirements-dev.txt"):
        path = project_root / filename
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            name, version = _parse_dep_string(line)
            normalized = name.lower().replace("-", "_")
            if normalized not in seen:
                seen.add(normalized)
                deps.append(DependencyCandidate(name=name, version=version))

    return deps


def parse_environment_yml(project_root: Path) -> list[DependencyCandidate]:
    try:
        import yaml
    except ImportError:
        return []

    deps: list[DependencyCandidate] = []
    seen: set[str] = set()

    for filename in ("environment.yml", "environment.dev.yml"):
        path = project_root / filename
        if not path.exists():
            continue
        data = yaml.safe_load(path.read_text())
        if not data or "dependencies" not in data:
            continue

        for dep in data["dependencies"]:
            if isinstance(dep, str):
                parts = dep.split("=")
                name = parts[0].strip()
                version = parts[1].strip() if len(parts) > 1 else None
                if name == "python":
                    continue
                normalized = name.lower().replace("-", "_")
                if normalized not in seen:
                    seen.add(normalized)
                    deps.append(DependencyCandidate(name=name, version=version))
            elif isinstance(dep, dict) and "pip" in dep:
                for pip_dep in dep["pip"]:
                    name, version = _parse_dep_string(pip_dep)
                    normalized = name.lower().replace("-", "_")
                    if normalized not in seen:
                        seen.add(normalized)
                        deps.append(DependencyCandidate(name=name, version=version))

    return deps


def scan_imports(project_root: Path) -> set[str]:
    imports: set[str] = set()

    skip_dirs = {".venv", "venv", "node_modules", ".towelette", "__pycache__", ".git"}
    for py_file in project_root.rglob("*.py"):
        if any(part in skip_dirs for part in py_file.parts):
            continue
        try:
            tree = ast.parse(py_file.read_text(), filename=str(py_file))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top not in _STDLIB:
                        imports.add(top)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    top = node.module.split(".")[0]
                    if top not in _STDLIB:
                        imports.add(top)

    return imports


def _local_module_names(project_root: Path) -> set[str]:
    """Collect names of top-level modules/packages defined within the project.

    These are imports that resolve locally and should never be treated as
    external dependencies to scout (e.g. f2l.py, pipeline.py, deformation.py).
    """
    names: set[str] = set()
    for path in project_root.iterdir():
        if path.is_file() and path.suffix == ".py":
            names.add(path.stem.lower())
        elif path.is_dir() and (path / "__init__.py").exists():
            names.add(path.name.lower())
    return names


def discover_deps(
    project_root: Path,
    user_skiplist: set[str] | None = None,
) -> DiscoveryResult:
    all_deps: dict[str, DependencyCandidate] = {}
    dep_files_found: list[str] = []

    for parser, filenames in [
        (parse_pyproject, ["pyproject.toml"]),
        (parse_environment_yml, ["environment.yml", "environment.dev.yml"]),
        (parse_requirements, ["requirements.txt", "requirements-dev.txt"]),
        (parse_conanfile, ["conanfile.txt"]),
        (parse_vcpkg_json, ["vcpkg.json"]),
    ]:
        for fname in filenames:
            if (project_root / fname).exists():
                dep_files_found.append(fname)
        for dep in parser(project_root):
            key = dep.name.lower().replace("-", "_")
            if key not in all_deps:
                all_deps[key] = dep

    # CMakeLists.txt may appear in subdirectories, so check separately
    if any(True for _ in project_root.rglob("CMakeLists.txt")):
        dep_files_found.append("CMakeLists.txt")
    for dep in parse_cmakelists(project_root):
        key = dep.name.lower().replace("-", "_")
        if key not in all_deps:
            all_deps[key] = dep

    local_modules = _local_module_names(project_root)
    imported = scan_imports(project_root) | scan_includes(project_root)
    for imp_name in imported:
        key = imp_name.lower().replace("-", "_")
        if key in local_modules:
            continue  # local project file, not an external dependency
        package_name = _IMPORT_TO_PACKAGE.get(imp_name, imp_name)
        pkg_key = package_name.lower().replace("-", "_")

        if pkg_key in all_deps:
            all_deps[pkg_key].import_count += 1
        elif key in all_deps:
            all_deps[key].import_count += 1
        else:
            all_deps[pkg_key] = DependencyCandidate(name=package_name, import_count=1)

    candidates: list[DependencyCandidate] = []
    skipped: list[str] = []

    for dep in all_deps.values():
        if should_skip(dep.name, user_skiplist):
            skipped.append(dep.name)
        else:
            candidates.append(dep)

    candidates.sort(key=lambda d: d.import_count, reverse=True)

    return DiscoveryResult(
        candidates=candidates,
        skipped=sorted(skipped),
        dep_files_found=dep_files_found,
    )


# --- PyPI URL resolution ---

import asyncio

import httpx


async def resolve_repo_url(package_name: str) -> str | None:
    """Look up a package on PyPI and extract the repository URL from metadata."""
    url = f"https://pypi.org/pypi/{package_name}/json"
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                return None
        except httpx.HTTPError:
            return None

    data = resp.json()
    info = data.get("info", {})

    project_urls = info.get("project_urls") or {}
    for key in ("Source", "Repository", "Source Code", "GitHub", "Homepage", "Code"):
        url_val = project_urls.get(key)
        if url_val and ("github.com" in url_val or "gitlab.com" in url_val or "bitbucket.org" in url_val):
            return url_val

    home_page = info.get("home_page", "")
    if home_page and ("github.com" in home_page or "gitlab.com" in home_page):
        return home_page

    return None


async def resolve_candidates(candidates: list[DependencyCandidate]) -> list[DependencyCandidate]:
    """Resolve repo URLs for all candidates in parallel."""
    async def _resolve_one(candidate: DependencyCandidate) -> DependencyCandidate:
        if candidate.repo_url:
            return candidate
        url = await resolve_repo_url(candidate.name)
        candidate.repo_url = url
        return candidate

    results = await asyncio.gather(*[_resolve_one(c) for c in candidates])
    return list(results)
