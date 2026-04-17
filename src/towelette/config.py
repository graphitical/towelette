"""Configuration management for .towelette/ directory."""
from __future__ import annotations

import re
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


_DEFAULT_CONFIG = """\
[settings]
tool_prefix = "towelette"
chunk_limit = 8000
# scout_model controls which Claude model scouts use. "haiku" is cheapest.
# If scouts fail with "Prompt is too long", set this to "sonnet" (higher token usage).
scout_model = "haiku"
# upstream_chase = true enables scouting of upstream dependencies recommended by scouts.
# Disabled by default -- most libraries don't have upstream deps worth indexing.
upstream_chase = false

[libraries]
# Populated by towelette init / scouts
"""


def find_towelette_dir(start: Path) -> Path | None:
    """Walk up from `start` looking for a .towelette/ directory."""
    current = start.resolve()
    while True:
        candidate = current / ".towelette"
        if candidate.is_dir():
            return candidate
        parent = current.parent
        if parent == current:
            return None
        current = parent


def init_towelette_dir(project_root: Path) -> Path:
    """Create .towelette/ directory structure and default config."""
    d = project_root / ".towelette"
    d.mkdir(exist_ok=True)
    (d / "chroma").mkdir(exist_ok=True)
    (d / "repos").mkdir(exist_ok=True)
    config_path = d / "config.toml"
    if not config_path.exists():
        config_path.write_text(_DEFAULT_CONFIG)
    return d


def load_config(towelette_dir: Path) -> dict:
    """Load and parse .towelette/config.toml."""
    config_path = towelette_dir / "config.toml"
    if not config_path.exists():
        return {"settings": {"tool_prefix": "towelette", "chunk_limit": 8000}, "libraries": {}}
    with open(config_path, "rb") as f:
        return tomllib.load(f)


def _toml_key(name: str) -> str:
    """Quote a TOML key if it contains characters outside [A-Za-z0-9_-]."""
    if re.fullmatch(r"[A-Za-z0-9_-]+", name):
        return name
    return f'"{name}"'


def save_library_config(towelette_dir: Path, library: str, entry: dict) -> None:
    """Add or update a library entry in config.toml."""
    config_path = towelette_dir / "config.toml"
    content = config_path.read_text() if config_path.exists() else _DEFAULT_CONFIG

    key = _toml_key(library)
    section = f"\n[libraries.{key}]\n"
    for k, value in entry.items():
        if isinstance(value, list):
            items = ", ".join(f'"{v}"' for v in value)
            section += f"{k} = [{items}]\n"
        elif isinstance(value, bool):
            section += f"{k} = {'true' if value else 'false'}\n"
        elif isinstance(value, (int, float)):
            section += f"{k} = {value}\n"
        else:
            section += f'{k} = "{value}"\n'

    # Remove existing section (try both quoted and bare key forms).
    # Use re.MULTILINE + ^ so the anchor doesn't consume the preceding newline.
    for pat_key in (re.escape(key), re.escape(library)):
        pattern = re.compile(
            rf"^\[libraries\.{pat_key}\]\n(?:(?!\[)[^\n]*\n)*",
            re.MULTILINE,
        )
        content = pattern.sub("", content)

    # Collapse excess blank lines and ensure a single trailing newline.
    content = re.sub(r"\n{3,}", "\n\n", content).rstrip("\n") + "\n"
    content += section
    config_path.write_text(content)


def get_user_skiplist(towelette_dir: Path) -> set[str]:
    """Read user-configured extra skiplist entries from config."""
    config = load_config(towelette_dir)
    skiplist_config = config.get("skiplist", {})
    return set(skiplist_config.get("extra", []))
