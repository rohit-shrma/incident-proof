"""
Blast Radius Analysis Engine — unit tests.

All tests use in-memory / tmp_path fixtures; no live cluster, no network I/O.
The BlastRadiusAnalyzer accepts catalog_path and runbook_index_path overrides
so every test controls its own data without monkeypatching.
"""
from __future__ import annotations

import json
import pytest

from claude_ops.blast_radius import (
    AffectedComponent,
    BlastRadiusAnalyzer,
    DependencyKind,
    ImpactLevel,
    ImpactReport,
    analyze,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

CATALOG = {
    "services": [
        {
            "name": "event-data",
            "namespace": "si",
            "labels": {"app": "event-data"},
            "risk": "production",
        },
        {
            "name": "time-series-query",
            "namespace": "si",
            "labels": {"app": "time-series-query"},
            "risk": "production",
        },
        {
            "name": "multi-system-processor",
            "namespace": "si",
            "labels": {"app": "multi-system-processor"},
            "risk": "production",
        },
    ]
}

RUNBOOK_INDEX = {
    "runbooks": [
        {
            "id": "oom-restart",
            "title": "OOM Restart Investigation",
            "path": "runbooks/oom-restart.md",
        },
        {
            "id": "kafka-commit-rate-low",
            "title": "Kafka Consumer Commit Rate Low",
            "path": "runbooks/kafka-commit-rate-low.md",
        },
    ]
}

OOM_RUNBOOK_TEXT = """\
# OOM Restart Investigation

## Symptoms
- Pod restarts
- OOMKilled
- Memory usage spikes

## Likely causes
- Large payload spike
- Heap pressure or native memory pressure

## Risky actions
- Restarting pods

These require human approval.
"""

KAFKA_RUNBOOK_TEXT = """\
# Kafka Consumer Commit Rate Low

## Symptoms
- Kafka commit rate low
- Consumer may lag

## downstream consumers may be affected if commit rate drops.

## Read-only checks
- Check consumer logs
"""


def _write_catalog(tmp_path, catalog=None):
    catalog_file = tmp_path / "service_catalog.json"
    catalog_file.write_text(json.dumps(catalog or CATALOG))
    return catalog_file


def _write_runbook_index(tmp_path, index=None, oom_text=None, kafka_text=None):
    """Write runbook index + body files; returns index path."""
    runbooks_dir = tmp_path / "runbooks"
    runbooks_dir.mkdir(exist_ok=True)

    (runbooks_dir / "oom-restart.md").write_text(oom_text or OOM_RUNBOOK_TEXT)
    (runbooks_dir / "kafka-commit-rate-low.md").write_text(kafka_text or KAFKA_RUNBOOK_TEXT)

    index_file = tmp_path / "runbook_index.json"
    index_file.write_text(json.dumps(index or RUNBOOK_INDEX))
    return index_file


@pytest.fixture()
def tmp_data(tmp_path):
    """Returns (catalog_path, runbook_index_path) pointing to temp fixtures."""
    catalog_path = _write_catalog(tmp_path)
    runbook_index_path = _write_runbook_index(tmp_path)
    return catalog_path, runbook_index_path


@pytest.fixture()
def minimal_report():
    """A minimal valid incident report dict (matches INCIDENT_REPORT_SCHEMA)."""
    return {
        "service": "event-data",
        "namespace": "si",
        "severity": "high",
        "symptoms": ["pod restarted", "OOMKilled"],
        "evidence": [
            {
                "source": "pod_events",
                "detail": "Container event-data was OOMKilled",
                "timestamp": None,
            }
        ],
        "likely_causes": ["memory spike due to large payload"],
        "ruled_out": ["node pressure not observed"],
        "recommended_next_steps": ["inspect payload size distribution"],
        "requires_human": True,
        "confidence": "medium",
        "unknowns": [],
    }


@pytest.fixture()
def analyzer(tmp_data):
    catalog_path, runbook_index_path = tmp_data
    return BlastRadiusAnalyzer(
        catalog_path=catalog_path,
        runbook_index_path=runbook_index_path,
    )


# ---------------------------------------------------------------------------
# 1. ImpactReport.to_dict() round-trips correctly; enums are strings
# ---------------------------------------------------------------------------

def test_impact_report_to_dict_serializes_enums():
    comp = AffectedComponent(
        name="event-data",
        component_type="service",
        impact=ImpactLevel.HIGH,
        dependency_kind=DependencyKind.CONFIRMED,
        rationale="origin service",
    )
    report = ImpactReport(
        root_cause="memory spike",
        service="event-data",
        namespace="si",
        generated_at="2024-01-01T00:00:00+00:00",
        affected_services=[comp],
    )
    d = report.to_dict()
    svc = d["affected_services"][0]
    assert svc["impact"] == "HIGH"
    assert svc["dependency_kind"] == "CONFIRMED"
    assert isinstance(svc["impact"], str)
    assert isinstance(svc["dependency_kind"], str)


# ---------------------------------------------------------------------------
# 2. ImpactReport.to_json() produces valid JSON
# ---------------------------------------------------------------------------

def test_impact_report_to_json_is_valid_json():
    comp = AffectedComponent(
        name="event-data",
        component_type="service",
        impact=ImpactLevel.HIGH,
        dependency_kind=DependencyKind.CONFIRMED,
        rationale="origin",
    )
    report = ImpactReport(
        root_cause="test",
        service="event-data",
        namespace="si",
        generated_at="2024-01-01T00:00:00+00:00",
        affected_services=[comp],
    )
    parsed = json.loads(report.to_json())
    assert parsed["service"] == "event-data"
    assert len(parsed["affected_services"]) == 1


# ---------------------------------------------------------------------------
# 3. analyze() with minimal valid report returns an ImpactReport (smoke test)
# ---------------------------------------------------------------------------

def test_analyze_smoke(analyzer, minimal_report):
    report = analyzer.analyze(minimal_report)
    assert isinstance(report, ImpactReport)
    assert report.service == "event-data"
    assert report.namespace == "si"
    assert report.generated_at  # ISO timestamp present


# ---------------------------------------------------------------------------
# 4. Origin service is always HIGH + CONFIRMED
# ---------------------------------------------------------------------------

def test_origin_service_is_high_confirmed(analyzer, minimal_report):
    report = analyzer.analyze(minimal_report)
    origin = next(
        (s for s in report.affected_services if s.name == "event-data"),
        None,
    )
    assert origin is not None, "Origin service not found in affected_services"
    assert origin.impact == ImpactLevel.HIGH
    assert origin.dependency_kind == DependencyKind.CONFIRMED


# ---------------------------------------------------------------------------
# 5. A service named in evidence detail → HIGH + CONFIRMED
# ---------------------------------------------------------------------------

def test_service_in_evidence_detail_is_high_confirmed(tmp_data):
    catalog_path, runbook_index_path = tmp_data
    analyzer = BlastRadiusAnalyzer(
        catalog_path=catalog_path,
        runbook_index_path=runbook_index_path,
    )
    report_dict = {
        "service": "event-data",
        "namespace": "si",
        "severity": "high",
        "symptoms": ["error"],
        "evidence": [
            {
                "source": "logs",
                "detail": "time-series-query returned 503 error when called by event-data",
                "timestamp": None,
            }
        ],
        "likely_causes": ["downstream failure"],
        "ruled_out": [],
        "recommended_next_steps": [],
        "requires_human": False,
        "confidence": "high",
        "unknowns": [],
    }
    report = analyzer.analyze(report_dict)
    tsq = next(
        (s for s in report.affected_services if s.name == "time-series-query"),
        None,
    )
    assert tsq is not None
    assert tsq.impact == ImpactLevel.HIGH
    assert tsq.dependency_kind == DependencyKind.CONFIRMED


# ---------------------------------------------------------------------------
# 6. A service named only in a matching runbook → MEDIUM + INFERRED
# ---------------------------------------------------------------------------

def test_service_in_runbook_only_is_medium_inferred(tmp_path):
    # Write a runbook that mentions "time-series-query"
    runbooks_dir = tmp_path / "runbooks"
    runbooks_dir.mkdir()
    (runbooks_dir / "oom-restart.md").write_text(
        "# OOM Restart\n\ntime-series-query may be affected during OOM events.\n"
    )
    (runbooks_dir / "kafka-commit-rate-low.md").write_text("# Kafka\n\nNo service mentions.\n")

    catalog_path = _write_catalog(tmp_path)
    runbook_index_path = _write_runbook_index(
        tmp_path,
        oom_text="# OOM Restart\n\ntime-series-query may be affected during OOM events.\n",
        kafka_text="# Kafka\n\nNo service mentions.\n",
    )
    analyzer = BlastRadiusAnalyzer(
        catalog_path=catalog_path,
        runbook_index_path=runbook_index_path,
    )
    report_dict = {
        "service": "event-data",
        "namespace": "si",
        "severity": "high",
        "symptoms": ["pod restarted", "oom"],
        "evidence": [
            {"source": "pod_events", "detail": "Container event-data OOMKilled", "timestamp": None}
        ],
        "likely_causes": ["memory spike"],
        "ruled_out": [],
        "recommended_next_steps": [],
        "requires_human": False,
        "confidence": "medium",
        "unknowns": [],
    }
    report = analyzer.analyze(report_dict)
    tsq = next(
        (s for s in report.affected_services if s.name == "time-series-query"),
        None,
    )
    assert tsq is not None
    assert tsq.impact == ImpactLevel.MEDIUM
    assert tsq.dependency_kind == DependencyKind.INFERRED


# ---------------------------------------------------------------------------
# 7. A service with no evidence/runbook signal → LOW + INFERRED
# ---------------------------------------------------------------------------

def test_service_no_signal_is_low_inferred(tmp_path):
    # Runbooks with no service name mentions
    runbooks_dir = tmp_path / "runbooks"
    runbooks_dir.mkdir()
    (runbooks_dir / "oom-restart.md").write_text("# OOM Restart\n\nGeneric checks only.\n")
    (runbooks_dir / "kafka-commit-rate-low.md").write_text("# Kafka\n\nGeneric checks.\n")

    catalog_path = _write_catalog(tmp_path)
    runbook_index_path = _write_runbook_index(
        tmp_path,
        oom_text="# OOM Restart\n\nGeneric checks only.\n",
        kafka_text="# Kafka\n\nGeneric checks.\n",
    )
    analyzer = BlastRadiusAnalyzer(
        catalog_path=catalog_path,
        runbook_index_path=runbook_index_path,
    )
    report_dict = {
        "service": "event-data",
        "namespace": "si",
        "severity": "low",
        "symptoms": ["pod restarted"],
        "evidence": [
            {"source": "pod_events", "detail": "Container event-data OOMKilled", "timestamp": None}
        ],
        "likely_causes": ["memory spike"],
        "ruled_out": [],
        "recommended_next_steps": [],
        "requires_human": False,
        "confidence": "low",
        "unknowns": [],
    }
    report = analyzer.analyze(report_dict)
    # multi-system-processor has no evidence or runbook mention
    msp = next(
        (s for s in report.affected_services if s.name == "multi-system-processor"),
        None,
    )
    assert msp is not None
    assert msp.impact == ImpactLevel.LOW
    assert msp.dependency_kind == DependencyKind.INFERRED


# ---------------------------------------------------------------------------
# 8. API URL in evidence with error context → HIGH + CONFIRMED
# ---------------------------------------------------------------------------

def test_api_url_in_evidence_with_error_is_high_confirmed(analyzer):
    report_dict = {
        "service": "event-data",
        "namespace": "si",
        "severity": "high",
        "symptoms": ["500 error"],
        "evidence": [
            {
                "source": "logs",
                "detail": "POST /api/v1/events returned 500 error from downstream",
                "timestamp": None,
            }
        ],
        "likely_causes": ["endpoint failure"],
        "ruled_out": [],
        "recommended_next_steps": [],
        "requires_human": False,
        "confidence": "high",
        "unknowns": [],
    }
    report = analyzer.analyze(report_dict)
    api = next(
        (a for a in report.affected_apis if "/api/v1/events" in a.name),
        None,
    )
    assert api is not None
    assert api.impact == ImpactLevel.HIGH
    assert api.dependency_kind == DependencyKind.CONFIRMED


# ---------------------------------------------------------------------------
# 9. Exception class in likely_causes → MEDIUM + INFERRED
# ---------------------------------------------------------------------------

def test_exception_in_likely_causes_is_medium_inferred(analyzer):
    report_dict = {
        "service": "event-data",
        "namespace": "si",
        "severity": "medium",
        "symptoms": ["service unavailable"],
        "evidence": [
            {"source": "logs", "detail": "Service returned 503", "timestamp": None}
        ],
        "likely_causes": ["OutOfMemoryError in heap causing restarts"],
        "ruled_out": [],
        "recommended_next_steps": [],
        "requires_human": False,
        "confidence": "medium",
        "unknowns": [],
    }
    report = analyzer.analyze(report_dict)
    exc = next(
        (c for c in report.affected_code_components if c.name == "OutOfMemoryError"),
        None,
    )
    assert exc is not None
    assert exc.impact == ImpactLevel.MEDIUM
    assert exc.dependency_kind == DependencyKind.INFERRED


# ---------------------------------------------------------------------------
# 10. DB keyword in evidence detail → HIGH + CONFIRMED
# ---------------------------------------------------------------------------

def test_db_keyword_in_evidence_is_high_confirmed(analyzer):
    report_dict = {
        "service": "event-data",
        "namespace": "si",
        "severity": "high",
        "symptoms": ["data loss"],
        "evidence": [
            {
                "source": "logs",
                "detail": "kafka consumer failed to commit offset, error during processing",
                "timestamp": None,
            }
        ],
        "likely_causes": ["consumer lag"],
        "ruled_out": [],
        "recommended_next_steps": [],
        "requires_human": True,
        "confidence": "high",
        "unknowns": [],
    }
    report = analyzer.analyze(report_dict)
    kafka_dep = next(
        (d for d in report.affected_db_dependencies if d.name == "kafka"),
        None,
    )
    assert kafka_dep is not None
    assert kafka_dep.impact == ImpactLevel.HIGH
    assert kafka_dep.dependency_kind == DependencyKind.CONFIRMED


# ---------------------------------------------------------------------------
# 11. Relevant tests list is non-empty when code components are identified
# ---------------------------------------------------------------------------

def test_relevant_tests_non_empty_when_code_components_present(analyzer):
    report_dict = {
        "service": "event-data",
        "namespace": "si",
        "severity": "high",
        "symptoms": ["crash"],
        "evidence": [
            {
                "source": "logs",
                "detail": "NullPointerException thrown in event-data, error during request processing",
                "timestamp": None,
            }
        ],
        "likely_causes": ["null pointer in handler"],
        "ruled_out": [],
        "recommended_next_steps": [],
        "requires_human": False,
        "confidence": "high",
        "unknowns": [],
    }
    report = analyzer.analyze(report_dict)
    assert len(report.affected_code_components) > 0, "Expected code components to be identified"
    assert len(report.relevant_tests) > 0, "Expected relevant tests when code components present"


# ---------------------------------------------------------------------------
# 12. BlastRadiusAnalyzer accepts custom catalog_path and runbook_index_path
# ---------------------------------------------------------------------------

def test_custom_paths_accepted(tmp_path):
    catalog_path = _write_catalog(tmp_path)
    runbook_index_path = _write_runbook_index(tmp_path)
    analyzer = BlastRadiusAnalyzer(
        catalog_path=str(catalog_path),          # also test str input
        runbook_index_path=str(runbook_index_path),
    )
    assert analyzer._catalog_path == catalog_path
    assert analyzer._runbook_index_path == runbook_index_path


# ---------------------------------------------------------------------------
# 13. Analyzer does not raise when catalog is missing; returns partial report
# ---------------------------------------------------------------------------

def test_missing_catalog_returns_partial_report(tmp_path):
    # Do NOT create catalog file
    runbook_index_path = _write_runbook_index(tmp_path)
    missing_catalog = tmp_path / "nonexistent_catalog.json"
    analyzer = BlastRadiusAnalyzer(
        catalog_path=missing_catalog,
        runbook_index_path=runbook_index_path,
    )
    report_dict = {
        "service": "event-data",
        "namespace": "si",
        "severity": "high",
        "symptoms": ["pod restarted"],
        "evidence": [
            {"source": "pod_events", "detail": "OOMKilled", "timestamp": None}
        ],
        "likely_causes": ["memory spike"],
        "ruled_out": [],
        "recommended_next_steps": [],
        "requires_human": False,
        "confidence": "medium",
        "unknowns": [],
    }
    # Must not raise
    report = analyzer.analyze(report_dict)
    assert isinstance(report, ImpactReport)
    # Catalog is empty → no catalog-based services, but report is returned
    assert report.service == "event-data"
    assert report.affected_services == []
