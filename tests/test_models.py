from __future__ import annotations

import pytest


def test_dependency_candidate_creation():
    from towelette.models import DependencyCandidate

    dep = DependencyCandidate(
        name="pythonocc-core",
        version="7.9.0",
        import_count=12,
        repo_url="https://github.com/tpaviot/pythonocc-core",
    )
    assert dep.name == "pythonocc-core"
    assert dep.version == "7.9.0"
    assert dep.import_count == 12
    assert dep.repo_url == "https://github.com/tpaviot/pythonocc-core"


def test_dependency_candidate_optional_fields():
    from towelette.models import DependencyCandidate

    dep = DependencyCandidate(name="trimesh")
    assert dep.version is None
    assert dep.import_count == 0
    assert dep.repo_url is None


def test_scout_report_creation():
    from towelette.models import ScoutReport, UpstreamDependency

    report = ScoutReport(
        library="potpourri3d",
        repo="https://github.com/nmwsharp/potpourri3d",
        version="v1.4.0",
        strategy="python_ast + tree_sitter_cpp",
        source_paths=["src/potpourri3d/"],
        cpp_paths=["src/cpp/"],
        doc_paths=[],
        skip_patterns=["test_*", "setup.py"],
        estimated_chunks=120,
        notes="Thin Python wrapper over Geometry Central.",
        upstream_dependencies=[
            UpstreamDependency(
                library="geometry_central",
                repo="https://github.com/nmwsharp/geometry-central",
                reason="C++ bindings call Geometry Central",
                significance="high",
                recommended=True,
            )
        ],
    )
    assert report.library == "potpourri3d"
    assert report.strategy == "python_ast + tree_sitter_cpp"
    assert len(report.upstream_dependencies) == 1
    assert report.upstream_dependencies[0].recommended is True


def test_index_entry_creation():
    from towelette.models import IndexEntry

    entry = IndexEntry(
        library="trimesh",
        collection_name="trimesh_code",
        version="4.8.2",
        strategy="python_ast",
        source_paths=["trimesh/"],
        chunk_count=813,
    )
    assert entry.library == "trimesh"
    assert entry.chunk_count == 813


def test_index_strategy_enum():
    from towelette.models import IndexStrategy

    assert IndexStrategy.PYTHON_AST == "python_ast"
    assert IndexStrategy.TREE_SITTER_CPP == "tree_sitter_cpp"
    assert IndexStrategy.BOTH == "python_ast + tree_sitter_cpp"


def test_discovery_result():
    from towelette.models import DependencyCandidate, DiscoveryResult

    result = DiscoveryResult(
        candidates=[
            DependencyCandidate(name="trimesh", version="4.8.2", import_count=8),
        ],
        skipped=["numpy", "pydantic"],
        dep_files_found=["pyproject.toml"],
    )
    assert len(result.candidates) == 1
    assert "numpy" in result.skipped
