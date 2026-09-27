# IncidentProof

When production breaks, IncidentProof investigates the evidence, identifies the root cause, measures the blast radius, reproduces the failure, generates a fix proposal, tests the fix, and produces a proof report.

IncidentProof turns incident response from guesswork into a verifiable evidence chain.

The workflow is:

INCIDENT
  ↓
INVESTIGATE
  ↓
ROOT CAUSE
  ↓
BLAST RADIUS
  ↓
REPRODUCE
  ↓
GENERATE FIX
  ↓
SAFETY GATE
  ↓
REGRESSION TEST
  ↓
VERIFY
  ↓
PROOF REPORT
  ↓
DRAFT PR
  ↓
HUMAN APPROVAL

Claude Ops Investigator helps engineers investigate Kubernetes incidents safely by combining read-only operational tools, external evidence storage, compact investigation memory, and human-controlled remediation boundaries.

The goal is not to give an AI unrestricted production access. The goal is to expose narrow, auditable, read-only interfaces that help engineers gather evidence, form hypotheses, rule out causes, and produce reliable incident reports faster.

## What this project provides

- AI-assisted incident investigation
- Evidence-grounded root-cause analysis
- Parallel investigation across Kubernetes, metrics, logs, and runbooks
- Blast-radius analysis across affected services and dependencies
- Automatic incident reproduction
- AI-generated fix proposals
- Safety gate before verification or risky actions
- Automatic regression-test generation
- Independent fix verification
- Evidence-backed proof reports
- Draft-only PR workflow with human approval
- Auditable evidence refrences and investigation artifacts

## Safety model

IncidentProof is designed around controlled automation rather than unrestricted production access.

The system separates investigation, remediation, verification, and human approval:

- Investigation uses read-only evidence gathering.
- Root-cause findings are backed by collected evidence.
- Reproduction runs through controlled commands with timeouts.
- Proposed fixes pass through a safety gate before verification.
- Regression tests are generated before declaring a fix successful.
- Verification checks that the expected behavior is restored.
- The final proof report records the evidence chain and verification result.
- Code changes are never silently pushed to production.
- PR creation is draft-only and remains subject to human review.

Potentially destructive commands are explicitly blocked by the verification safety layer.

## Quick start

Clone the repository and install the project:

```cmd
git clone https://github.com/rohit-shrma/incident-proof.git
cd incident-proof
python -m venv .venv

Install the project dependencies:

    pip install -e ".[dev]"

Run the test suite:

    python -m pytest

Run the IncidentProof end-to-end demo:

    python -m claude_ops.orchestration.demo

The demo runs the complete IncidentProof workflow:

    INCIDENT
      ↓
    INVESTIGATE
      ↓
    ROOT CAUSE
      ↓
    BLAST RADIUS
      ↓
    REPRODUCE
      ↓
    GENERATE FIX
      ↓
    SAFETY GATE
      ↓
    REGRESSION TEST
      ↓
    VERIFY
      ↓
    PROOF REPORT

The generated proof report is written to:

    reports/

The demo uses a simulated incident and does not require access to a real
production Kubernetes cluster.

For live operational investigations, optional Kubernetes, Prometheus, and
IBM Cloud Logs configuration is described in the environment sections below.

## Slash commands

IncidentProof provides two complementary workflows: investigation and
fix generation.

### `/investigate-incident`

Starts an evidence-driven incident investigation.

```text
/investigate-incident

The investigation workflow:

1. Collects incident evidence.
2. Forms and evaluates possible root causes.
3. Analyzes the blast radius.
4. Reproduces the reported failure when possible.
5. Generates a structured incident result.
6. Preserves evidence references for auditability.

### `/propose-fix`

Generates a fix proposal after an incident has been investigated.

The workflow:

1. Uses the investigation findings and root cause.
2. Generates a proposed code change.
3. Applies safety checks before verification.
4. Generates regression tests.
5. Verifies the proposed fix.
6. Produces a proof report.
7. Keeps human approval in the loop before code changes are merged.

The two workflows are intentionally separated: investigation does not
automatically modify code or production systems.

### Claude Code slash commands

The main interactive workflow is the `/investigate-incident` slash command:

```
/investigate-incident namespace=<namespace> service=<service> symptom="<specific symptom>" since_minutes=<minutes>
```

`symptom` is required — this workflow is symptom-driven, not a generic
service health check. If no symptom is given, Claude asks for one before
investigating anything.

Examples:

```
/investigate-incident namespace=si service=multi-system-processor symptom="readiness probe failures during recent rollout" since_minutes=60
/investigate-incident namespace=si service=event-data symptom="KafkaConsumerCommitRateLow alert fired" since_minutes=120
/investigate-incident namespace=si service=multi-system-processor symptom="OOMKilled restarts observed" since_minutes=180
```

What it does:

1. Mints an `investigation_id` and creates `runs/<investigation_id>/scratchpad/`,
   then delegates to the `incident-coordinator` subagent (falls back to a
   single agent, with that fallback stated explicitly, only if subagents
   aren't available)
2. The coordinator reads the service catalog and runbook catalog, then routes
   the symptom to the narrowest relevant specialist subagents:
   - `k8s-evidence-collector` — pod listing, describe, live logs, namespace
     events, current resource usage
   - `prometheus-analyst` — restart counts/increase, CPU, memory, HTTP error
     rate, latency p95
   - `log-analyst` — historical IBM Cloud Logs search (errors, probe
     failures, arbitrary text) spanning restarts/deployments
   - `runbook-analyst` — matches the symptom against local runbooks
3. Every specialist stores raw evidence as an `evidence_ref` and hands back
   only summaries/findings — the coordinator never gathers evidence directly.
   Each also writes a concise markdown scratchpad (scope, tools called, key
   findings, evidence_refs, unknowns/gaps, decisions, handoff summary) to its
   assigned `runs/<investigation_id>/scratchpad/wave<N>-<subagent-name>.md`
   file — never raw log/metric bodies, only summaries and evidence_refs. The
   coordinator maintains its own running Structured Finding Brief at
   `coordinator-brief.md` in the same directory, and passes each subagent
   that brief plus any relevant prior scratchpad paths in its task prompt.
4. `incident-reporter` runs last, synthesizing all subagents' findings (never
   its own) into a single evidence-grounded, schema-valid report
5. The final output includes a "Subagent usage audit" table: which subagent
   ran, what it did, which tools/evidence_refs/scratchpad path it used, and
   its result

What it does not do:

- Does not mutate Kubernetes resources
- Does not restart pods
- Does not apply fixes
- Does not run destructive commands
- Does not fetch raw evidence detail unless needed

### Bob Shell slash commands

Bob Shell (`.bob/`) is a parallel harness that talks to the same MCP tool
layer and exposes the same two commands.

#### `/investigate-incident`

Read-only, same behavior and args as the Claude Code version above:

```
/investigate-incident namespace=<namespace> service=<service> symptom="<specific symptom>" since_minutes=<minutes>
```

An orchestrator mode decomposes the incident and delegates to the same four
specialist roles (`k8s-evidence-collector`, `prometheus-analyst`,
`log-analyst`, `runbook-analyst`), then hands off to `incident-reporter` for
a schema-valid, evidence-grounded report — see `.bob/commands/investigate-incident.md`
and `AGENTS.md` for the full workflow.

#### `/propose-fix`

A separate, autonomous command. It only fires when an incident report traces
the cause to a named application-code location (an exception class, stack
trace, or file/function reference — not an infra/operational finding); if
that gate isn't met, no fix is proposed. When it does fire, it:

- Works only in the target service's own existing local git checkout (looked
  up from `data/service_catalog.json`) — it never clones a repo.
- Requires a clean working tree first — any uncommitted changes to tracked
  files stop it immediately, nothing is stashed or discarded.
- Opens a **draft-only** PR, with an AI-disclosure line and a human-review
  checklist in the description. It never opens a non-draft PR.

Args:

```
/propose-fix namespace=<namespace> service=<service> symptom="<symptom>" since_minutes=<minutes>
/propose-fix investigation_id=<id>|latest
```

Optional: `dry_run=true` (locates the code and narrates the proposed fix to
a scratchpad file without branching, committing, pushing, or opening a PR)
and `base_branch=<branch>` (defaults to whatever branch is already checked
out in the local checkout if omitted).

`/investigate-incident` never triggers `/propose-fix` — they are separate
commands, and a code change only ever happens when `/propose-fix` is run
explicitly.

## Environment for optional tools

IncidentProof can connect to external operational evidence sources when
configured. These integrations are optional for the local demo.

### Prometheus

Set the following environment variables when using Prometheus metrics:

- `PROMETHEUS_URL`
- `PROMETHEUS_AUTO_PORT_FORWARD`
- `PROMETHEUS_PF_SERVICE`
- `PROMETHEUS_PF_NAMESPACE`

### IBM Cloud Logs

Set the following environment variables when using IBM Cloud Logs:

- `IBM_LOGS_ENDPOINT`
- `IBM_CLOUD_API_KEY`

### Local configuration

Copy `.env.example` to `.env` and add your local values.

The `.env` file is gitignored and must never be committed to the repository.
Secrets should not be placed in `.mcp.json`.

The local IncidentProof demo does not require these external credentials.

## No-token local tests

The project includes a local test suite that exercises the core IncidentProof
engines without requiring access to a real production environment.

Run the complete test suite:

    python -m pytest

The test suite covers:

- Blast-radius analysis
- Incident reproduction
- Safety-gated verification
- Automatic regression-test generation
- Evidence storage
- Proof-report generation
- MCP tools and structured error handling

The local end-to-end demo also runs without real Kubernetes, Prometheus, or
IBM Cloud Logs credentials:

    python -m claude_ops.orchestration.demo

## Local environment

IncidentProof can run locally without connecting to a production environment.

For the local demo, no Kubernetes, Prometheus, IBM Cloud Logs, or production
credentials are required.

Optional integrations can be configured through a local `.env` file:

- `PROMETHEUS_URL`
- `IBM_LOGS_ENDPOINT`
- `IBM_CLOUD_API_KEY`

The `.env` file is gitignored and must never be committed to the repository.

For local development:

    pip install -e ".[dev]"
    python -m pytest

To run the end-to-end IncidentProof demonstration:

    python -m claude_ops.orchestration.demo

The local demo uses a simulated incident and does not require production
credentials or access to a real production cluster.

## Harness hooks (safety gate + audit trail)

`.claude/settings.json` configures four read-only Claude Code hooks under
`.claude/hooks/`. These hooks provide a harness-level safety net and audit
trail alongside the application-level guardrails in
`src/claude_ops/hooks.py` and `schemas/incident_report_schema.py`.

The hooks do not call Kubernetes, Prometheus, IBM Cloud Logs, or the Claude
API. They only inspect the JSON that Claude Code passes to them through
stdin. Their only file output is JSONL audit logs under `runs/`, which is
gitignored.

| Hook | Event | What it does |
|---|---|---|
| `block_unsafe_shell.py` | `PreToolUse` on `Bash` | Blocks raw shell commands such as `kubectl delete`, `kubectl apply`, `kubectl patch`, `kubectl scale`, `kubectl rollout restart`, `kubectl exec`, and `helm upgrade`. This provides a second safety gate for destructive commands reaching `Bash` directly. |
| `audit_mcp_tool_call.py` | `PostToolUse` on MCP tools | Records completed MCP tool calls in `runs/mcp-tool-audit.jsonl`, including the tool name, timestamp, status, evidence reference, and session ID. |
| `audit_subagent_lifecycle.py` | `SubagentStart` / `SubagentStop` | Records subagent lifecycle events in `runs/subagent-audit.jsonl`, including the event, timestamp, session ID, subagent type, and description. |
| `validate_final_report.py` | `Stop` | Validates incident-report-style final responses before the session stops. When applicable, it checks for evidence references, a Subagent usage audit table, `ruled_out`, `unknowns`, and an explicit confirmed/not-confirmed statement. Missing required information blocks the stop with an explanation. Ordinary conversational responses are left unchanged. |

Together, these hooks provide an additional safety and audit layer around
the Claude Code workflow without directly accessing production systems.

### Disabling hooks locally

Hooks are enabled by default because they provide safety checks and audit
trails during the Claude Code workflow.

If hooks need to be disabled temporarily for local development, there are two
options:

- **Disable everything:** Add `"disableAllHooks": true` to
  `.claude/settings.local.json`. This file is gitignored and intended for
  personal local settings. Do not add this setting to the shared
  `.claude/settings.json`.

- **Disable only the IncidentProof hooks:** Set
  `CLAUDE_OPS_HOOKS_DISABLED=1` in the shell environment before launching
  Claude Code. Each hook checks this variable at startup and exits without
  performing its safety or audit action.

Disabling the hooks is a local development option and does not change the
application-level safety controls in the IncidentProof codebase.

## Recommended first live use

For the first live operational investigation, use a non-production namespace
rather than a production environment.

The investigation can be started with the following command:

    python -m claude_ops.main investigate --namespace <non-production-namespace> --service <service-name> --since-minutes 120

This command collects an investigation snapshot for the specified service and
time window.

After the investigation completes, provide the generated JSON snapshot to
Claude or Claude Code and ask it to produce an incident report using the
schema defined in:

    src/claude_ops/schemas/incident_report_schema.py

Review the generated findings and evidence before taking any remediation
action. The investigation workflow is intended to support human review rather
than automatically modifying production systems.

## MCP client/server map

IncidentProof uses the Model Context Protocol (MCP) to connect Claude Code
with the project's operational investigation tools.

The project uses the following MCP architecture:

    Claude Code = MCP client
    src/claude_ops/mcp/server.py = local MCP server
    .mcp.json = project-level MCP client configuration for Claude Code

The MCP server can be started manually for a local syntax or startup check:

    python -m claude_ops.mcp.server

For Claude Code, keep `.mcp.json` in the project root. Claude Code reads this
configuration and launches the MCP server over STDIO.

An optional local smoke test is available when the MCP development dependency
is installed:

    pip install -e ".[dev,mcp]"
    python scripts/mcp_smoke_client.py

### MCP resources

- `ops://runbook-catalog`
- `ops://service-catalog`

### MCP tools

- `k8s_list_pods`
- `k8s_describe_pod`
- `k8s_get_pod_logs`
- `k8s_get_recent_namespace_events`
- `k8s_top_pods`
- `runbook_search`
- `prom_query_instant`
- `prom_get_pod_restart_counts`
- `prom_get_pod_restart_increase`
- `prom_get_pod_cpu_usage`
- `prom_get_pod_memory_usage`
- `prom_get_http_error_rate`
- `prom_get_latency_p95`
- `prom_ensure_connection`
- `ibm_logs_search`
- `ibm_logs_search_errors`
- `ibm_logs_search_probe_failures`
- `ibm_logs_search_text`
- `evidence_get_detail`

### MCP prompt

- `investigate_incident`

These MCP resources, tools, and prompts provide Claude Code with structured
access to the evidence sources used by the IncidentProof investigation
workflow.