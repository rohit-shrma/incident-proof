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
        name="payment-api-oom",
        service="payment-api",
        namespace="production",
        symptom="OOMKilled payment-api pods after memory usage exceeded limit",
    )

    reproduction = ReproductionScenario(
        name="reproduce-payment-api-oom",
        command=(
            "python",
            "-c",
            "import sys; print('OOMKilled: memory limit exceeded'); sys.exit(1)",
        ),
        expected_failure_tokens=("OOMKilled",),
    )

    fix = FixProposal(
        description=(
            "Increase payment-api memory allocation and remove the "
            "memory-retention condition identified during investigation."
        ),
        verification_command=(
            "python",
            "-c",
            "print('payment-api healthy verification passed')",
        ),
    )

    return demo.run(
        incident=incident,
        root_cause="Payment worker retained memory across requests.",
        fix=fix,
        reproduction_scenario=reproduction,
        expected_verification_tokens=("healthy", "passed"),
        evidence_refs=("demo-reproduction", "demo-verification"),
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