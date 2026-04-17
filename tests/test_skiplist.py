from __future__ import annotations


def test_default_skiplist_contains_numpy():
    from towelette.skiplist import DEFAULT_SKIPLIST

    assert "numpy" in DEFAULT_SKIPLIST


def test_default_skiplist_contains_common_libs():
    from towelette.skiplist import DEFAULT_SKIPLIST

    for lib in ["scipy", "pandas", "flask", "django", "torch", "pydantic", "pytest"]:
        assert lib in DEFAULT_SKIPLIST


def test_should_skip_returns_true_for_skipped():
    from towelette.skiplist import should_skip

    assert should_skip("numpy") is True
    assert should_skip("pandas") is True


def test_should_skip_returns_false_for_unknown():
    from towelette.skiplist import should_skip

    assert should_skip("pythonocc-core") is False
    assert should_skip("potpourri3d") is False


def test_should_skip_with_user_additions():
    from towelette.skiplist import should_skip

    assert should_skip("my-internal-lib", user_skiplist={"my-internal-lib"}) is True


def test_should_skip_normalizes_names():
    from towelette.skiplist import should_skip

    assert should_skip("scikit-learn") is True
    assert should_skip("scikit_learn") is True
    assert should_skip("typing_extensions") is True
    assert should_skip("typing-extensions") is True
