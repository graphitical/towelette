from __future__ import annotations

import pytest


def test_get_embedding_function_returns_callable():
    from towelette.embed import get_embedding_function

    ef = get_embedding_function()
    assert callable(ef)


def test_get_embedding_function_is_cached():
    from towelette.embed import get_embedding_function

    ef1 = get_embedding_function()
    ef2 = get_embedding_function()
    assert ef1 is ef2


def test_get_embedding_function_returns_onnx_minilm():
    from towelette.embed import get_embedding_function
    from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2

    ef = get_embedding_function()
    assert isinstance(ef, ONNXMiniLM_L6_V2)
