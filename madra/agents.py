from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .blackboard import BlackboardState
from .llm import LLMClient
from .messages import BaseMessage, ClaimMessage
from .models import AgentOutput, CaseInput, CaseRecord, EvidenceSpan, SchemaValidationError
from .prompts import AGENT_JSON_CONTRACT, ROLE_PROMPTS


@dataclass(frozen=True)
class AgentSpec:
    name: str
    role_prompt: str


DEFAULT_AGENTS = [
    AgentSpec(name=name, role_prompt=prompt)
    for name, prompt in ROLE_PROMPTS.items()
    if name not in {"single_agent", "single_agent_same_context", "single_agent_long_prompt", "rag_only"}
]


def agent_specs_for_mode(mode: str) -> list[AgentSpec]:
    if mode in {"single_agent", "single_agent_same_context", "single_agent_long_prompt"}:
        return [AgentSpec(name=mode, role_prompt=ROLE_PROMPTS[mode])]
    if mode == "rag_only":
        return [AgentSpec(name="rag_only", role_prompt=ROLE_PROMPTS["rag_only"])]
    specs = DEFAULT_AGENTS
    if mode == "no_evidence_verification":
        specs = [item for item in specs if item.name != "evidence_verification_agent"]
    return specs


class RoleAgent:
    def __init__(self, spec: AgentSpec, llm: LLMClient, *, max_schema_retries: int = 2):
        self.spec = spec
        self.llm = llm
        self.max_schema_retries = max_schema_retries

    def reason(
        self,
        *,
        case: CaseRecord | CaseInput,
        evidence: list[EvidenceSpan],
        round_index: int,
        coordinator_feedback: str = "",
    ) -> AgentOutput:
        record = case.to_record() if isinstance(case, CaseInput) else case
        system_prompt = f"{self.spec.role_prompt}\n\n{AGENT_JSON_CONTRACT}"
        user_prompt = build_agent_user_prompt(
            case=record,
            evidence=evidence,
            round_index=round_index,
            coordinator_feedback=coordinator_feedback,
        )
        return complete_with_schema_retries(
            llm=self.llm,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema_name=self.spec.name,
            parser=lambda raw: AgentOutput.from_dict(
                {**raw, "agent_role": raw.get("agent_role") or self.spec.name},
                valid_evidence_ids={item.span_id for item in evidence},
                role=self.spec.name,
            ),
            max_retries=self.max_schema_retries,
        )

    def read_blackboard(self, blackboard: BlackboardState) -> str:
        """Return a compact evidence-indexed state view for blackboard-mediated deliberation."""
        case = blackboard.case_record
        open_conflicts = blackboard.conflict_graph.open_conflicts()
        recent_feedback = [
            message.to_dict()
            for message in blackboard.message_pool[-6:]
            if message.message_type in {"coordinator_feedback", "challenge", "verification"}
        ]
        return (
            f"Case profile:\n{case.text_for_prompt()}\n\n"
            f"Valid evidence IDs: {', '.join(sorted(blackboard.valid_evidence_ids))}\n"
            f"Open conflicts: {open_conflicts or 'none'}\n"
            f"Recent structured feedback: {recent_feedback or 'none'}"
        )

    def write_message(
        self,
        *,
        blackboard: BlackboardState,
        evidence: list[EvidenceSpan],
        round_index: int,
        coordinator_feedback: str = "",
    ) -> tuple[BaseMessage, AgentOutput]:
        """Submit a structured ClaimMessage to the shared blackboard."""
        state_view = self.read_blackboard(blackboard)
        output = self.reason(
            case=blackboard.case_record,
            evidence=evidence,
            round_index=round_index,
            coordinator_feedback=(coordinator_feedback + "\n\nBlackboard state view:\n" + state_view).strip(),
        )
        claim_id = f"{self.spec.name}-R{round_index}-{len(blackboard.message_pool) + 1}"
        message = ClaimMessage(
            round_id=round_index,
            sender=self.spec.name,
            receiver="coordinator_agent",
            claim_id=claim_id,
            evidence_ids=output.evidence_ids,
            content=output.to_dict(),
            confidence=1.0 - output.uncertainty,
            required_action="verify_and_coordinate",
            metadata={
                "liability_label": output.liability_label,
                "allocation": output.allocation,
                "unsupported_claims": output.unsupported_claims,
            },
        )
        blackboard.post_message(message)
        return message, output


class OwnerAgent(RoleAgent):
    def __init__(self, llm: LLMClient, *, max_schema_retries: int = 2):
        super().__init__(AgentSpec("owner_agent", ROLE_PROMPTS["owner_agent"]), llm, max_schema_retries=max_schema_retries)


class ContractorAgent(RoleAgent):
    def __init__(self, llm: LLMClient, *, max_schema_retries: int = 2):
        super().__init__(
            AgentSpec("contractor_agent", ROLE_PROMPTS["contractor_agent"]),
            llm,
            max_schema_retries=max_schema_retries,
        )


class DelayAnalysisAgent(RoleAgent):
    def __init__(self, llm: LLMClient, *, max_schema_retries: int = 2):
        super().__init__(
            AgentSpec("delay_analysis_agent", ROLE_PROMPTS["delay_analysis_agent"]),
            llm,
            max_schema_retries=max_schema_retries,
        )


class ContractRuleAgent(RoleAgent):
    def __init__(self, llm: LLMClient, *, max_schema_retries: int = 2):
        super().__init__(
            AgentSpec("contract_rule_agent", ROLE_PROMPTS["contract_rule_agent"]),
            llm,
            max_schema_retries=max_schema_retries,
        )


class EvidenceVerificationAgent(RoleAgent):
    def __init__(self, llm: LLMClient, *, max_schema_retries: int = 2):
        super().__init__(
            AgentSpec("evidence_verification_agent", ROLE_PROMPTS["evidence_verification_agent"]),
            llm,
            max_schema_retries=max_schema_retries,
        )


class CoordinatorAgent:
    name = "coordinator_agent"


def complete_with_schema_retries(
    *,
    llm: LLMClient,
    system_prompt: str,
    user_prompt: str,
    schema_name: str,
    parser: Callable[[dict[str, Any]], Any],
    max_retries: int = 2,
) -> Any:
    last_error: Exception | None = None
    prompt = user_prompt
    for attempt in range(max_retries + 1):
        try:
            raw = llm.complete_json(system_prompt=system_prompt, user_prompt=prompt, schema_name=schema_name)
            parsed = parser(raw)
            stats = getattr(llm, "madra_stats", None)
            if isinstance(stats, dict):
                stats["schema_success_count"] = stats.get("schema_success_count", 0) + 1
            return parsed
        except Exception as exc:
            last_error = exc
            stats = getattr(llm, "madra_stats", None)
            if isinstance(stats, dict):
                stats["schema_failure_count"] = stats.get("schema_failure_count", 0) + 1
            if attempt >= max_retries:
                break
            if isinstance(stats, dict):
                stats["schema_retry_count"] = stats.get("schema_retry_count", 0) + 1
            prompt = (
                user_prompt
                + "\n\nYour previous response did not match the required JSON schema. "
                + f"Error: {exc}. Return only corrected JSON with all required fields."
            )
    if isinstance(last_error, SchemaValidationError):
        raise last_error
    raise SchemaValidationError(role=schema_name, missing_fields=["valid_json_schema"], raw=str(last_error))


def build_agent_user_prompt(
    *,
    case: CaseRecord,
    evidence: list[EvidenceSpan],
    round_index: int,
    coordinator_feedback: str = "",
) -> str:
    evidence_text = "\n".join(
        f"[{span.span_id}] ({span.source}) {span.text}" for span in evidence
    )
    reasoning_text = "\n".join(
        f"- ({span.source}; context only, not a valid evidence_id) {span.text}" for span in case.reasoning_spans
    )
    return (
        f"Case ID: {case.case_id}\n"
        f"Round: {round_index}\n\n"
        f"Structured case record:\n{case.text_for_prompt()}\n\n"
        f"Evidence spans:\n{evidence_text or 'No evidence provided.'}\n\n"
        f"Reasoning spans, if available for context only. Do not cite their R IDs as evidence_ids:\n{reasoning_text or 'None'}\n\n"
        f"Coordinator feedback from previous round:\n{coordinator_feedback or 'None'}\n\n"
        "Analyse only this case. Every key_claim must cite evidence_ids."
    )
