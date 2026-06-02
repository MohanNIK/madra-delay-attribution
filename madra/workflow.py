from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def workflow_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class WorkflowStep:
    step_id: str
    timestamp: str
    actor: str
    input_state_id: str
    output_state_id: str
    trigger_condition: str
    output_summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "timestamp": self.timestamp,
            "actor": self.actor,
            "input_state_id": self.input_state_id,
            "output_state_id": self.output_state_id,
            "trigger_condition": self.trigger_condition,
            "output_summary": self.output_summary,
        }


@dataclass
class WorkflowTrace:
    steps: list[WorkflowStep] = field(default_factory=list)

    def record(
        self,
        *,
        actor: str,
        input_state_id: str,
        output_state_id: str,
        trigger_condition: str,
        output_summary: str,
    ) -> WorkflowStep:
        step = WorkflowStep(
            step_id=f"W-{uuid4().hex[:12]}",
            timestamp=workflow_timestamp(),
            actor=actor,
            input_state_id=input_state_id,
            output_state_id=output_state_id,
            trigger_condition=trigger_condition,
            output_summary=output_summary,
        )
        self.steps.append(step)
        return step

    def to_dict(self) -> dict[str, Any]:
        return {"steps": [step.to_dict() for step in self.steps]}
