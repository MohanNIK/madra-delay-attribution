from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


EDGE_TYPES = {
    "supports",
    "contradicts",
    "weakly_supports",
    "missing",
    "causes",
    "mitigates",
    "allocates_to",
}


@dataclass(frozen=True)
class ClaimNode:
    node_id: str
    text: str
    source_agent: str

    def to_dict(self) -> dict[str, Any]:
        return {"node_type": "claim", "node_id": self.node_id, "text": self.text, "source_agent": self.source_agent}


@dataclass(frozen=True)
class EvidenceNode:
    node_id: str
    span_id: str
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {"node_type": "evidence", "node_id": self.node_id, "span_id": self.span_id, "text": self.text}


@dataclass(frozen=True)
class ResponsibilityNode:
    node_id: str
    liability_label: str
    allocation: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_type": "responsibility",
            "node_id": self.node_id,
            "liability_label": self.liability_label,
            "allocation": self.allocation,
        }


@dataclass(frozen=True)
class DelayEventNode:
    node_id: str
    event_text: str

    def to_dict(self) -> dict[str, Any]:
        return {"node_type": "delay_event", "node_id": self.node_id, "event_text": self.event_text}


@dataclass(frozen=True)
class PartyNode:
    node_id: str
    party_role: str
    party_name: str

    def to_dict(self) -> dict[str, Any]:
        return {"node_type": "party", "node_id": self.node_id, "party_role": self.party_role, "party_name": self.party_name}


@dataclass(frozen=True)
class ArgumentEdge:
    source: str
    target: str
    edge_type: str
    weight: float = 1.0
    evidence_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.edge_type not in EDGE_TYPES:
            raise ValueError(f"Unsupported argument graph edge type: {self.edge_type}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "edge_type": self.edge_type,
            "weight": self.weight,
            "evidence_ids": self.evidence_ids,
        }


@dataclass
class ArgumentGraph:
    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    edges: list[ArgumentEdge] = field(default_factory=list)

    def add_node(self, node: ClaimNode | EvidenceNode | ResponsibilityNode | DelayEventNode | PartyNode) -> None:
        self.nodes[node.node_id] = node.to_dict()

    def add_edge(
        self,
        *,
        source: str,
        target: str,
        edge_type: str,
        weight: float = 1.0,
        evidence_ids: list[str] | None = None,
    ) -> None:
        self.edges.append(
            ArgumentEdge(
                source=source,
                target=target,
                edge_type=edge_type,
                weight=weight,
                evidence_ids=evidence_ids or [],
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {"nodes": self.nodes, "edges": [edge.to_dict() for edge in self.edges]}
