from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from .argument_graph import ArgumentGraph, ClaimNode, EvidenceNode, ResponsibilityNode
from .messages import BaseMessage
from .models import CaseRecord, EvidenceSpan
from .workflow import WorkflowTrace


@dataclass
class EvidenceRegistry:
    spans: dict[str, EvidenceSpan] = field(default_factory=dict)

    @classmethod
    def from_case(cls, case: CaseRecord) -> "EvidenceRegistry":
        return cls(spans={span.span_id: span for span in case.evidence_spans})

    def register(self, span: EvidenceSpan) -> None:
        self.spans[span.span_id] = span

    def valid_ids(self) -> set[str]:
        return set(self.spans)

    def to_dict(self) -> dict[str, Any]:
        return {span_id: span.to_dict() for span_id, span in self.spans.items()}


@dataclass
class ClaimLedger:
    claims: dict[str, dict[str, Any]] = field(default_factory=dict)

    def add_claim(self, *, claim_id: str, text: str, agent_role: str, evidence_ids: list[str]) -> None:
        self.claims[claim_id] = {
            "claim_id": claim_id,
            "text": text,
            "agent_role": agent_role,
            "evidence_ids": evidence_ids,
            "status": "submitted",
        }

    def mark_status(self, claim_id: str, status: str, details: str = "") -> None:
        if claim_id in self.claims:
            self.claims[claim_id]["status"] = status
            if details:
                self.claims[claim_id]["details"] = details

    def to_dict(self) -> dict[str, Any]:
        return self.claims


@dataclass
class ConflictGraph:
    conflicts: list[dict[str, Any]] = field(default_factory=list)

    def add_conflict(self, *, conflict_type: str, description: str, agent_roles: list[str], evidence_ids: list[str]) -> None:
        self.conflicts.append(
            {
                "conflict_id": f"K-{uuid4().hex[:10]}",
                "conflict_type": conflict_type,
                "description": description,
                "agent_roles": agent_roles,
                "evidence_ids": evidence_ids,
                "status": "open",
            }
        )

    def resolve_all(self) -> None:
        for conflict in self.conflicts:
            conflict["status"] = "resolved"

    def open_conflicts(self) -> list[dict[str, Any]]:
        return [item for item in self.conflicts if item.get("status") == "open"]

    def to_dict(self) -> dict[str, Any]:
        return {"conflicts": self.conflicts}


@dataclass
class ConsensusState:
    disagreement_score: float = 1.0
    consensus_score: float = 0.0
    unsupported_claim_rate: float = 1.0
    stop_condition_satisfied: bool = False
    round_index: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_index": self.round_index,
            "disagreement_score": self.disagreement_score,
            "consensus_score": self.consensus_score,
            "unsupported_claim_rate": self.unsupported_claim_rate,
            "stop_condition_satisfied": self.stop_condition_satisfied,
        }


@dataclass
class AuditLog:
    events: list[dict[str, Any]] = field(default_factory=list)

    def append(self, event_type: str, *, actor: str, round_id: int, details: dict[str, Any] | None = None) -> None:
        self.events.append(
            {
                "event_id": f"A-{uuid4().hex[:12]}",
                "event_type": event_type,
                "actor": actor,
                "round_id": round_id,
                "details": details or {},
            }
        )

    def export_jsonl(self, path: str | Path) -> None:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            "\n".join(json.dumps(event, ensure_ascii=False) for event in self.events)
            + ("\n" if self.events else ""),
            encoding="utf-8",
        )

    def to_dict(self) -> list[dict[str, Any]]:
        return self.events


@dataclass
class BlackboardState:
    case_record: CaseRecord
    evidence_registry: EvidenceRegistry
    claim_ledger: ClaimLedger = field(default_factory=ClaimLedger)
    argument_graph: ArgumentGraph = field(default_factory=ArgumentGraph)
    message_pool: list[BaseMessage] = field(default_factory=list)
    verification_records: list[dict[str, Any]] = field(default_factory=list)
    conflict_graph: ConflictGraph = field(default_factory=ConflictGraph)
    consensus_state: ConsensusState = field(default_factory=ConsensusState)
    audit_log: AuditLog = field(default_factory=AuditLog)
    workflow_trace: WorkflowTrace = field(default_factory=WorkflowTrace)
    revision_history: list[dict[str, Any]] = field(default_factory=list)
    state_id: str = field(default_factory=lambda: f"B-{uuid4().hex[:12]}")

    @classmethod
    def initialize(cls, case: CaseRecord) -> "BlackboardState":
        board = cls(case_record=case, evidence_registry=EvidenceRegistry.from_case(case))
        for span in case.evidence_spans:
            node = EvidenceNode(node_id=f"EV-{span.span_id}", span_id=span.span_id, text=span.text)
            board.argument_graph.add_node(node)
        board.audit_log.append("task_started", actor="coordinator", round_id=0, details={"case_id": case.case_id})
        return board

    @property
    def valid_evidence_ids(self) -> set[str]:
        return self.evidence_registry.valid_ids()

    def next_state_id(self) -> str:
        self.state_id = f"B-{uuid4().hex[:12]}"
        return self.state_id

    def post_message(self, message: BaseMessage) -> None:
        self.message_pool.append(message)
        self.audit_log.append(
            "agent_argument_submitted" if message.message_type == "claim" else f"{message.message_type}_posted",
            actor=message.sender,
            round_id=message.round_id,
            details={"message_id": message.message_id, "claim_id": message.claim_id},
        )
        if message.message_type == "claim":
            claim_text = ""
            if isinstance(message.content, dict):
                claims = message.content.get("key_claims") or []
                claim_text = str(claims[0]) if claims else ""
            else:
                claim_text = str(message.content)
            self.claim_ledger.add_claim(
                claim_id=message.claim_id,
                text=claim_text,
                agent_role=message.sender,
                evidence_ids=message.evidence_ids,
            )
            self.argument_graph.add_node(ClaimNode(node_id=f"CL-{message.claim_id}", text=claim_text, source_agent=message.sender))
            self.argument_graph.add_node(
                ResponsibilityNode(
                    node_id=f"RS-{message.claim_id}",
                    liability_label=str(message.metadata.get("liability_label", "")),
                    allocation=dict(message.metadata.get("allocation", {})),
                )
            )
            for evidence_id in message.evidence_ids:
                self.argument_graph.add_edge(
                    source=f"EV-{evidence_id}",
                    target=f"CL-{message.claim_id}",
                    edge_type="supports",
                    evidence_ids=[evidence_id],
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "state_id": self.state_id,
            "case_profile": self.case_record.to_dict(),
            "evidence_registry": self.evidence_registry.to_dict(),
            "claim_ledger": self.claim_ledger.to_dict(),
            "argument_graph": self.argument_graph.to_dict(),
            "message_pool": [message.to_dict() for message in self.message_pool],
            "verification_records": self.verification_records,
            "conflict_graph": self.conflict_graph.to_dict(),
            "consensus_state": self.consensus_state.to_dict(),
            "revision_history": self.revision_history,
            "audit_log": self.audit_log.to_dict(),
            "workflow_trace": self.workflow_trace.to_dict(),
        }
