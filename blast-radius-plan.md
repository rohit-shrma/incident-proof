# Blast Radius Analysis Engine — Implementation Plan

## Top-Level Overview

**Goal:** Implement the Blast Radius Analysis engine for IncidentProof inside the three
empty stub files already created in `src/claude_ops/blast_radius/`. Given a confirmed root
cause from the existing incident investigation pipeline, the engine traverses the service
catalog and runbook index — both already present — to identify all potentially affected
components, classify each by impact severity, and emit a structured, machine-readable report.

**Scope:**
- Three files only: `__init__.py`, `analyzer.py`, `impact_report.py`
- Read-only throughout; no new MCP tools registered; no changes to existing code
- Designed to be called programmatically (from orchestrator or `/propose-fix` gate) and
  from the command line
- One new test file: `tests/test_blast_radius.py`

**Non-goals:**
- No live cluster queries during analysis (uses static catalog + already-collected evidence)
- No mutation of the cluster or existing reports
- No duplication of evidence storage (`raw_store`, `EvidenceRecord`) or error handling
  (`ToolError`, `ok`) — reuse them directly

---

## Architecture Diagram (for review — not for plan file)

The data flow is:

```
IncidentReport (existing schema)
        │
        ▼
  BlastRadiusAnalyzer.analyze()
        │ reads (read-only)
        ├── data/service_catalog.json     ← already an MCP resource
        ├── data/runbook_index.json       ← already an MCP resource
        └── existing EvidenceRecords      ← artifacts/ dir
        │
        ▼
  ImpactReport (new dataclass, JSON-serialisable)
        │
        ├── affected_services[]           ← HIGH/MEDIUM/LOW + confirmed/inferred
        ├── affected_apis[]
        ├── affected_code_components[]
        ├── affected_db_dependencies[]
        ├── affected_downstream_consumers[]
        ├── relevant_tests[]
        └── analysis_metadata{}
```

---

## Sub-Tasks

---

### Sub-Task 1 — `impact_report.py`: Data Models

**Intent:**
Define the complete set of frozen, JSON-serialisable dataclasses that represent the
blast-radius output. These models are the single source of truth for the report schema
consumed downstream (fix-generator, dashboards, etc.). They must mirror the style of
`EvidenceRecord` (frozen dataclasses with a `to_dict()` method) so the rest of the project
stays idiomatic.

**Expected Outcomes:**
- `ImpactLevel` enum: `HIGH`, `MEDIUM`, `LOW`
- `DependencyKind` enum: `CONFIRMED`, `INFERRED`
- `AffectedComponent` dataclass: component name, component type, impact level, dependency
  kind, rationale string, and optional list of evidence refs (strings, not EvidenceRecords
  — they're already stored in artifacts/)
- `ImpactReport` dataclass: root-cause summary (string), originating service/namespace,
  generated-at timestamp (ISO-8601 string), and six typed lists — one per affected-component
  category (services, APIs, code_components, db_dependencies, downstream_consumers,
  relevant_tests) — each of type `list[AffectedComponent]`. A `to_dict()` method must
  produce a fully JSON-serialisable `dict` (no enums in the output, use `.value`). A
  `to_json()` convenience method returns the JSON string.

**Todo List:**
1. Define `ImpactLevel` as a `str`-based `Enum` with values `"HIGH"`, `"MEDIUM"`, `"LOW"`
2. Define `DependencyKind` as a `str`-based `Enum` with values `"CONFIRMED"`, `"INFERRED"`
3. Define `AffectedComponent` as a `@dataclass(frozen=True)` with fields:
   `name: str`, `component_type: str`, `impact: ImpactLevel`, `dependency_kind: DependencyKind`,
   `rationale: str`, `evidence_refs: list[str]` (default empty list)
4. Define `ImpactReport` as a `@dataclass` (mutable, so lists can be built incrementally)
   with fields: `root_cause: str`, `service: str`, `namespace: str`, `generated_at: str`,
   `affected_services: list[AffectedComponent]`, `affected_apis: list[AffectedComponent]`,
   `affected_code_components: list[AffectedComponent]`,
   `affected_db_dependencies: list[AffectedComponent]`,
   `affected_downstream_consumers: list[AffectedComponent]`,
   `relevant_tests: list[AffectedComponent]`
5. Implement `ImpactReport.to_dict()` — recurse through all lists, convert enums to `.value`
6. Implement `ImpactReport.to_json(indent=2)` delegating to `json.dumps(self.to_dict(), ...)`
7. Export both dataclasses and both enums from `__init__.py`

**Relevant Context:**
- Pattern: `src/claude_ops/evidence/models.py` — `EvidenceRecord` as frozen dataclass with `to_dict()`
- Pattern: `src/claude_ops/errors.py` — `ErrorCategory` as `Literal`, `ToolError.to_dict()` using `asdict`
- `from __future__ import annotations` is used project-wide; follow the same header convention

**Status:** `[ ] pending`

---

### Sub-Task 2 — `analyzer.py`: Analysis Algorithm

**Intent:**
Implement `BlastRadiusAnalyzer` — the engine that receives a confirmed root cause and
produces an `ImpactReport` by traversing the service catalog and runbook index. The
algorithm must be deterministic, read-only, and use only data already available in the
project (no new I/O dependencies). It must produce clear HIGH/MEDIUM/LOW classification
and must distinguish confirmed dependencies (present in the catalog) from inferred ones
(derived by keyword matching against the root cause string and runbook text).

**Expected Outcomes:**
- `BlastRadiusAnalyzer` class with a single public method `analyze(incident_report: dict) -> ImpactReport`
- `incident_report` is the dict that already validates against `INCIDENT_REPORT_SCHEMA`
  (fields: `service`, `namespace`, `likely_causes`, `evidence`, `symptoms`, `severity`, etc.)
- The method returns a populated `ImpactReport`; it never raises for missing catalog data
  (returns partial report with a rationale note instead)
- Read-only safety: the analyzer only calls `Path.read_text()` and `json.loads()` — no writes

**Algorithm / Workflow:**

```
Step 1 — Load catalogs (read-only)
  Load data/service_catalog.json → list of service entries
  Load data/runbook_index.json + each matching runbook body

Step 2 — Extract root-cause signal from incident_report
  Combine: service, namespace, likely_causes[], symptoms[], evidence[].detail
  Build a normalized "signal set": lowercased tokens + full phrases

Step 3 — Identify the origin service entry in the catalog
  Match incident_report["service"] against catalog["services"][*]["name"]
  This service is always HIGH + CONFIRMED (it is the root-cause locus)

Step 4 — Classify affected services
  For each other catalog entry:
    - CONFIRMED + HIGH if the entry's name or labels appear in any evidence[].detail
    - INFERRED + MEDIUM if the entry's name appears in any runbook body that matched
      the root-cause signal
    - INFERRED + LOW otherwise (all remaining catalog services share the namespace
      and may be affected by node/network blast, but without specific evidence)
  Rationale string must say which evidence_ref or runbook id triggered the classification

Step 5 — Identify affected APIs
  Source: scan evidence[].detail for URL-shaped strings (/v1/..., /api/..., endpoint names)
  Classification:
    - CONFIRMED + HIGH if the API path appears in evidence with an error/failure detail
    - INFERRED + MEDIUM if it appears in a runbook excerpt matched to the cause
  Rationale: cite the evidence source or runbook id

Step 6 — Identify affected code components
  Source: scan likely_causes[] and evidence[].detail for:
    - Exception class names (CamelCase pattern or "Exception"/"Error" suffix)
    - File paths or package-like tokens (contains "." + no spaces, or ends in .py/.java/.go)
    - Function/method references (contains "()" or "at <class>.<method>")
  Classification:
    - CONFIRMED + HIGH if found in evidence[].detail with an error context
    - INFERRED + MEDIUM if found only in likely_causes[]

Step 7 — Identify database dependencies
  Source: scan evidence[].detail and likely_causes[] for database signal tokens:
    keywords: "kafka", "postgres", "db", "database", "redis", "mongo", "elasticsearch",
              "jdbc", "datasource", "connection pool", "commit rate"
  Classification:
    - CONFIRMED + HIGH if the token appears in evidence[].detail
    - INFERRED + MEDIUM if only in likely_causes[]
  Rationale: cite evidence_ref or cause string

Step 8 — Identify downstream consumers
  Source: service catalog entries whose name or labels are NOT the origin service;
    also scan runbook text for "downstream", "consumer", "caller", "dependency" patterns
    near the origin service name
  Classification:
    - CONFIRMED + HIGH if an evidence[].detail explicitly names a consumer failing
    - INFERRED + MEDIUM if the runbook for this incident type mentions downstream impact
    - INFERRED + LOW for all remaining same-namespace catalog services
      (they could be callers; without dependency graph, we cannot confirm)

Step 9 — Identify relevant tests
  Source: scan runbook bodies that matched the root-cause signal for "test", "unit test",
    "integration test", or test-file-shaped tokens (test_*.py, *Test.java, *_test.go)
  Also emit a generic INFERRED + HIGH entry for any code component identified in Step 6
    ("unit tests covering <component>") since a confirmed code defect always needs test coverage
  Classification: always INFERRED (test files are not in the evidence stream)

Step 10 — Assemble and return ImpactReport
  Populate all six lists, set generated_at = utcnow().isoformat(), return
```

**Impact Classification Rules (consolidated):**

| Evidence source | dependency_kind | impact |
|---|---|---|
| Named in `evidence[].detail` with error/failure context | `CONFIRMED` | `HIGH` |
| Named in `evidence[].detail` without error context | `CONFIRMED` | `MEDIUM` |
| Named in `likely_causes[]` only | `INFERRED` | `MEDIUM` |
| Matched via runbook text for this symptom | `INFERRED` | `MEDIUM` |
| Same namespace, no specific signal | `INFERRED` | `LOW` |

**Todo List:**
1. Create `BlastRadiusAnalyzer.__init__(self, catalog_path=None, runbook_index_path=None)`
   accepting optional path overrides for testability (default: resolve from `__file__` like
   `runbook_tools.py` does with `PROJECT_ROOT`)
2. Implement `_load_service_catalog()` → returns parsed list or `[]` on error
3. Implement `_load_runbooks_for_signal(signal_tokens: set[str])` → returns list of
   `{"id": str, "title": str, "text": str}` for runbooks whose title or body matches any token
4. Implement `_extract_signal_tokens(incident_report: dict) -> set[str]` — lower-case token
   set from `service`, `namespace`, `likely_causes`, `symptoms`, and `evidence[].detail`
5. Implement `_classify_services(incident_report, catalog, runbook_hits) -> list[AffectedComponent]`
   using the rules in Steps 3–4
6. Implement `_classify_apis(incident_report) -> list[AffectedComponent]`
   using URL-pattern regex scan in Steps 5
7. Implement `_classify_code_components(incident_report) -> list[AffectedComponent]`
   using exception/file/method patterns in Step 6
8. Implement `_classify_db_dependencies(incident_report) -> list[AffectedComponent]`
   using keyword scan in Step 7
9. Implement `_classify_downstream_consumers(incident_report, catalog, runbook_hits) -> list[AffectedComponent]`
   using Step 8
10. Implement `_classify_relevant_tests(incident_report, runbook_hits, code_components) -> list[AffectedComponent]`
    using Step 9
11. Implement the public `analyze(incident_report: dict) -> ImpactReport` that orchestrates
    Steps 1–10 and assembles the report
12. Add module-level `analyze(incident_report: dict) -> ImpactReport` convenience function
    that constructs a default `BlastRadiusAnalyzer` and calls `.analyze()` — this is the
    entry point used by the orchestrator gate

**Relevant Context:**
- `src/claude_ops/tools/runbook_tools.py` — `search_runbooks()` shows the exact pattern for
  loading `runbook_index.json` and reading runbook bodies; reuse `PROJECT_ROOT` resolution
- `src/claude_ops/schemas/incident_report_schema.py` — canonical field names of the dict
  passed in (`service`, `namespace`, `evidence`, `likely_causes`, `symptoms`, `severity`)
- `src/claude_ops/errors.py` — `ToolError`, `ok` for error envelope; do NOT re-raise, return
  a partial report with rationale
- `src/claude_ops/evidence/raw_store.py` — `store_raw_evidence` / `load_raw_evidence`
  patterns are available if we ever need to persist the ImpactReport as evidence; for now,
  the analyzer itself does not call `store_raw_evidence` — the caller decides

**Status:** `[ ] pending`

---

### Sub-Task 3 — `__init__.py`: Public API

**Intent:**
Make the `blast_radius` package importable with a clean, minimal public surface. The
orchestrator and MCP server (future) should be able to do
`from claude_ops.blast_radius import analyze, ImpactReport` without knowing the internal
module layout.

**Expected Outcomes:**
- `__init__.py` exports: `BlastRadiusAnalyzer`, `analyze`, `ImpactReport`, `AffectedComponent`,
  `ImpactLevel`, `DependencyKind`
- No logic in `__init__.py` itself — only re-exports

**Todo List:**
1. Add `from claude_ops.blast_radius.impact_report import ImpactReport, AffectedComponent, ImpactLevel, DependencyKind`
2. Add `from claude_ops.blast_radius.analyzer import BlastRadiusAnalyzer, analyze`
3. Add `__all__` listing all six names

**Relevant Context:**
- `src/claude_ops/evidence/__init__.py` — check whether it uses explicit `__all__` (it's
  empty; we should be explicit to be better than the rest of the package)

**Status:** `[ ] pending`

---

### Sub-Task 4 — `tests/test_blast_radius.py`: Test Suite

**Intent:**
Provide a focused, deterministic test suite that validates the core contracts of the
engine without mocking deep internals or relying on a live cluster. All tests use `tmp_path`
or in-memory fixtures; no network I/O.

**Expected Outcomes:**
A passing `pytest` run with tests covering:
1. `ImpactReport.to_dict()` round-trips correctly; enums are serialised as strings
2. `ImpactReport.to_json()` produces valid JSON
3. `analyze()` with a minimal valid `incident_report` returns an `ImpactReport` (smoke test)
4. The origin service is always classified as `HIGH` + `CONFIRMED`
5. A service that appears in evidence detail is classified as `HIGH` + `CONFIRMED`
6. A service that appears only in a runbook for the matched symptom is classified as
   `MEDIUM` + `INFERRED`
7. A service with no signal in evidence or runbooks is `LOW` + `INFERRED`
8. An API URL found in evidence detail with an error context is `HIGH` + `CONFIRMED`
9. An exception class token found in `likely_causes` is `MEDIUM` + `INFERRED`
10. A DB keyword found in `evidence[].detail` is `HIGH` + `CONFIRMED`
11. Relevant-tests list is non-empty when code components are identified
12. `BlastRadiusAnalyzer` accepts custom `catalog_path` and `runbook_index_path` (testability)
13. Analyzer does not raise when catalog file is missing — returns partial report

**Todo List:**
1. Create `tests/test_blast_radius.py`
2. Build a `minimal_report` pytest fixture (dict matching `INCIDENT_REPORT_SCHEMA`) that
   uses the real service names from `data/service_catalog.json` (`event-data`, `si`)
3. Build a `catalog_fixture` and `runbook_index_fixture` writing temp JSON files to `tmp_path`
   so tests are isolated from the real data directory
4. Write tests 1–13 above, one function each
5. Confirm all tests pass with `pytest tests/test_blast_radius.py`

**Relevant Context:**
- `tests/test_evidence_store.py` — shows `monkeypatch` + `tmp_path` patterns used in this project
- `tests/test_schema.py` — shows minimal report fixtures
- `pyproject.toml` — `testpaths = ["tests"]`, `pythonpath = ["src"]`

**Status:** `[ ] pending`

---

## Integration Points

### Where the engine is called from

| Call site | How | What it passes |
|---|---|---|
| Orchestrator, after root-cause confirmation | `from claude_ops.blast_radius import analyze` | Final `incident_report` dict (validated against `INCIDENT_REPORT_SCHEMA`) |
| `/propose-fix` gate (03-fix-proposal-gate.md) | Same import | Report loaded from `runs/<id>/report.md` |
| Future MCP tool `blast_radius_analyze` | Wraps `analyze()` the same way other tools wrap their domain modules | Same dict |

The engine returns an `ImpactReport`. The caller is responsible for deciding whether to
`store_raw_evidence()` the JSON output or write it directly to `runs/<id>/blast-radius.json`.
The analyzer itself does not write files — this keeps it pure and testable.

### Existing data sources consumed (read-only)

| Source | File | Already used by |
|---|---|---|
| Service catalog | `data/service_catalog.json` | `mcp/server.py` (`ops://service-catalog` resource) |
| Runbook index | `data/runbook_index.json` | `tools/runbook_tools.py` (`get_runbook_catalog`) |
| Runbook bodies | `data/runbooks/*.md` | `tools/runbook_tools.py` (`search_runbooks`) |
| Incident report dict | produced by incident-reporter agent | `schemas/incident_report_schema.py` |
| Evidence artifacts (optional) | `artifacts/ev_*.json` | `evidence/raw_store.py` (`load_raw_evidence`) |

### Existing utilities reused (not duplicated)

| Utility | Location | Use in blast radius |
|---|---|---|
| `ToolError` / `ok` | `errors.py` | Error envelope if `analyze()` is wrapped as MCP tool later |
| `EvidenceRecord` | `evidence/models.py` | `evidence_refs` list in `AffectedComponent` cites existing refs |
| `store_raw_evidence` | `evidence/raw_store.py` | Caller may persist the `ImpactReport.to_json()` as evidence |
| `PROJECT_ROOT` pattern | `tools/runbook_tools.py` | Same `Path(__file__).resolve().parents[N]` pattern in analyzer |
| `INCIDENT_REPORT_SCHEMA` | `schemas/incident_report_schema.py` | Defines the exact input dict shape |

---

## Test Strategy

- **Unit tests only** — no live cluster, no Prometheus, no IBM Cloud Logs
- **Fixture isolation** — `BlastRadiusAnalyzer` accepts `catalog_path` and
  `runbook_index_path` overrides so every test controls its own data via `tmp_path`
- **Contract tests** — verify `to_dict()` / `to_json()` serialization boundaries
- **Classification rule tests** — one test per classification rule row in the table above,
  using minimal synthetic fixtures
- **Negative/resilience tests** — missing catalog should not raise; empty evidence list should
  produce a non-empty report (origin service is always present)
- **No mocking of `Path.read_text`** — path overrides make monkeypatching unnecessary
- Pattern: follow `test_evidence_store.py` style (plain pytest functions, `tmp_path` fixture)

---

## Required Existing Data Sources

All data sources are already present in the repository. No new data files are required.

1. `data/service_catalog.json` — 3 services: `event-data`, `time-series-query`,
   `multi-system-processor`, all in namespace `si`, all `risk: production`
2. `data/runbook_index.json` + `data/runbooks/oom-restart.md`,
   `data/runbooks/kafka-commit-rate-low.md`, `data/runbooks/liveness-probe-failure.md`
3. `src/claude_ops/schemas/incident_report_schema.py` — input contract

---

## Sub-Task Execution Order

```
Sub-Task 1 (impact_report.py — data models)
        ↓
Sub-Task 2 (analyzer.py — algorithm, imports from Sub-Task 1)
        ↓
Sub-Task 3 (__init__.py — re-exports from Sub-Tasks 1 and 2)
        ↓
Sub-Task 4 (tests — imports from all three modules)
```

Each sub-task is a single focused file edit. Agent mode processes them one at a time.
After each, the plan status field is updated to `[x] done`.

---

## Open Questions for Review

1. **Evidence persistence**: Should `analyze()` itself call `store_raw_evidence()` to archive
   the ImpactReport, or leave that to the caller (orchestrator)? Current plan: leave it to
   the caller, keep the analyzer pure. Confirm?

2. **Service catalog coverage**: The catalog has only 3 services. The analyzer should emit
   `LOW + INFERRED` for all same-namespace catalog services with no matching signal. For
   services *not* in the catalog but referenced in evidence strings, should we still emit
   them as `INFERRED` components, or only catalog-registered services? Current plan:
   emit catalog-registered services only; unregistered names appear only in
   `affected_code_components` or `affected_apis` if they surface from evidence text. Confirm?

3. **Downstream consumer graph**: Without an explicit dependency graph, downstream consumers
   are inferred from catalog + runbook text only. Is this acceptable for v1, or should the
   catalog schema be extended with a `depends_on` field before implementation starts?
   Current plan: runbook + catalog text-scan only for v1; `depends_on` is a follow-on.

4. **MCP tool registration**: Should a `blast_radius_analyze` MCP tool be registered in
   `mcp/server.py` as part of this work, or is the Python API + orchestrator integration
   sufficient for now? Current plan: Python API only; MCP registration is a follow-on.
