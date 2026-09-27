from __future__ import annotations

from dataclasses import dataclass, field
import subprocess


@dataclass(frozen=True)
class VerificationScenario:
    name: str
    verification_command: tuple[str, ...]
    expected_tokens: tuple[str, ...] = ()
    timeout_seconds: int = 30
    max_output_chars: int = 4000


@dataclass(frozen=True)
class SafetyDecision:
    approved: bool
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class VerificationResult:
    scenario: str
    safety: SafetyDecision
    verified: bool
    exit_code: int
    stdout: str
    stderr: str
    evidence: list[str] = field(default_factory=list)
    timed_out: bool = False


class VerificationEngine:
    """
    Controlled fix-verification engine.

    The engine never uses shell=True. Verification commands are explicit
    argument lists, making the execution deterministic and avoiding shell
    expansion.
    """

    BLOCKED_COMMANDS = {
        "del",
        "erase",
        "format",
        "shutdown",
        "reboot",
        "diskpart",
    }

    def evaluate_safety(
        self,
        scenario: VerificationScenario,
    ) -> SafetyDecision:
        reasons: list[str] = []

        if not scenario.name.strip():
            reasons.append("Scenario name cannot be empty.")

        if not scenario.verification_command:
            reasons.append("Verification command cannot be empty.")
            return SafetyDecision(approved=False, reasons=reasons)

        if scenario.timeout_seconds <= 0:
            reasons.append("Timeout must be positive.")

        if scenario.max_output_chars <= 0:
            reasons.append("max_output_chars must be positive.")

        executable = scenario.verification_command[0].lower()

        if executable in self.BLOCKED_COMMANDS:
            reasons.append(
                f"Blocked potentially destructive command: {executable}"
            )

        return SafetyDecision(
            approved=not reasons,
            reasons=reasons,
        )

    def verify(
        self,
        scenario: VerificationScenario,
    ) -> VerificationResult:
        safety = self.evaluate_safety(scenario)

        if not safety.approved:
            return VerificationResult(
                scenario=scenario.name,
                safety=safety,
                verified=False,
                exit_code=-1,
                stdout="",
                stderr="",
                evidence=["Verification blocked by safety gate."],
            )

        try:
            completed = subprocess.run(
                list(scenario.verification_command),
                capture_output=True,
                text=True,
                timeout=scenario.timeout_seconds,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            return VerificationResult(
                scenario=scenario.name,
                safety=safety,
                verified=False,
                exit_code=-1,
                stdout=(exc.stdout or "")[-scenario.max_output_chars:],
                stderr=(exc.stderr or "")[-scenario.max_output_chars:],
                evidence=[
                    f"Verification timed out after "
                    f"{scenario.timeout_seconds}s."
                ],
                timed_out=True,
            )

        stdout = completed.stdout[-scenario.max_output_chars:]
        stderr = completed.stderr[-scenario.max_output_chars:]

        combined = f"{stdout}\n{stderr}".lower()

        matched_tokens = [
            token
            for token in scenario.expected_tokens
            if token.lower() in combined
        ]

        verified = (
            completed.returncode == 0
            and (
                not scenario.expected_tokens
                or bool(matched_tokens)
            )
        )

        evidence = [
            f"Exit code: {completed.returncode}",
            f"Expected tokens matched: "
            f"{', '.join(matched_tokens) or 'none'}",
        ]

        if stdout.strip():
            evidence.append(f"stdout: {stdout.strip()}")

        if stderr.strip():
            evidence.append(f"stderr: {stderr.strip()}")

        return VerificationResult(
            scenario=scenario.name,
            safety=safety,
            verified=verified,
            exit_code=completed.returncode,
            stdout=stdout,
            stderr=stderr,
            evidence=evidence,
        )