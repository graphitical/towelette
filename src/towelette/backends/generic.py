"""GenericBackend — shell out to any configurable CLI coding agent.

The command template receives ``{prompt}`` as a format argument and is
executed via the shell.  Standard output is expected to contain a TOML (or
JSON) scout report in the same format used by :class:`ClaudeBackend`.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from towelette.models import DependencyCandidate, ScoutReport
from towelette.scout import build_scout_prompt, parse_scout_report


class GenericBackend:
    """Scout backend that shells out to an arbitrary CLI command.

    Parameters
    ----------
    command_template:
        Shell command with a ``{prompt}`` placeholder.  Example::

            codex -q '{prompt}'
            aider --message '{prompt}'

    timeout:
        Seconds to wait for the command before killing it.
    """

    def __init__(self, command_template: str, timeout: int = 300) -> None:
        if not command_template:
            raise ValueError("command_template must not be empty")
        self.command_template = command_template
        self.timeout = timeout

    def scout(
        self,
        candidate: DependencyCandidate,
        repos_dir: Path,
        imports: list[str] | None = None,
    ) -> ScoutReport:
        """Run the command template and parse its output as a scout report."""
        if imports is None:
            imports = []

        prompt = build_scout_prompt(candidate, imports, repos_dir=str(repos_dir))

        try:
            cmd = self.command_template.format(prompt=prompt)
        except KeyError as exc:
            return ScoutReport(
                library=candidate.name,
                repo=candidate.repo_url,
                version=candidate.version,
                error=f"GenericBackend: invalid command_template placeholder: {exc}",
            )

        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            return ScoutReport(
                library=candidate.name,
                repo=candidate.repo_url,
                version=candidate.version,
                error=f"GenericBackend: command timed out after {self.timeout}s",
            )
        except Exception as exc:
            return ScoutReport(
                library=candidate.name,
                repo=candidate.repo_url,
                version=candidate.version,
                error=f"GenericBackend: command failed: {exc}",
            )

        if result.returncode == 0 and result.stdout.strip():
            return parse_scout_report(result.stdout)

        stderr_tail = result.stderr[-200:] if result.stderr else ""
        return ScoutReport(
            library=candidate.name,
            repo=candidate.repo_url,
            version=candidate.version,
            error=(
                f"GenericBackend: command exited {result.returncode}: {stderr_tail}"
            ),
        )
