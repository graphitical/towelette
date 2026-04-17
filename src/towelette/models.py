"""Pydantic models for Towelette data structures."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class IndexStrategy(str, Enum):
    """Indexing strategy for a library."""

    PYTHON_AST = "python_ast"
    TREE_SITTER_CPP = "tree_sitter_cpp"
    BOTH = "python_ast + tree_sitter_cpp"


class DependencyCandidate(BaseModel):
    """A discovered dependency that may be worth indexing."""

    name: str
    version: str | None = None
    import_count: int = 0
    repo_url: str | None = None


class UpstreamDependency(BaseModel):
    """An upstream dependency discovered by a scout."""

    library: str
    repo: str | None = None
    reason: str = ""
    significance: str = "low"
    recommended: bool = False


class ScoutReport(BaseModel):
    """Report returned by a scout after researching a library."""

    library: str
    repo: str | None = None
    version: str | None = None
    strategy: str = "python_ast"
    source_paths: list[str] = Field(default_factory=list)
    cpp_paths: list[str] = Field(default_factory=list)
    doc_paths: list[str] = Field(default_factory=list)
    skip_patterns: list[str] = Field(default_factory=list)
    estimated_chunks: int = 0
    notes: str = ""
    upstream_dependencies: list[UpstreamDependency] = Field(default_factory=list)
    error: str | None = None


class IndexEntry(BaseModel):
    """Metadata for an indexed library stored in config."""

    library: str
    collection_name: str
    version: str | None = None
    strategy: str = "python_ast"
    source_paths: list[str] = Field(default_factory=list)
    chunk_count: int = 0
    indexed_at: str | None = None


class DiscoveryResult(BaseModel):
    """Result of the discovery phase."""

    candidates: list[DependencyCandidate] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    dep_files_found: list[str] = Field(default_factory=list)
