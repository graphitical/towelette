"""Embedding function management -- pluggable, default ONNX MiniLM."""
from __future__ import annotations

from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2

_embedding_function: ONNXMiniLM_L6_V2 | None = None


def get_embedding_function() -> ONNXMiniLM_L6_V2:
    """Return the singleton embedding function (lazy-loaded)."""
    global _embedding_function
    if _embedding_function is None:
        _embedding_function = ONNXMiniLM_L6_V2()
    return _embedding_function
