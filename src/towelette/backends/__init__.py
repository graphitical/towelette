"""Scout backend protocol and factory.

Backends are responsible for analyzing a library candidate and returning a
``ScoutReport``.  The protocol is intentionally simple so that new backends
can be added without touching the orchestrator.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from towelette.models import DependencyCandidate, ScoutReport


@runtime_checkable
class ScoutBackend(Protocol):
    """Protocol for scout backends that analyze library repos."""

    def scout(
        self,
        candidate: DependencyCandidate,
        repos_dir: Path,
        imports: list[str] | None = None,
    ) -> ScoutReport: ...


def get_backend(config: dict) -> "ScoutBackend":
    """Instantiate the configured scout backend from a towelette config dict.

    Reads ``config["settings"]``:
      * ``scout_backend``  — one of ``auto``, ``local``, ``claude``, ``generic``
                            (default: ``auto``)
      * ``scout_model``    — Claude model shorthand for the claude backend
                            (default: ``haiku``)
      * ``scout_command``  — command template for the generic backend
    """
    settings = config.get("settings", {})
    backend_name = settings.get("scout_backend", "auto")
    scout_model = settings.get("scout_model", "haiku")
    scout_command = settings.get("scout_command", "")

    if backend_name == "local":
        from towelette.backends.local import LocalBackend
        return LocalBackend()

    if backend_name == "claude":
        from towelette.backends.claude import ClaudeBackend
        return ClaudeBackend(model=scout_model)

    if backend_name == "generic":
        if not scout_command:
            raise ValueError(
                "scout_backend = \"generic\" requires scout_command to be set in config"
            )
        from towelette.backends.generic import GenericBackend
        return GenericBackend(command_template=scout_command)

    # Default: auto — local first, escalate to claude if uncertain
    from towelette.backends.local import LocalBackend
    from towelette.backends.auto import AutoBackend

    local = LocalBackend()
    try:
        from towelette.backends.claude import ClaudeBackend
        fallback: ScoutBackend | None = ClaudeBackend(model=scout_model)
    except Exception:
        fallback = None

    return AutoBackend(local=local, fallback=fallback)
