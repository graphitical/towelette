"""Default skiplist of well-known libraries that don't need RAG indexing."""
from __future__ import annotations

# Libraries where LLM training data is sufficient -- RAG adds no value
DEFAULT_SKIPLIST: frozenset[str] = frozenset({
    # Scientific/numeric
    "numpy", "scipy", "pandas", "matplotlib", "seaborn", "plotly",
    "scikit-learn", "sklearn", "sympy", "statsmodels",
    # Web/API
    "flask", "django", "fastapi", "requests", "httpx", "aiohttp",
    "starlette", "uvicorn", "gunicorn",
    # Data/DB
    "sqlalchemy", "psycopg2", "redis", "celery", "pymongo",
    # DevOps/CLI
    "click", "typer", "rich", "pytest", "mypy", "ruff",
    "setuptools", "pip", "wheel", "hatchling",
    # ML frameworks
    "torch", "tensorflow", "keras", "transformers", "jax",
    # Standard-ish
    "pydantic", "attrs", "dataclasses", "typing_extensions",
    "loguru", "structlog", "dotenv", "toml", "yaml", "json",
    # C++ well-known (LLMs already know these)
    "boost", "zlib", "openssl", "libcurl", "sqlite3",
    "glfw", "glew", "opengl", "vulkan", "sdl2",
})


def _normalize(name: str) -> str:
    """Normalize a package name for comparison (PEP 503)."""
    return name.lower().replace("-", "_").replace(".", "_")


_NORMALIZED_SKIPLIST: frozenset[str] = frozenset(
    _normalize(n) for n in DEFAULT_SKIPLIST
)


def should_skip(
    name: str,
    user_skiplist: set[str] | None = None,
) -> bool:
    """Return True if the package should be skipped (well-known, no RAG needed)."""
    normalized = _normalize(name)
    if normalized in _NORMALIZED_SKIPLIST:
        return True
    if user_skiplist:
        user_normalized = {_normalize(n) for n in user_skiplist}
        if normalized in user_normalized:
            return True
    return False
