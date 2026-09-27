from pathlib import Path

from claude_ops.orchestration.engine import (
    FixProposal,
    Incident,
    IncidentProofEngine,
    IncidentProofResult,
)
from claude_ops.reproduction.engine import ReproductionScenario
def run_demo(
    *,
    catalog_path: Path | str = "data/service_catalog.json",
    runbook_index_path: Path | str = "data/runbook_index.json",
    report_dir: Path | str = "reports",
) -> IncidentProofResult:
    """
    Run a deterministic local IncidentProof demonstration.

    The commands below intentionally use Python's standard library instead
    of kubectl or other external infrastructure tools, so the demo can run
    reliably during a hackathon presentation.
    """

    demo = IncidentProofEngine(
        catalog_path=catalog_path,
        runbook_index_path=runbook_index_path,
        report_dir=report_dir,
    )

    incident = Incident(
        name="service-memory-failure",
        service="example-service",
        namespace="production",
        symptom="Service instances restarted after memory usage exceeded the configured limit",
    )

    reproduction = ReproductionScenario(
        name="reproduce-service-memory-failure",
        command=(
            "python",
            "-c",
            "import sys; print('MemoryLimitExceeded: instance restarted'); sys.exit(1)",
        ),
        expected_failure_tokens=("MemoryLimitExceeded",),
    )

    fix = FixProposal(
        description=(
            "Increase the affected service's memory allocation and remove "
            "the memory-retention condition identified during investigation."
        ),
        verification_command=(
            "python",
            "-c",
            "print('service healthy verification passed')",
        ),
    )

    return demo.run(
        incident=incident,
        root_cause="A memory-retention condition caused the service to exceed its configured memory limit.",
        fix=fix,
        reproduction_scenario=reproduction,
        expected_verification_tokens=("healthy", "passed"),
        evidence_refs=("reproduction-evidence", "verification-evidence"),
    )


if __name__ == "__main__":
    result = run_demo()

    print("IncidentProof demo completed.")
    print(f"Incident: {result.incident.name}")
    print(f"Root cause: {result.root_cause}")
    print(f"Reproduced: {result.reproduction.reproduced}")
    print(f"Safety gate: {'APPROVED' if result.safety.approved else 'BLOCKED'}")
    print(f"Verified: {result.verification.verified}")
    print(f"Proof report: {result.report_path}")