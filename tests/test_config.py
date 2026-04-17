from __future__ import annotations

from pathlib import Path

import pytest


def test_find_towelette_dir_walks_up(tmp_path: Path):
    from towelette.config import find_towelette_dir

    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    (tmp_path / ".towelette").mkdir()

    result = find_towelette_dir(nested)
    assert result == tmp_path / ".towelette"


def test_find_towelette_dir_returns_none_when_missing(tmp_path: Path):
    from towelette.config import find_towelette_dir

    result = find_towelette_dir(tmp_path)
    assert result is None


def test_init_towelette_dir_creates_structure(tmp_path: Path):
    from towelette.config import init_towelette_dir

    d = init_towelette_dir(tmp_path)
    assert d.exists()
    assert (d / "chroma").is_dir()
    assert (d / "repos").is_dir()
    assert (d / "config.toml").is_file()


def test_load_config_reads_toml(tmp_path: Path):
    from towelette.config import init_towelette_dir, load_config

    init_towelette_dir(tmp_path)
    config = load_config(tmp_path / ".towelette")
    assert config["settings"]["tool_prefix"] == "towelette"


def test_save_library_config(tmp_path: Path):
    from towelette.config import init_towelette_dir, load_config, save_library_config

    d = init_towelette_dir(tmp_path)
    save_library_config(d, "trimesh", {
        "repo": "https://github.com/mikedh/trimesh",
        "version": "4.8.2",
        "collection": "trimesh_code",
        "strategy": "python_ast",
        "source_paths": ["trimesh/"],
    })
    config = load_config(d)
    assert "trimesh" in config["libraries"]
    assert config["libraries"]["trimesh"]["version"] == "4.8.2"


def test_get_user_skiplist_empty_by_default(tmp_path: Path):
    from towelette.config import get_user_skiplist, init_towelette_dir

    d = init_towelette_dir(tmp_path)
    assert get_user_skiplist(d) == set()


def test_get_user_skiplist_reads_config(tmp_path: Path):
    from towelette.config import init_towelette_dir, get_user_skiplist

    d = init_towelette_dir(tmp_path)
    config_path = d / "config.toml"
    content = config_path.read_text()
    content += '\n[skiplist]\nextra = ["my-lib", "another-lib"]\n'
    config_path.write_text(content)

    result = get_user_skiplist(d)
    assert result == {"my-lib", "another-lib"}
