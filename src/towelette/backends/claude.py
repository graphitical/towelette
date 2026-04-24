"""ClaudeBackend — dispatches scouts via the ``claude --print`` CLI.

This is the original scout dispatch logic extracted from
:func:`towelette.orchestrator._dispatch_one_scout` into a reusable backend
class.
"""
from __future__ import annotations

import subprocess
import threading
from pathlib import Path

from towelette.models import DependencyCandidate, ScoutReport
from towelette.scout import build_scout_prompt, parse_scout_report


class ClaudeBackend:
    """Scout backend that spawns a ``claude --print`` subprocess.

    Parameters
    ----------
    model:
        Claude model shorthand passed to ``--model``.  Defaults to
        ``"haiku"`` (cheapest).  Use ``"sonnet"`` if scouts fail with
        "Prompt is too long".
    timeout:
        Seconds to wait for the subprocess before killing it.
    """

    def __init__(self, model: str = "haiku", timeout: int = 300) -> None:
        self.model = model
        self.timeout = timeout

    def scout(
        self,
        candidate: DependencyCandidate,
        repos_dir: Path,
        imports: list[str] | None = None,
    ) -> ScoutReport:
        """Dispatch a Claude Code subprocess to scout *candidate*.

        The subprocess clones the repo, explores it, and returns a TOML
        report on stdout.  Falls back to an error report on failure.
        """
        if imports is None:
            imports = []

        prompt = build_scout_prompt(candidate, imports, repos_dir=str(repos_dir))

        stderr_lines: list[str] = []

        def _stream_stderr(pipe) -> None:
            for line in pipe:
                stderr_lines.append(line)
                print(f"  [scout:{candidate.name}] {line}", end="", flush=True)

        try:
            proc = subprocess.Popen(
                [
                    "claude",
                    "--print",
                    "--model", self.model,
                    "--strict-mcp-config",       # ignore project .mcp.json
                    "--no-session-persistence",
                    "--allowedTools", "Bash,Read,LS,Glob,Grep,WebFetch,WebSearch",
                    "--verbose",
                    "-p", prompt,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=Path.home(),    # neutral cwd — prevents project CLAUDE.md from loading
            )
            stderr_thread = threading.Thread(
                target=_stream_stderr, args=(proc.stderr,), daemon=True
            )
            stderr_thread.start()
            try:
                stdout, _ = proc.communicate(timeout=self.timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                return ScoutReport(
                    library=candidate.name,
                    repo=candidate.repo_url,
                    version=candidate.version,
                    error=f"Scout timed out after {self.timeout}s",
                )
            stderr_thread.join()

            if proc.returncode == 0 and stdout.strip():
                return parse_scout_report(stdout)

            combined = ("".join(stderr_lines) + stdout).lower()
            if "prompt is too long" in combined:
                hint = (
                    f"Scout prompt exceeded {self.model}'s context limit. "
                    f"Set scout_model = \"sonnet\" in .towelette/config.toml to use a larger "
                    f"context (higher token usage)."
                )
                return ScoutReport(
                    library=candidate.name,
                    repo=candidate.repo_url,
                    version=candidate.version,
                    error=hint,
                )
            stderr_tail = "".join(stderr_lines)[-200:]
            return ScoutReport(
                library=candidate.name,
                repo=candidate.repo_url,
                version=candidate.version,
                error=f"Scout subprocess failed (exit {proc.returncode}): {stderr_tail}",
            )

        except FileNotFoundError:
            return ScoutReport(
                library=candidate.name,
                repo=candidate.repo_url,
                version=candidate.version,
                error="claude CLI not found — install Claude Code to dispatch scouts",
            )
