from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


MESSAGE_TYPES = {
    "claim",
    "evidence",
    "challenge",
    "rebuttal",
    "concession",
    "verification",
    "coordinator_feedback",
}


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class BaseMessage:
    round_id: int
    sender: str
    receiver: str
    claim_id: str
    evidence_ids: list[str]
    message_type: str
    content: str | dict[str, Any]
    confidence: float = 0.0
    required_action: str = "none"
    message_id: str = field(default_factory=lambda: f"M-{uuid4().hex[:12]}")
    timestamp: str = field(default_factory=utc_timestamp)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.message_type not in MESSAGE_TYPES:
            raise ValueError(f"Unsupported MAD-RA message_type: {self.message_type}")
        self.evidence_ids = [str(item) for item in self.evidence_ids]
        self.confidence = max(0.0, min(float(self.confidence), 1.0))

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "round_id": self.round_id,
            "timestamp": self.timestamp,
            "sender": self.sender,
            "receiver": self.receiver,
            "claim_id": self.claim_id,
            "evidence_ids": self.evidence_ids,
            "message_type": self.message_type,
            "content": self.content,
            "confidence": self.confidence,
            "required_action": self.required_action,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BaseMessage":
        return cls(
            message_id=str(data.get("message_id") or f"M-{uuid4().hex[:12]}"),
            round_id=int(data.get("round_id", 0)),
            timestamp=str(data.get("timestamp") or utc_timestamp()),
            sender=str(data.get("sender") or ""),
            receiver=str(data.get("receiver") or ""),
            claim_id=str(data.get("claim_id") or ""),
            evidence_ids=[str(item) for item in data.get("evidence_ids", [])],
            message_type=str(data.get("message_type") or ""),
            content=data.get("content") or "",
            confidence=float(data.get("confidence", 0.0)),
            required_action=str(data.get("required_action") or "none"),
            metadata=dict(data.get("metadata") or {}),
        )


class ClaimMessage(BaseMessage):
    def __init__(self, **kwargs: Any):
        super().__init__(message_type="claim", **kwargs)


class EvidenceMessage(BaseMessage):
    def __init__(self, **kwargs: Any):
        super().__init__(message_type="evidence", **kwargs)


class ChallengeMessage(BaseMessage):
    def __init__(self, **kwargs: Any):
        super().__init__(message_type="challenge", **kwargs)


class RebuttalMessage(BaseMessage):
    def __init__(self, **kwargs: Any):
        super().__init__(message_type="rebuttal", **kwargs)


class ConcessionMessage(BaseMessage):
    def __init__(self, **kwargs: Any):
        super().__init__(message_type="concession", **kwargs)


class VerificationMessage(BaseMessage):
    def __init__(self, **kwargs: Any):
        super().__init__(message_type="verification", **kwargs)


class CoordinatorFeedback(BaseMessage):
    def __init__(self, **kwargs: Any):
        super().__init__(message_type="coordinator_feedback", **kwargs)
