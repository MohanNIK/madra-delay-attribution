from __future__ import annotations

import re
from typing import Any


class MockLLM:
    """Deterministic local LLM substitute for demos, tests, and paper workflows."""

    def __init__(self, *, variant: int = 0):
        self.variant = variant
        self.madra_stats = {
            "api_calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "malformed_output_count": 0,
        }

    def complete_json(self, *, system_prompt: str, user_prompt: str, schema_name: str) -> dict[str, Any]:
        self.madra_stats["api_calls"] += 1
        self.madra_stats["prompt_tokens"] += max(1, len(system_prompt.split()) + len(user_prompt.split()))
        self.madra_stats["completion_tokens"] += 80
        self.madra_stats["total_tokens"] = self.madra_stats["prompt_tokens"] + self.madra_stats["completion_tokens"]
        evidence_ids = re.findall(r"\[(E\d+)\]", user_prompt)
        if schema_name == "coordination":
            return self._coordination(evidence_ids)
        return self._agent(schema_name, evidence_ids)

    def _agent(self, schema_name: str, evidence_ids: list[str]) -> dict[str, Any]:
        first = evidence_ids[0] if evidence_ids else "E1"
        second = evidence_ids[1] if len(evidence_ids) > 1 else first
        if schema_name == "contractor_agent" and self.variant % 2:
            return {
                "agent_role": schema_name,
                "liability_label": "contractor_responsibility",
                "allocation": {"owner": 30, "contractor": 70},
                "key_claims": ["The contractor failed to update the recovery plan."],
                "evidence_ids": [second],
                "reasoning_steps": [f"{second} records a disputed recovery-planning or contractor-side issue."],
                "uncertainty": 0.25,
                "unsupported_claims": [],
            }
        if schema_name == "evidence_verification_agent":
            return {
                "agent_role": schema_name,
                "liability_label": "shared_responsibility",
                "allocation": {"owner": 60, "contractor": 40},
                "key_claims": [f"Responsibility claims should be grounded in {first} and {second}."],
                "evidence_ids": sorted(set([first, second])),
                "reasoning_steps": [f"No final key attribution should be made without valid IDs such as {first} or {second}."],
                "uncertainty": 0.15,
                "unsupported_claims": [],
            }
        return {
            "agent_role": schema_name,
            "liability_label": "shared_responsibility",
            "allocation": {"owner": 60, "contractor": 40},
            "key_claims": ["Owner design change and approval delay contributed to the delay."],
            "evidence_ids": [first],
            "reasoning_steps": [f"{first} records the key delay-related fact."],
            "uncertainty": 0.2,
            "unsupported_claims": [],
        }

    def _coordination(self, evidence_ids: list[str]) -> dict[str, Any]:
        selected = sorted(set(evidence_ids[:2])) or ["E1"]
        return {
            "liability_label": "shared_responsibility",
            "allocation": {"owner": 60, "contractor": 40},
            "key_claims": ["Owner design change and contractor recovery planning both require attention."],
            "evidence_ids": selected,
            "consensus_score": 0.86,
            "disagreement_score": 0.14,
            "unsupported_claim_rate": 0.0,
            "conflict_points": [],
            "rationale": "Mock result: agents converged on shared responsibility with stable evidence IDs.",
            "management_implications": {
                "key_risk_points": ["Design changes and recovery planning are central risk points."],
                "evidence_preparation_suggestions": ["Preserve instructions, approvals, notices, and recovery plans."],
                "claim_negotiation_focus": [f"Discuss allocation around {', '.join(selected)}."],
                "preventive_actions": ["Maintain a delay-event register with evidence IDs."],
            },
        }
