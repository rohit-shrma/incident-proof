from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from claude_ops.blast_radius.analyzer import BlastRadiusAnalyzer
from claude_ops.proof_report.engine import ProofReportGenerator
from claude_ops.regression.engine import RegressionTestGenerator
from claude_ops.reproduction.engine import (
    ReproductionEngine,
    ReproductionScenario,
)
from claude_ops.verification.engine import (
    VerificationEngine,
    VerificationScenario,
)


@dataclass(frozen=True)
class Incident:
    name: str
    service: str
    namespace: str
    symptom: str


@dataclass(frozen=True)
class FixProposal:
    description: str
    verification_command: tuple[str, ...]


@dataclass(frozen=True)
class IncidentProofResult:
    incident: Incident
    root_cause: str
    blast_radius: object
    reproduction: object
    fix: FixProposal
    safety: object
    regression_suite: object
    verification: object
    proof_report: object
    report_path: Path


class IncidentProofEngine:
    """
    End-to-end IncidentProof demonstration pipeline.

    The demo connects the deterministic project components into one
    auditable workflow. Infrastructure-changing actions are represented
    as proposals; the demo does not automatically modify a real cluster.
    """

    def __init__(
        self,
        *,
        catalog_path: Path | str,
        runbook_index_path: Path | str,
        report_dir: Path | str = "reports",
    ) -> None:
        self.blast_radius = BlastRadiusAnalyzer(
            catalog_path=Path(catalog_path),
            runbook_index_path=Path(runbook_index_path),
        )
        self.reproduction = ReproductionEngine()
        self.verification = VerificationEngine()
        self.regression = RegressionTestGenerator()
        self.proof = ProofReportGenerator()
        self.report_dir = Path(report_dir)

    def run(
        self,
        *,
        incident: Incident,
        root_cause: str,
        fix: FixProposal,
        reproduction_scenario: ReproductionScenario,
        expected_verification_tokens: tuple[str, ...] = (),
        evidence_refs: tuple[str, ...] = (),
    ) -> IncidentProofResult:
        # 1. INVESTIGATION
        investigation = [
            f"Incident: {incident.name}",
            f"Service: {incident.service}",
            f"Namespace: {incident.namespace}",
            f"Symptom: {incident.symptom}",
            f"Root cause identified: {root_cause}",
        ]

        # 2. BLAST RADIUS
        blast_radius = self.blast_radius.analyze(
    {
        "service": incident.service,
        "namespace": incident.namespace,
        "severity": "high",
        "symptoms": [incident.symptom],
        "evidence": [
            {
                "source": "demo-investigation",
                "detail": incident.symptom,
                "timestamp": None,
            }
        ],
        "likely_causes": [root_cause],
        "ruled_out": [],
        "recommended_next_steps": [fix.description],
        "requires_human": True,
        "confidence": "high",
        "unknowns": [],
    }
)
        blast_radius_details = [
            f"{component.name}: {component.impact.value} impact "
            f"({component.dependency_kind.value})"
            for component in blast_radius.affected_code_components
        ]

        # 3. REPRODUCTION
        reproduction = self.reproduction.run(reproduction_scenario)

        if not reproduction.reproduced:
            raise RuntimeError(
                "Incident reproduction failed; refusing to continue "
                "to fix verification."
            )

        # 4. FIX PROPOSAL
        fix_details = [
            f"Proposed fix: {fix.description}",
            "No infrastructure mutation was performed by the demo.",
        ]

        # 5. SAFETY GATE
        verification_scenario = VerificationScenario(
            name=f"verify-{incident.name}",
            verification_command=fix.verification_command,
            expected_tokens=expected_verification_tokens,
        )

        safety = self.verification.evaluate_safety(verification_scenario)

        if not safety.approved:
            raise RuntimeError(
                "Fix verification blocked by safety gate: "
                + "; ".join(safety.reasons)
            )

        # 6. REGRESSION TEST GENERATION
        regression_suite = self.regression.generate_from_reproduction(
            incident=incident.name,
            reproduction_command=reproduction_scenario.command,
            verification_command=fix.verification_command,
            expected_output=expected_verification_tokens,
        )

        regression_details = [
            f"Generated regression test: {test.name}"
            for test in regression_suite.tests
        ]

        # 7. VERIFICATION
        verification = self.verification.verify(verification_scenario)

        if not verification.verified:
            raise RuntimeError(
                "Fix verification failed; proof report will not claim success."
            )

        # 8. PROOF REPORT
        report = self.proof.generate(
            incident=incident.name,
            root_cause=root_cause,
            confidence="high",
            investigation=investigation,
            blast_radius=blast_radius_details,
            reproduction=reproduction.evidence,
            fix=fix_details,
            verification=verification.evidence,
            regression_test=regression_details,
            evidence_refs=evidence_refs,
        )

        report_path = (
            self.report_dir
            / f"{incident.name.replace(' ', '-').lower()}-proof.md"
        )
        self.proof.write_markdown(report, report_path)

        return IncidentProofResult(
            incident=incident,
            root_cause=root_cause,
            blast_radius=blast_radius,
            reproduction=reproduction,
            fix=fix,
            safety=safety,
            regression_suite=regression_suite,
            verification=verification,
            proof_report=report,
            report_path=report_path,
        )
