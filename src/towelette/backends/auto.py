"""AutoBackend — tries local heuristics first, escalates to agentic on uncertainty.

This backend wraps :class:`~towelette.backends.local.LocalBackend` and an
optional *fallback* :class:`~towelette.backends.ScoutBackend`.  When the
local heuristics signal they are uncertain (``needs_agentic=True``), the
fallback backend is used instead.
"""
from __future__ import annotations

from pathlib import Path

from towelette.backends import ScoutBackend
from towelette.backends.local import LocalBackend
from towelette.models import DependencyCandidate, ScoutReport


class AutoBackend:
    """Scout backend that tries :class:`LocalBackend` and escalates if needed.

    Parameters
    ----------
    local:
        The local heuristic backend to try first.
    fallback:
        An optional agentic backend to use when the local result has
        ``needs_agentic=True``.  If *None* the local result is always used,
        even when uncertain.
    """

    def __init__(
        self,
        local: LocalBackend,
        fallback: ScoutBackend | None = None,
    ) -> None:
        self.local = local
        self.fallback = fallback

    def scout(
        self,
        candidate: DependencyCandidate,
        repos_dir: Path,
        imports: list[str] | None = None,
    ) -> ScoutReport:
        """Scout *candidate*, escalating to the fallback when uncertain."""
        result = self.local.scout_with_confidence(candidate, repos_dir, imports)

        if result.needs_agentic and self.fallback is not None:
            print(
                f"  [auto] {candidate.name}: local uncertain "
                f"({', '.join(result.warnings)}), escalating",
                flush=True,
            )
            return self.fallback.scout(candidate, repos_dir, imports)

        if result.warnings:
            print(
                f"  [auto] {candidate.name}: local with warnings: "
                f"{', '.join(result.warnings)}",
                flush=True,
            )

        return result.report
