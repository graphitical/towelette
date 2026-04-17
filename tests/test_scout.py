from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from towelette.models import DependencyCandidate, ScoutReport, UpstreamDependency


class TestBuildScoutPrompt:
    def test_generates_prompt(self):
        from towelette.scout import build_scout_prompt

        candidate = DependencyCandidate(
            name="potpourri3d",
            version="1.4.0",
            import_count=3,
            repo_url="https://github.com/nmwsharp/potpourri3d",
        )
        imports = ["MeshHeatSolver", "compute_distance", "PointCloudHeatSolver"]
        prompt = build_scout_prompt(candidate, imports)
        assert "potpourri3d" in prompt
        assert "https://github.com/nmwsharp/potpourri3d" in prompt
        assert "MeshHeatSolver" in prompt
        assert "v1.4.0" in prompt

    def test_prompt_without_repo_url(self):
        from towelette.scout import build_scout_prompt

        candidate = DependencyCandidate(name="obscure-lib", version="2.0.0")
        prompt = build_scout_prompt(candidate, [])
        assert "obscure-lib" in prompt
        assert "pip download" in prompt.lower() or "package name" in prompt.lower()

    def test_prompt_without_version(self):
        from towelette.scout import build_scout_prompt

        candidate = DependencyCandidate(name="mylib", repo_url="https://github.com/user/mylib")
        prompt = build_scout_prompt(candidate, [])
        assert "mylib" in prompt
        assert "latest" in prompt.lower() or "main" in prompt.lower()

    def test_prompt_includes_repos_dir(self):
        from towelette.scout import build_scout_prompt

        candidate = DependencyCandidate(
            name="mylib", version="1.0.0",
            repo_url="https://github.com/user/mylib",
        )
        prompt = build_scout_prompt(candidate, repos_dir="/tmp/.towelette/repos")
        assert "/tmp/.towelette/repos/mylib" in prompt

    def test_prompt_includes_toml_format(self):
        from towelette.scout import build_scout_prompt

        candidate = DependencyCandidate(name="mylib")
        prompt = build_scout_prompt(candidate)
        assert "[report]" in prompt
        assert "strategy" in prompt
        assert "source_paths" in prompt
        assert "upstream_dependencies" in prompt


class TestParseScoutReport:
    def test_parses_toml_report(self):
        from towelette.scout import parse_scout_report

        report_text = textwrap.dedent("""\
            [report]
            library = "potpourri3d"
            repo = "https://github.com/nmwsharp/potpourri3d"
            version = "v1.4.0"
            strategy = "python_ast + tree_sitter_cpp"
            source_paths = ["src/potpourri3d/"]
            cpp_paths = ["src/cpp/"]
            doc_paths = []
            skip_patterns = ["test_*", "setup.py"]
            estimated_chunks = 120
            notes = "Thin Python wrapper over Geometry Central."

            [[upstream_dependencies]]
            library = "geometry_central"
            repo = "https://github.com/nmwsharp/geometry-central"
            reason = "C++ bindings call Geometry Central"
            significance = "high"
            recommended = true
        """)
        report = parse_scout_report(report_text)
        assert report.library == "potpourri3d"
        assert report.strategy == "python_ast + tree_sitter_cpp"
        assert report.estimated_chunks == 120
        assert len(report.upstream_dependencies) == 1
        assert report.upstream_dependencies[0].library == "geometry_central"
        assert report.upstream_dependencies[0].recommended is True

    def test_parses_json_report(self):
        from towelette.scout import parse_scout_report

        report_text = """{
            "library": "trimesh",
            "repo": "https://github.com/mikedh/trimesh",
            "version": "4.8.2",
            "strategy": "python_ast",
            "source_paths": ["trimesh/"],
            "estimated_chunks": 800,
            "notes": "Pure Python mesh processing library."
        }"""
        report = parse_scout_report(report_text)
        assert report.library == "trimesh"
        assert report.strategy == "python_ast"

    def test_extracts_toml_from_code_block(self):
        from towelette.scout import parse_scout_report

        report_text = 'Here is the report:\n\n```toml\n[report]\nlibrary = "mylib"\nstrategy = "python_ast"\nsource_paths = ["src/"]\nestimated_chunks = 50\n```\n\nDone.'
        report = parse_scout_report(report_text)
        assert report.library == "mylib"

    def test_handles_malformed_report(self):
        from towelette.scout import parse_scout_report

        report = parse_scout_report("this is not valid toml or json at all")
        assert report.error is not None


class TestFormatScoutSummary:
    def test_formats_multiple_reports(self):
        from towelette.scout import format_scout_summary

        reports = [
            ScoutReport(library="trimesh", version="4.8.2", strategy="python_ast", estimated_chunks=800),
            ScoutReport(library="potpourri3d", version="v1.4.0", strategy="python_ast + tree_sitter_cpp", estimated_chunks=120),
        ]
        summary = format_scout_summary(reports)
        assert "trimesh" in summary
        assert "potpourri3d" in summary
        assert "800" in summary

    def test_formats_report_with_error(self):
        from towelette.scout import format_scout_summary

        reports = [
            ScoutReport(library="broken-lib", error="Could not find repository"),
        ]
        summary = format_scout_summary(reports)
        assert "broken-lib" in summary
        assert "error" in summary.lower() or "Could not find" in summary

    def test_shows_upstream_deps(self):
        from towelette.scout import format_scout_summary

        reports = [
            ScoutReport(
                library="potpourri3d",
                strategy="python_ast",
                upstream_dependencies=[
                    UpstreamDependency(library="geometry_central", significance="high", recommended=True),
                ],
            ),
        ]
        summary = format_scout_summary(reports)
        assert "geometry_central" in summary
        assert "recommended" in summary.lower()
