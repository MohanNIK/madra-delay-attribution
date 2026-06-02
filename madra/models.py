from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
from typing import Any


class SchemaValidationError(ValueError):
    def __init__(self, *, role: str, missing_fields: list[str], raw: Any):
        self.role = role
        self.missing_fields = missing_fields
        self.raw = raw
        excerpt = repr(raw)
        if len(excerpt) > 500:
            excerpt = excerpt[:500] + "..."
        super().__init__(
            f"Invalid schema for {role}; missing/invalid fields: "
            f"{', '.join(missing_fields)}; raw={excerpt}"
        )


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(number) or math.isinf(number):
        return default
    return number


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _normalise_terms(text: str) -> set[str]:
    return {term.lower() for term in re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]+", text)}


def _normalise_allocation(raw: dict[str, Any]) -> dict[str, float]:
    allocation = {str(k): _as_float(v) for k, v in dict(raw).items()}
    values = list(allocation.values())
    if values and max(abs(value) for value in values) <= 1.0 and sum(abs(value) for value in values) <= 1.5:
        allocation = {party: round(value * 100.0, 4) for party, value in allocation.items()}
    return allocation


@dataclass(frozen=True)
class EvidenceSpan:
    span_id: str
    text: str
    source: str = "case"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceSpan":
        span_id = str(data.get("span_id") or data.get("id") or "").strip()
        text = str(data.get("text") or "").strip()
        if not span_id or not text:
            raise SchemaValidationError(role="evidence_span", missing_fields=["span_id/text"], raw=data)
        return cls(span_id=span_id, text=text, source=str(data.get("source") or "case"))

    def to_dict(self) -> dict[str, Any]:
        return {"span_id": self.span_id, "text": self.text, "source": self.source}


@dataclass(frozen=True)
class CaseRecord:
    case_id: str
    project_type: str
    dispute_type: str
    parties: dict[str, str]
    facts: list[str]
    claims: list[str]
    evidence_spans: list[EvidenceSpan]
    reasoning_spans: list[EvidenceSpan]
    final_decision: str
    liability_label: str
    allocation_ground_truth: dict[str, float]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CaseRecord":
        evidence = [EvidenceSpan.from_dict(item) for item in _as_list(data.get("evidence_spans")) if isinstance(item, dict)]
        reasoning = [EvidenceSpan.from_dict(item) for item in _as_list(data.get("reasoning_spans")) if isinstance(item, dict)]
        missing: list[str] = []
        for field_name in [
            "case_id",
            "project_type",
            "dispute_type",
            "parties",
            "facts",
            "claims",
            "final_decision",
            "liability_label",
            "allocation_ground_truth",
        ]:
            if data.get(field_name) in (None, "", []):
                missing.append(field_name)
        if not evidence:
            missing.append("evidence_spans")
        if missing:
            raise SchemaValidationError(role="case_record", missing_fields=missing, raw=data)
        return cls(
            case_id=str(data["case_id"]),
            project_type=str(data["project_type"]),
            dispute_type=str(data["dispute_type"]),
            parties={str(k): str(v) for k, v in dict(data["parties"]).items()},
            facts=[str(item) for item in _as_list(data["facts"])],
            claims=[str(item) for item in _as_list(data["claims"])],
            evidence_spans=evidence,
            reasoning_spans=reasoning,
            final_decision=str(data["final_decision"]),
            liability_label=str(data["liability_label"]),
            allocation_ground_truth={
                str(k): _as_float(v) for k, v in dict(data["allocation_ground_truth"]).items()
            },
        )

    def valid_evidence_ids(self) -> set[str]:
        return {span.span_id for span in self.evidence_spans}

    def text_for_prompt(self) -> str:
        parts = [
            f"Project type: {self.project_type}",
            f"Dispute type: {self.dispute_type}",
            "Parties: " + ", ".join(f"{k}={v}" for k, v in self.parties.items()),
            "Facts:\n" + "\n".join(f"- {item}" for item in self.facts),
            "Claims:\n" + "\n".join(f"- {item}" for item in self.claims),
        ]
        return "\n\n".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "project_type": self.project_type,
            "dispute_type": self.dispute_type,
            "parties": self.parties,
            "facts": self.facts,
            "claims": self.claims,
            "evidence_spans": [item.to_dict() for item in self.evidence_spans],
            "reasoning_spans": [item.to_dict() for item in self.reasoning_spans],
            "final_decision": self.final_decision,
            "liability_label": self.liability_label,
            "allocation_ground_truth": self.allocation_ground_truth,
        }


@dataclass(frozen=True)
class CaseInput:
    case_id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> CaseRecord:
        return CaseRecord(
            case_id=self.case_id,
            project_type=str(self.metadata.get("project_type", "unknown")),
            dispute_type=str(self.metadata.get("dispute_type", "delay responsibility")),
            parties={str(k): str(v) for k, v in dict(self.metadata.get("parties", {})).items()},
            facts=[self.text],
            claims=[],
            evidence_spans=[EvidenceSpan(span_id="E1", text=self.text, source="case")],
            reasoning_spans=[],
            final_decision="",
            liability_label=str(self.metadata.get("liability_label", "unknown")),
            allocation_ground_truth={},
        )


@dataclass
class AgentOutput:
    agent_role: str
    liability_label: str
    allocation: dict[str, float]
    key_claims: list[str]
    evidence_ids: list[str]
    reasoning_steps: list[str]
    uncertainty: float
    unsupported_claims: list[str]

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        *,
        valid_evidence_ids: set[str] | None = None,
        role: str | None = None,
    ) -> "AgentOutput":
        if not isinstance(data, dict):
            raise SchemaValidationError(role=role or "agent", missing_fields=["json_object"], raw=data)
        translated = dict(data)
        if "agent_role" not in translated and "agent_name" in translated:
            translated["agent_role"] = translated["agent_name"]
        if "key_claims" not in translated and "claims" in translated:
            translated["key_claims"] = translated["claims"]
        if "evidence_ids" not in translated and "evidence" in translated:
            translated["evidence_ids"] = [
                str(item.get("span_id")) for item in translated["evidence"] if isinstance(item, dict) and item.get("span_id")
            ]
        if "reasoning_steps" not in translated and "rationale" in translated:
            translated["reasoning_steps"] = [str(translated["rationale"])]
        if "unsupported_claims" not in translated:
            translated["unsupported_claims"] = []

        required = [
            "agent_role",
            "liability_label",
            "allocation",
            "key_claims",
            "evidence_ids",
            "reasoning_steps",
            "uncertainty",
            "unsupported_claims",
        ]
        missing = [name for name in required if name not in translated]
        if missing:
            raise SchemaValidationError(role=role or str(translated.get("agent_role") or "agent"), missing_fields=missing, raw=data)

        evidence_ids = [str(item) for item in _as_list(translated["evidence_ids"]) if str(item)]
        invalid_ids = []
        if valid_evidence_ids is not None:
            invalid_ids = [item for item in evidence_ids if item not in valid_evidence_ids]
        if invalid_ids:
            raise SchemaValidationError(
                role=role or str(translated["agent_role"]),
                missing_fields=[f"valid_evidence_ids({','.join(invalid_ids)})"],
                raw=data,
            )

        return cls(
            agent_role=str(translated["agent_role"]),
            liability_label=str(translated["liability_label"]),
            allocation=_normalise_allocation(translated["allocation"]),
            key_claims=[str(item) for item in _as_list(translated["key_claims"])],
            evidence_ids=evidence_ids,
            reasoning_steps=[str(item) for item in _as_list(translated["reasoning_steps"])],
            uncertainty=_as_float(translated["uncertainty"], default=0.5),
            unsupported_claims=[str(item) for item in _as_list(translated["unsupported_claims"])],
        )

    @property
    def agent_name(self) -> str:
        return self.agent_role

    @property
    def claims(self) -> list[str]:
        return self.key_claims

    def unsupported_claim_count(self) -> int:
        return len(self.unsupported_claims)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_role": self.agent_role,
            "liability_label": self.liability_label,
            "allocation": self.allocation,
            "key_claims": self.key_claims,
            "evidence_ids": self.evidence_ids,
            "reasoning_steps": self.reasoning_steps,
            "uncertainty": self.uncertainty,
            "unsupported_claims": self.unsupported_claims,
        }


@dataclass
class ManagementImplications:
    key_risk_points: list[str]
    evidence_preparation_suggestions: list[str]
    claim_negotiation_focus: list[str]
    preventive_actions: list[str]

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ManagementImplications":
        data = data or {}
        return cls(
            key_risk_points=[str(item) for item in _as_list(data.get("key_risk_points"))],
            evidence_preparation_suggestions=[
                str(item) for item in _as_list(data.get("evidence_preparation_suggestions"))
            ],
            claim_negotiation_focus=[str(item) for item in _as_list(data.get("claim_negotiation_focus"))],
            preventive_actions=[str(item) for item in _as_list(data.get("preventive_actions"))],
        )

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "key_risk_points": self.key_risk_points,
            "evidence_preparation_suggestions": self.evidence_preparation_suggestions,
            "claim_negotiation_focus": self.claim_negotiation_focus,
            "preventive_actions": self.preventive_actions,
        }


@dataclass
class CoordinationOutput:
    liability_label: str
    allocation: dict[str, float]
    key_claims: list[str]
    evidence_ids: list[str]
    consensus_score: float
    disagreement_score: float
    unsupported_claim_rate: float
    conflict_points: list[str]
    rationale: str
    management_implications: ManagementImplications

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        *,
        valid_evidence_ids: set[str] | None = None,
    ) -> "CoordinationOutput":
        translated = dict(data)
        if "evidence_ids" not in translated and "evidence_chain" in translated:
            translated["evidence_ids"] = [
                str(item.get("span_id")) for item in translated["evidence_chain"] if isinstance(item, dict) and item.get("span_id")
            ]
        if "key_claims" not in translated:
            translated["key_claims"] = []
        if "conflict_points" not in translated:
            translated["conflict_points"] = []
        if "management_implications" not in translated:
            translated["management_implications"] = {}
        required = [
            "liability_label",
            "allocation",
            "evidence_ids",
            "consensus_score",
            "disagreement_score",
            "unsupported_claim_rate",
            "rationale",
        ]
        missing = [name for name in required if name not in translated]
        if missing:
            raise SchemaValidationError(role="coordination", missing_fields=missing, raw=data)
        evidence_ids = [str(item) for item in _as_list(translated["evidence_ids"]) if str(item)]
        if valid_evidence_ids is not None:
            evidence_ids = [item for item in evidence_ids if item in valid_evidence_ids]
        return cls(
            liability_label=str(translated["liability_label"]),
            allocation=_normalise_allocation(translated["allocation"]),
            key_claims=[str(item) for item in _as_list(translated["key_claims"])],
            evidence_ids=evidence_ids,
            consensus_score=_as_float(translated["consensus_score"]),
            disagreement_score=_as_float(translated["disagreement_score"], default=1.0),
            unsupported_claim_rate=_as_float(translated["unsupported_claim_rate"], default=1.0),
            conflict_points=[str(item) for item in _as_list(translated["conflict_points"])],
            rationale=str(translated["rationale"]),
            management_implications=ManagementImplications.from_dict(translated.get("management_implications")),
        )

    @property
    def evidence_chain(self) -> list[EvidenceSpan]:
        return [EvidenceSpan(span_id=item, text=item, source="evidence_id") for item in self.evidence_ids]

    def to_dict(self) -> dict[str, Any]:
        return {
            "liability_label": self.liability_label,
            "allocation": self.allocation,
            "key_claims": self.key_claims,
            "evidence_ids": self.evidence_ids,
            "consensus_score": self.consensus_score,
            "disagreement_score": self.disagreement_score,
            "unsupported_claim_rate": self.unsupported_claim_rate,
            "conflict_points": self.conflict_points,
            "rationale": self.rationale,
            "management_implications": self.management_implications.to_dict(),
        }


@dataclass
class DeliberationRound:
    round_index: int
    agent_outputs: list[AgentOutput]
    coordination: CoordinationOutput

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_index": self.round_index,
            "agent_outputs": [item.to_dict() for item in self.agent_outputs],
            "coordination": self.coordination.to_dict(),
        }


@dataclass
class MADRAResult:
    case_id: str
    final: CoordinationOutput
    rounds: list[DeliberationRound]
    mode: str = "full"
    run_index: int = 0
    seed: int | None = None
    temperature: float = 0.0
    audit_log: list[dict[str, Any]] = field(default_factory=list)
    blackboard_state: dict[str, Any] | None = None

    @property
    def rounds_completed(self) -> int:
        return len(self.rounds)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "mode": self.mode,
            "run_index": self.run_index,
            "seed": self.seed,
            "temperature": self.temperature,
            "rounds_completed": self.rounds_completed,
            "final": self.final.to_dict(),
            "rounds": [item.to_dict() for item in self.rounds],
            "audit_log": self.audit_log,
            "blackboard_state": self.blackboard_state,
        }
