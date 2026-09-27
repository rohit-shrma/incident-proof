from __future__ import annotations

from dataclasses import dataclass, field
import subprocess
from typing import Sequence


@dataclass(frozen=True)
class ReproductionScenario:
    name: str
    command: tuple[str, ...]
    expected_failure_tokens: tuple[str, ...] = ()
    timeout_seconds: int = 30


@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def combined_output(self) -> str:
        return f"{self.stdout}\n{self.stderr}".strip()


@dataclass(frozen=True)
class ReproductionResult:
    scenario: str
    reproduced: bool
    evidence: list[str] = field(default_factory=list)
    command_result: CommandResult | None = None


class ReproductionEngine:
    """
    Controlled incident reproduction engine.

    Commands are supplied explicitly as argument lists and executed without
    shell expansion. This keeps reproduction deterministic and avoids shell
    injection through scenario input.
    """

    def run(self, scenario: ReproductionScenario) -> ReproductionResult:
        if not scenario.name.strip():
            raise ValueError("Scenario name cannot be empty.")

        if not scenario.command:
            raise ValueError("Scenario command cannot be empty.")

        if scenario.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive.")

        try:
            completed = subprocess.run(
                list(scenario.command),
                capture_output=True,
                text=True,
                timeout=scenario.timeout_seconds,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            result = CommandResult(
                command=scenario.command,
                exit_code=-1,
                stdout=exc.stdout or "",
                stderr=exc.stderr or "",
                timed_out=True,
            )
            return ReproductionResult(
                scenario=scenario.name,
                reproduced=False,
                evidence=[
                    f"Command timed out after {scenario.timeout_seconds}s."
                ],
                command_result=result,
            )

        result = CommandResult(
            command=scenario.command,
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

        output = result.combined_output.lower()

        token_matches = [
            token
            for token in scenario.expected_failure_tokens
            if token.lower() in output
        ]

        reproduced = (
            result.exit_code != 0
            and (
                not scenario.expected_failure_tokens
                or bool(token_matches)
            )
        )

        evidence = [
            f"Exit code: {result.exit_code}",
            f"Failure tokens matched: {', '.join(token_matches) or 'none'}",
        ]

        if result.stdout.strip():
            evidence.append(f"stdout: {result.stdout.strip()}")

        if result.stderr.strip():
            evidence.append(f"stderr: {result.stderr.strip()}")

        return ReproductionResult(
            scenario=scenario.name,
            reproduced=reproduced,
            evidence=evidence,
            command_result=result,
        )