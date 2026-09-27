from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RegressionTestCase:
    name: str
    command: tuple[str, ...]
    expected_output: tuple[str, ...] = ()


@dataclass(frozen=True)
class RegressionSuite:
    incident: str
    tests: tuple[RegressionTestCase, ...]


class RegressionTestGenerator:
    """
    Generates deterministic regression-test cases from verified incident
    evidence.

    The generated cases are descriptions of commands to run; this class
    does not execute them.
    """

    def generate(
        self,
        incident: str,
        verification_command: tuple[str, ...],
        expected_output: tuple[str, ...] = (),
    ) -> RegressionSuite:
        if not incident.strip():
            raise ValueError("Incident cannot be empty.")

        if not verification_command:
            raise ValueError("Verification command cannot be empty.")

        test = RegressionTestCase(
            name=f"regression-{incident.strip().lower().replace(' ', '-')}",
            command=verification_command,
            expected_output=expected_output,
        )

        return RegressionSuite(
            incident=incident,
            tests=(test,),
        )

    def generate_from_reproduction(
        self,
        incident: str,
        reproduction_command: tuple[str, ...],
        verification_command: tuple[str, ...],
        expected_output: tuple[str, ...] = (),
    ) -> RegressionSuite:
        if not reproduction_command:
            raise ValueError("Reproduction command cannot be empty.")

        suite = self.generate(
            incident=incident,
            verification_command=verification_command,
            expected_output=expected_output,
        )

        reproduction_test = RegressionTestCase(
            name=f"reproduction-{incident.strip().lower().replace(' ', '-')}",
            command=reproduction_command,
        )

        return RegressionSuite(
            incident=suite.incident,
            tests=(reproduction_test, *suite.tests),
        )