from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ImpactLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class DependencyKind(str, Enum):
    CONFIRMED = "CONFIRMED"
    INFERRED = "INFERRED"


@dataclass(frozen=True)
class AffectedComponent:
    name: str
    component_type: str
    impact: ImpactLevel
    dependency_kind: DependencyKind
    rationale: str
    evidence_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "component_type": self.component_type,
            "impact": self.impact.value,
            "dependency_kind": self.dependency_kind.value,
            "rationale": self.rationale,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass
class ImpactReport:
    root_cause: str
    service: str
    namespace: str
    generated_at: str
    affected_services: list[AffectedComponent] = field(default_factory=list)
    affected_apis: list[AffectedComponent] = field(default_factory=list)
    affected_code_components: list[AffectedComponent] = field(default_factory=list)
    affected_db_dependencies: list[AffectedComponent] = field(default_factory=list)
    affected_downstream_consumers: list[AffectedComponent] = field(default_factory=list)
    relevant_tests: list[AffectedComponent] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_cause": self.root_cause,
            "service": self.service,
            "namespace": self.namespace,
            "generated_at": self.generated_at,
            "affected_services": [c.to_dict() for c in self.affected_services],
            "affected_apis": [c.to_dict() for c in self.affected_apis],
            "affected_code_components": [c.to_dict() for c in self.affected_code_components],
            "affected_db_dependencies": [c.to_dict() for c in self.affected_db_dependencies],
            "affected_downstream_consumers": [c.to_dict() for c in self.affected_downstream_consumers],
            "relevant_tests": [c.to_dict() for c in self.relevant_tests],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)
