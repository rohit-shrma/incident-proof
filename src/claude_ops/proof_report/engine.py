from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProofSection:
    title: str
    status: str
    details: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProofReport:
    incident: str
    root_cause: str
    confidence: str
    sections: tuple[ProofSection, ...]
    evidence_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_markdown(self) -> str:
        lines = [
            f"# Incident Proof Report",
            "",
            f"**Incident:** {self.incident}",
            f"**Root Cause:** {self.root_cause}",
            f"**Confidence:** {self.confidence}",
            "",
            "## Evidence Chain",
            "",
        ]

        for section in self.sections:
            lines.append(f"### {section.title} — {section.status}")

            if section.details:
                for detail in section.details:
                    lines.append(f"- {detail}")
            else:
                lines.append("- No details recorded.")

            lines.append("")

        if self.evidence_refs:
            lines.extend(
                [
                    "## Evidence References",
                    "",
                ]
            )

            for ref in self.evidence_refs:
                lines.append(f"- `{ref}`")

            lines.append("")

        return "\n".join(lines).rstrip() + "\n"


class ProofReportGenerator:
    """
    Builds an auditable incident report from investigation evidence.

    The generator does not execute commands or modify infrastructure.
    It only records the evidence and decisions supplied by the caller.
    """

    REQUIRED_SECTION_TITLES = (
        "Investigation",
        "Blast Radius",
        "Reproduction",
        "Fix",
        "Verification",
        "Regression Test",
    )

    def generate(
        self,
        *,
        incident: str,
        root_cause: str,
        confidence: str,
        investigation: list[str],
        blast_radius: list[str],
        reproduction: list[str],
        fix: list[str],
        verification: list[str],
        regression_test: list[str],
        evidence_refs: list[str] | tuple[str, ...] = (),
    ) -> ProofReport:
        if not incident.strip():
            raise ValueError("Incident cannot be empty.")

        if not root_cause.strip():
            raise ValueError("Root cause cannot be empty.")

        if not confidence.strip():
            raise ValueError("Confidence cannot be empty.")

        sections = (
            ProofSection("Investigation", "completed", investigation),
            ProofSection("Blast Radius", "analyzed", blast_radius),
            ProofSection("Reproduction", "reproduced", reproduction),
            ProofSection("Fix", "generated", fix),
            ProofSection("Verification", "verified", verification),
            ProofSection("Regression Test", "generated", regression_test),
        )

        return ProofReport(
            incident=incident.strip(),
            root_cause=root_cause.strip(),
            confidence=confidence.strip(),
            sections=sections,
            evidence_refs=tuple(evidence_refs),
        )

    def write_markdown(
        self,
        report: ProofReport,
        output_path: Path | str,
    ) -> Path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report.to_markdown(), encoding="utf-8")
        return path

    def write_json(
        self,
        report: ProofReport,
        output_path: Path | str,
    ) -> Path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(report.to_dict(), indent=2),
            encoding="utf-8",
        )
        return path