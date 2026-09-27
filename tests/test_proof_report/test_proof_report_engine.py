import json

import pytest

from claude_ops.proof_report.engine import ProofReportGenerator


def build_report():
    return ProofReportGenerator().generate(
        incident="payment-api-oom",
        root_cause="Memory leak in payment worker",
        confidence="high",
        investigation=["Logs showed repeated OOMKilled events."],
        blast_radius=["payment-api", "checkout-api"],
        reproduction=["OOM reproduced with the same workload."],
        fix=["Reduced worker memory retention."],
        verification=["Health check passed after the fix."],
        regression_test=["Regression test passed."],
        evidence_refs=["ev_001", "ev_002"],
    )


def test_generate_builds_complete_evidence_chain():
    report = build_report()

    assert report.incident == "payment-api-oom"
    assert report.root_cause == "Memory leak in payment worker"
    assert report.confidence == "high"

    assert [section.title for section in report.sections] == [
        "Investigation",
        "Blast Radius",
        "Reproduction",
        "Fix",
        "Verification",
        "Regression Test",
    ]

    assert [section.status for section in report.sections] == [
        "completed",
        "analyzed",
        "reproduced",
        "generated",
        "verified",
        "generated",
    ]


def test_markdown_contains_evidence_chain():
    report = build_report()

    markdown = report.to_markdown()

    assert "# Incident Proof Report" in markdown
    assert "**Incident:** payment-api-oom" in markdown
    assert "**Root Cause:** Memory leak in payment worker" in markdown
    assert "**Confidence:** high" in markdown

    for title in [
        "Investigation",
        "Blast Radius",
        "Reproduction",
        "Fix",
        "Verification",
        "Regression Test",
    ]:
        assert title in markdown

    assert "ev_001" in markdown
    assert "ev_002" in markdown


def test_write_markdown_creates_report(tmp_path):
    report = build_report()
    output = tmp_path / "proof.md"

    result = ProofReportGenerator().write_markdown(report, output)

    assert result == output
    assert output.exists()
    assert "Incident Proof Report" in output.read_text(encoding="utf-8")


def test_write_json_creates_structured_report(tmp_path):
    report = build_report()
    output = tmp_path / "proof.json"

    result = ProofReportGenerator().write_json(report, output)

    assert result == output
    assert output.exists()

    data = json.loads(output.read_text(encoding="utf-8"))

    assert data["incident"] == "payment-api-oom"
    assert data["root_cause"] == "Memory leak in payment worker"
    assert data["confidence"] == "high"
    assert len(data["sections"]) == 6
    assert data["evidence_refs"] == ["ev_001", "ev_002"]


@pytest.mark.parametrize(
    "field",
    ["incident", "root_cause", "confidence"],
)
def test_generate_rejects_empty_required_fields(field):
    values = {
        "incident": "payment-api-oom",
        "root_cause": "Memory leak",
        "confidence": "high",
    }
    values[field] = " "

    with pytest.raises(ValueError):
        ProofReportGenerator().generate(
            incident=values["incident"],
            root_cause=values["root_cause"],
            confidence=values["confidence"],
            investigation=[],
            blast_radius=[],
            reproduction=[],
            fix=[],
            verification=[],
            regression_test=[],
        )