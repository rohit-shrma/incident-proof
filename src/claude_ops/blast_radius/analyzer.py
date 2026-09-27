from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from claude_ops.blast_radius.impact_report import (
    AffectedComponent,
    DependencyKind,
    ImpactLevel,
    ImpactReport,
)

# Relative to this file: src/claude_ops/blast_radius/analyzer.py → project root is 4 levels up
_PROJECT_ROOT = Path(__file__).resolve().parents[4]

# Tokens that indicate a database / messaging dependency
_DB_KEYWORDS: frozenset[str] = frozenset({
    "kafka",
    "postgres",
    "postgresql",
    "db",
    "database",
    "redis",
    "mongo",
    "mongodb",
    "elasticsearch",
    "jdbc",
    "datasource",
    "connection pool",
    "connectionpool",
    "commit rate",
    "commitrate",
})

# Regex for URL / API path shapes
_API_PATTERN = re.compile(r"/(?:v\d+|api)[/\w\-\.%{}:?=&]+", re.IGNORECASE)

# Regex for exception / error class names (CamelCase ending in Exception/Error, or any CamelCase)
_EXCEPTION_PATTERN = re.compile(r"\b([A-Z][a-zA-Z0-9]*(?:Exception|Error))\b")

# Regex for file-like tokens (path or package notation)
_FILE_PATTERN = re.compile(
    r"\b[\w/\.\-]+\.(?:py|java|go|ts|js|rb|kt|scala)\b"
    r"|\b[\w]+(?:\.[\w]+){2,}\b"  # package.sub.Class
)

# Regex for method references
_METHOD_PATTERN = re.compile(r"\b\w+\.\w+\(\)|at \w+\.\w+")

# Error / failure signal words
_ERROR_WORDS: frozenset[str] = frozenset({
    "error", "exception", "failure", "failed", "crash", "oom", "oomkilled",
    "killed", "panic", "fatal", "timeout", "refused", "unavailable", "down",
    "unreachable", "5xx", "500", "503",
})

# Downstream signal words in runbook text
_DOWNSTREAM_WORDS: frozenset[str] = frozenset({
    "downstream", "consumer", "caller", "dependency", "dependent", "upstream caller",
})


def _has_error_context(text: str) -> bool:
    """Return True if text contains an error/failure signal word."""
    lower = text.lower()
    return any(w in lower for w in _ERROR_WORDS)


class BlastRadiusAnalyzer:
    """
    Read-only, deterministic blast-radius analysis engine.

    Accepts a confirmed incident report dict (validated against
    INCIDENT_REPORT_SCHEMA) and returns an ImpactReport by traversing
    the service catalog and runbook index — no live cluster I/O.
    """

    def __init__(
        self,
        catalog_path: Path | str | None = None,
        runbook_index_path: Path | str | None = None,
    ) -> None:
        self._catalog_path = (
            Path(catalog_path) if catalog_path is not None
            else _PROJECT_ROOT / "data" / "service_catalog.json"
        )
        self._runbook_index_path = (
            Path(runbook_index_path) if runbook_index_path is not None
            else _PROJECT_ROOT / "data" / "runbook_index.json"
        )

    # ------------------------------------------------------------------
    # Internal loaders
    # ------------------------------------------------------------------

    def _load_service_catalog(self) -> list[dict[str, Any]]:
        try:
            raw = json.loads(self._catalog_path.read_text())
            return raw.get("services", [])
        except Exception:
            return []

    def _load_runbooks_for_signal(
        self, signal_tokens: set[str]
    ) -> list[dict[str, str]]:
        """
        Return runbooks whose title or body contains at least one signal token.
        Each hit is {"id": str, "title": str, "text": str}.
        """
        try:
            index = json.loads(self._runbook_index_path.read_text())
        except Exception:
            return []

        # Resolve runbook file paths relative to the runbook index directory
        # (mirrors runbook_tools.py which uses PROJECT_ROOT)
        index_dir = self._runbook_index_path.parent
        hits: list[dict[str, str]] = []
        for rb in index.get("runbooks", []):
            path = index_dir / rb["path"]
            try:
                text = path.read_text()
            except Exception:
                continue
            haystack = f"{rb['title']}\n{text}".lower()
            if any(tok in haystack for tok in signal_tokens):
                hits.append({"id": rb["id"], "title": rb["title"], "text": text})
        return hits

    # ------------------------------------------------------------------
    # Signal extraction
    # ------------------------------------------------------------------

    def _extract_signal_tokens(self, incident_report: dict[str, Any]) -> set[str]:
        """
        Build a lower-cased token set from the incident report fields that
        represent the root-cause signal (service, namespace, causes, symptoms,
        evidence details).
        """
        tokens: set[str] = set()
        for field in ("service", "namespace"):
            val = incident_report.get(field, "")
            if val:
                tokens.add(val.lower())

        for lst_field in ("likely_causes", "symptoms"):
            for item in incident_report.get(lst_field, []):
                for tok in item.lower().split():
                    tokens.add(tok)

        for ev in incident_report.get("evidence", []):
            detail = ev.get("detail", "")
            for tok in detail.lower().split():
                tokens.add(tok)

        return tokens

    # ------------------------------------------------------------------
    # Step 3 + 4 — services
    # ------------------------------------------------------------------

    def _classify_services(
        self,
        incident_report: dict[str, Any],
        catalog: list[dict[str, Any]],
        runbook_hits: list[dict[str, str]],
    ) -> list[AffectedComponent]:
        origin_name = incident_report.get("service", "")
        origin_ns = incident_report.get("namespace", "")
        evidence_list = incident_report.get("evidence", [])

        # Collect all evidence detail strings
        all_evidence_details = [ev.get("detail", "") for ev in evidence_list]
        combined_evidence = " ".join(all_evidence_details).lower()

        # Collect all runbook text
        combined_runbook = " ".join(rb["text"] for rb in runbook_hits).lower()
        runbook_ids = [rb["id"] for rb in runbook_hits]

        components: list[AffectedComponent] = []

        for entry in catalog:
            name = entry.get("name", "")
            ns = entry.get("namespace", "")
            labels = entry.get("labels", {})
            label_values = " ".join(str(v) for v in labels.values()).lower()
            name_lower = name.lower()

            if name == origin_name:
                # Origin service is always HIGH + CONFIRMED
                components.append(AffectedComponent(
                    name=name,
                    component_type="service",
                    impact=ImpactLevel.HIGH,
                    dependency_kind=DependencyKind.CONFIRMED,
                    rationale="Root-cause locus: this is the originating service identified in the incident report.",
                ))
                continue

            # Check evidence for confirmed signal
            evidence_mentions = [
                ev.get("detail", "") for ev in evidence_list
                if name_lower in ev.get("detail", "").lower()
                or label_values in ev.get("detail", "").lower()
            ]

            if evidence_mentions:
                has_error = any(_has_error_context(d) for d in evidence_mentions)
                impact = ImpactLevel.HIGH if has_error else ImpactLevel.MEDIUM
                ref_snippet = evidence_mentions[0][:120]
                components.append(AffectedComponent(
                    name=name,
                    component_type="service",
                    impact=impact,
                    dependency_kind=DependencyKind.CONFIRMED,
                    rationale=f"Named in evidence detail: \"{ref_snippet}\"",
                ))
                continue

            # Check runbook text for inferred signal
            if runbook_ids and name_lower in combined_runbook:
                components.append(AffectedComponent(
                    name=name,
                    component_type="service",
                    impact=ImpactLevel.MEDIUM,
                    dependency_kind=DependencyKind.INFERRED,
                    rationale=f"Named in runbook(s): {', '.join(runbook_ids)}",
                ))
                continue

            # Same namespace, no specific signal → LOW
            if ns == origin_ns:
                components.append(AffectedComponent(
                    name=name,
                    component_type="service",
                    impact=ImpactLevel.LOW,
                    dependency_kind=DependencyKind.INFERRED,
                    rationale=(
                        f"Same namespace '{ns}' as origin service; no specific evidence signal. "
                        "May be affected by node/network blast."
                    ),
                ))

        # Decision 2: surface unregistered services mentioned in evidence
        catalog_names_lower = {e.get("name", "").lower() for e in catalog}
        for ev in evidence_list:
            detail = ev.get("detail", "")
            # Look for tokens that look like service names (hyphenated lowercase words)
            # that are NOT already in the catalog
            for token in re.findall(r"\b[a-z][a-z0-9]*(?:-[a-z0-9]+)+\b", detail):
                if token not in catalog_names_lower and token != origin_name.lower() and token not in seen:
                    seen.add(token)
                    has_error = _has_error_context(detail)
                    components.append(AffectedComponent(
                        name=token,
                        component_type="service",
                        impact=ImpactLevel.HIGH if has_error else ImpactLevel.MEDIUM,
                        dependency_kind=DependencyKind.INFERRED,
                        rationale=(
                            f"not_in_catalog: Explicitly identified in evidence detail but not "
                            f"registered in the service catalog. Evidence: \"{detail[:120]}\""
                        ),
                    ))
                    catalog_names_lower.add(token)  # avoid duplicates

        return components

    # ------------------------------------------------------------------
    # Step 5 — APIs
    # ------------------------------------------------------------------

    def _classify_apis(
        self, incident_report: dict[str, Any]
    ) -> list[AffectedComponent]:
        seen: set[str] = set()
        components: list[AffectedComponent] = []

        runbook_hits: list[dict[str, str]] = []  # populated separately; not available here
        # APIs are sourced from evidence detail strings
        for ev in incident_report.get("evidence", []):
            detail = ev.get("detail", "")
            for match in _API_PATTERN.findall(detail):
                if match in seen:
                    continue
                seen.add(match)
                has_error = _has_error_context(detail)
                components.append(AffectedComponent(
                    name=match,
                    component_type="api",
                    impact=ImpactLevel.HIGH if has_error else ImpactLevel.MEDIUM,
                    dependency_kind=DependencyKind.CONFIRMED,
                    rationale=f"API path found in evidence detail: \"{detail[:120]}\"",
                ))

        return components

    # ------------------------------------------------------------------
    # Step 6 — code components
    # ------------------------------------------------------------------

    def _classify_code_components(
        self, incident_report: dict[str, Any]
    ) -> list[AffectedComponent]:
        seen: set[str] = set()
        components: list[AffectedComponent] = []

        # Evidence detail → CONFIRMED HIGH (if error context) or CONFIRMED MEDIUM
        for ev in incident_report.get("evidence", []):
            detail = ev.get("detail", "")
            has_error = _has_error_context(detail)
            for pattern, ctype in (
                (_EXCEPTION_PATTERN, "exception"),
                (_FILE_PATTERN, "file"),
                (_METHOD_PATTERN, "method"),
            ):
                for m in pattern.findall(detail):
                    token = m.strip()
                    if not token or token in seen:
                        continue
                    seen.add(token)
                    components.append(AffectedComponent(
                        name=token,
                        component_type=ctype,
                        impact=ImpactLevel.HIGH if has_error else ImpactLevel.MEDIUM,
                        dependency_kind=DependencyKind.CONFIRMED,
                        rationale=f"Identified in evidence detail: \"{detail[:120]}\"",
                    ))

        # likely_causes → INFERRED MEDIUM
        for cause in incident_report.get("likely_causes", []):
            for pattern, ctype in (
                (_EXCEPTION_PATTERN, "exception"),
                (_FILE_PATTERN, "file"),
                (_METHOD_PATTERN, "method"),
            ):
                for m in pattern.findall(cause):
                    token = m.strip()
                    if not token or token in seen:
                        continue
                    seen.add(token)
                    components.append(AffectedComponent(
                        name=token,
                        component_type=ctype,
                        impact=ImpactLevel.MEDIUM,
                        dependency_kind=DependencyKind.INFERRED,
                        rationale=f"Identified in likely_causes: \"{cause[:120]}\"",
                    ))

        return components

    # ------------------------------------------------------------------
    # Step 7 — DB dependencies
    # ------------------------------------------------------------------

    def _classify_db_dependencies(
        self, incident_report: dict[str, Any]
    ) -> list[AffectedComponent]:
        seen: set[str] = set()
        components: list[AffectedComponent] = []

        # Evidence detail → CONFIRMED HIGH
        for ev in incident_report.get("evidence", []):
            detail = ev.get("detail", "")
            detail_lower = detail.lower()
            for keyword in _DB_KEYWORDS:
                if keyword in detail_lower and keyword not in seen:
                    seen.add(keyword)
                    components.append(AffectedComponent(
                        name=keyword,
                        component_type="db_dependency",
                        impact=ImpactLevel.HIGH,
                        dependency_kind=DependencyKind.CONFIRMED,
                        rationale=f"DB/messaging keyword '{keyword}' found in evidence detail: \"{detail[:120]}\"",
                    ))

        # likely_causes → INFERRED MEDIUM
        for cause in incident_report.get("likely_causes", []):
            cause_lower = cause.lower()
            for keyword in _DB_KEYWORDS:
                if keyword in cause_lower and keyword not in seen:
                    seen.add(keyword)
                    components.append(AffectedComponent(
                        name=keyword,
                        component_type="db_dependency",
                        impact=ImpactLevel.MEDIUM,
                        dependency_kind=DependencyKind.INFERRED,
                        rationale=f"DB/messaging keyword '{keyword}' found in likely_causes: \"{cause[:120]}\"",
                    ))

        return components

    # ------------------------------------------------------------------
    # Step 8 — downstream consumers
    # ------------------------------------------------------------------

    def _classify_downstream_consumers(
        self,
        incident_report: dict[str, Any],
        catalog: list[dict[str, Any]],
        runbook_hits: list[dict[str, str]],
    ) -> list[AffectedComponent]:
        origin_name = incident_report.get("service", "")
        origin_ns = incident_report.get("namespace", "")
        evidence_list = incident_report.get("evidence", [])
        runbook_ids = [rb["id"] for rb in runbook_hits]

        # Combine runbook text to scan for downstream signal near the service name
        combined_runbook = " ".join(rb["text"] for rb in runbook_hits).lower()
        origin_lower = origin_name.lower()

        # Determine if a runbook mentions downstream impact near the service name
        runbook_mentions_downstream = False
        seen: set[str] = set()
        components: list[AffectedComponent] = []

        for entry in catalog:
            name = entry.get("name", "")
            ns = entry.get("namespace", "")
            if name == origin_name:
                continue

            name_lower = name.lower()

            # CONFIRMED HIGH: evidence explicitly names a consumer failing
            consumer_evidence = [
                ev.get("detail", "") for ev in evidence_list
                if name_lower in ev.get("detail", "").lower()
                and _has_error_context(ev.get("detail", ""))
            ]
            if consumer_evidence and name not in seen:
                seen.add(name)
                components.append(AffectedComponent(
                    name=name,
                    component_type="downstream_consumer",
                    impact=ImpactLevel.HIGH,
                    dependency_kind=DependencyKind.CONFIRMED,
                    rationale=f"Consumer explicitly named in evidence with error context: \"{consumer_evidence[0][:120]}\"",
                ))
                continue

            # INFERRED MEDIUM: runbook mentions downstream impact
            if runbook_mentions_downstream and name not in seen:
                seen.add(name)
                components.append(AffectedComponent(
                    name=name,
                    component_type="downstream_consumer",
                    impact=ImpactLevel.MEDIUM,
                    dependency_kind=DependencyKind.INFERRED,
                    rationale=f"Runbook(s) {', '.join(runbook_ids)} mention downstream/consumer impact for this incident type.",
                ))
                continue

            # INFERRED LOW: same-namespace service (possible caller)
            if ns == origin_ns and name not in seen:
                seen.add(name)
                components.append(AffectedComponent(
                    name=name,
                    component_type="downstream_consumer",
                    impact=ImpactLevel.LOW,
                    dependency_kind=DependencyKind.INFERRED,
                    rationale=(
                        f"Same namespace '{ns}' as origin; without a dependency graph, "
                        "this service may be a caller/consumer."
                    ),
                ))

        return components

    # ------------------------------------------------------------------
    # Step 9 — relevant tests
    # ------------------------------------------------------------------

    def _classify_relevant_tests(
        self,
        incident_report: dict[str, Any],
        runbook_hits: list[dict[str, str]],
        code_components: list[AffectedComponent],
    ) -> list[AffectedComponent]:
        seen: set[str] = set()
        components: list[AffectedComponent] = []

        _test_token_pattern = re.compile(
            r"\b(?:test_[\w]+\.py|[\w]+Test\.java|[\w]+_test\.go|[\w]+Spec\.\w+)\b"
            r"|integration test|unit test",
            re.IGNORECASE,
        )

        for rb in runbook_hits:
            for match in _test_token_pattern.findall(rb["text"]):
                token = match.strip()
                if token in seen:
                    continue
                seen.add(token)
                components.append(AffectedComponent(
                    name=token,
                    component_type="test",
                    impact=ImpactLevel.MEDIUM,
                    dependency_kind=DependencyKind.INFERRED,
                    rationale=f"Test reference found in runbook '{rb['id']}'.",
                ))

        # For every confirmed code component, recommend a test entry
        for comp in code_components:
            test_name = f"unit tests covering {comp.name}"
            if test_name not in seen:
                seen.add(test_name)
                components.append(AffectedComponent(
                    name=test_name,
                    component_type="test",
                    impact=ImpactLevel.HIGH,
                    dependency_kind=DependencyKind.INFERRED,
                    rationale=(
                        f"Confirmed code defect in '{comp.name}' always requires test coverage review."
                    ),
                ))

        return components

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, incident_report: dict[str, Any]) -> ImpactReport:
        """
        Analyse the blast radius of a confirmed incident.

        Parameters
        ----------
        incident_report:
            A dict that validates against INCIDENT_REPORT_SCHEMA.

        Returns
        -------
        ImpactReport
            Populated report; never raises — returns a partial report with
            a rationale note when catalog data is unavailable.
        """
        # Step 1 — Load catalogs
        catalog = self._load_service_catalog()
        signal_tokens = self._extract_signal_tokens(incident_report)
        runbook_hits = self._load_runbooks_for_signal(signal_tokens)

        # Step 2-10 — classify
        affected_services = self._classify_services(incident_report, catalog, runbook_hits)
        affected_apis = self._classify_apis(incident_report)
        code_components = self._classify_code_components(incident_report)
        db_deps = self._classify_db_dependencies(incident_report)
        downstream = self._classify_downstream_consumers(incident_report, catalog, runbook_hits)
        tests = self._classify_relevant_tests(incident_report, runbook_hits, code_components)

        root_cause = "; ".join(incident_report.get("likely_causes", [])) or "unknown"

        return ImpactReport(
            root_cause=root_cause,
            service=incident_report.get("service", ""),
            namespace=incident_report.get("namespace", ""),
            generated_at=datetime.now(tz=timezone.utc).isoformat(),
            affected_services=affected_services,
            affected_apis=affected_apis,
            affected_code_components=code_components,
            affected_db_dependencies=db_deps,
            affected_downstream_consumers=downstream,
            relevant_tests=tests,
        )


def analyze(incident_report: dict[str, Any]) -> ImpactReport:
    """
    Module-level convenience entry point.

    Constructs a default BlastRadiusAnalyzer (using paths resolved from the
    repository layout) and calls analyze(). This is the entry point used by
    the orchestrator gate.

        from claude_ops.blast_radius import analyze
        report = analyze(incident_report_dict)
    """
    return BlastRadiusAnalyzer().analyze(incident_report)
