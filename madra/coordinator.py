from __future__ import annotations

from collections import Counter, defaultdict
import json
from statistics import mean

from .agents import complete_with_schema_retries
from .llm import LLMClient
from .metrics import composite_disagreement, unsupported_claim_rate
from .models import (
    AgentOutput,
    CaseInput,
    CaseRecord,
    CoordinationOutput,
    EvidenceSpan,
    ManagementImplications,
)
from .prompts import COORDINATION_JSON_CONTRACT, COORDINATOR_PROMPT


class CoordinationAgent:
    def __init__(self, llm: LLMClient, *, use_llm: bool = False):
        self.llm = llm
        self.use_llm = use_llm

    def coordinate(
        self,
        *,
        case: CaseRecord | CaseInput,
        agent_outputs: list[AgentOutput],
        evidence: list[EvidenceSpan],
        round_index: int,
    ) -> CoordinationOutput:
        record = case.to_record() if isinstance(case, CaseInput) else case
        deterministic = deterministic_coordinate(record, agent_outputs, evidence)
        if not self.use_llm:
            return deterministic
        raw = complete_with_schema_retries(
            llm=self.llm,
            system_prompt=f"{COORDINATOR_PROMPT}\n\n{COORDINATION_JSON_CONTRACT}",
            user_prompt=build_coordination_prompt(
                case=record,
                agent_outputs=agent_outputs,
                evidence=evidence,
                round_index=round_index,
                computed_metrics=deterministic,
            ),
            schema_name="coordination",
            parser=lambda data: CoordinationOutput.from_dict(
                data,
                valid_evidence_ids={item.span_id for item in evidence},
            ),
        )
        return guard_final_output(raw, agent_outputs, evidence)


def deterministic_coordinate(
    case: CaseRecord,
    agent_outputs: list[AgentOutput],
    evidence: list[EvidenceSpan],
) -> CoordinationOutput:
    metrics = compute_deliberation_metrics(agent_outputs)
    label = majority_label(agent_outputs)
    allocation = mean_allocation(agent_outputs)
    evidence_ids = stable_evidence_ids(agent_outputs, evidence)
    key_claims = guarded_key_claims(agent_outputs, evidence_ids)
    management = build_management_implications(case, key_claims, evidence_ids)
    return CoordinationOutput(
        liability_label=label,
        allocation=allocation,
        key_claims=key_claims,
        evidence_ids=evidence_ids,
        consensus_score=metrics["consensus_score"],
        disagreement_score=metrics["disagreement_score"],
        unsupported_claim_rate=metrics["unsupported_claim_rate"],
        conflict_points=conflict_points(agent_outputs),
        rationale=(
            "Decision-support synthesis based on role-agent labels, allocation estimates, "
            "evidence overlap, and unsupported-claim checks."
        ),
        management_implications=management,
    )


def compute_deliberation_metrics(agent_outputs: list[AgentOutput]) -> dict[str, float]:
    disagreement = composite_disagreement(agent_outputs)
    unsupported = unsupported_claim_rate(agent_outputs)
    consensus = max(0.0, min(1.0, 1.0 - disagreement - 0.2 * unsupported))
    return {
        "disagreement_score": disagreement,
        "consensus_score": consensus,
        "unsupported_claim_rate": unsupported,
    }


def majority_label(agent_outputs: list[AgentOutput]) -> str:
    labels = [item.liability_label for item in agent_outputs if item.liability_label]
    if not labels:
        return "insufficient_evidence"
    return Counter(labels).most_common(1)[0][0]


def mean_allocation(agent_outputs: list[AgentOutput]) -> dict[str, float]:
    values: dict[str, list[float]] = defaultdict(list)
    for output in agent_outputs:
        for party, value in output.allocation.items():
            values[party].append(float(value))
    return {party: round(mean(items), 2) for party, items in values.items()}


def stable_evidence_ids(agent_outputs: list[AgentOutput], evidence: list[EvidenceSpan]) -> list[str]:
    valid = {item.span_id for item in evidence}
    counts = Counter(eid for output in agent_outputs for eid in output.evidence_ids if eid in valid)
    if not counts:
        return []
    threshold = 2 if len(agent_outputs) > 1 else 1
    selected = [eid for eid, count in counts.items() if count >= threshold]
    return selected or [eid for eid, _ in counts.most_common(3)]


def guarded_key_claims(agent_outputs: list[AgentOutput], evidence_ids: list[str]) -> list[str]:
    if not evidence_ids:
        return []
    claims: list[str] = []
    for output in agent_outputs:
        if not set(output.evidence_ids) & set(evidence_ids):
            continue
        for claim in output.key_claims:
            if claim not in output.unsupported_claims and claim not in claims:
                claims.append(claim)
    return claims[:8]


def conflict_points(agent_outputs: list[AgentOutput]) -> list[str]:
    points: list[str] = []
    labels = {item.liability_label for item in agent_outputs}
    if len(labels) > 1:
        points.append("Role agents disagree on liability_label: " + ", ".join(sorted(labels)))
    evidence_sets = [set(item.evidence_ids) for item in agent_outputs if item.evidence_ids]
    if evidence_sets and len(set(tuple(sorted(item)) for item in evidence_sets)) > 1:
        points.append("Role agents cite different evidence_ids.")
    unsupported = [claim for output in agent_outputs for claim in output.unsupported_claims]
    if unsupported:
        points.append("Unsupported claims require removal or additional evidence.")
    return points


def build_management_implications(
    case: CaseRecord,
    key_claims: list[str],
    evidence_ids: list[str],
) -> ManagementImplications:
    return ManagementImplications(
        key_risk_points=[
            "Delay responsibility remains sensitive to notice, causality, and evidence sufficiency.",
            *key_claims[:2],
        ],
        evidence_preparation_suggestions=[
            f"Preserve and index evidence spans: {', '.join(evidence_ids) or 'no stable evidence identified'}.",
            "Link each delay event to contemporaneous notices, instructions, schedules, and progress records.",
        ],
        claim_negotiation_focus=[
            "Focus negotiation on supported causality and responsibility allocation, not unsupported narrative claims.",
            f"Use the final decision-support label as a scenario: {case.liability_label or 'unknown ground truth'}."
        ],
        preventive_actions=[
            "Maintain a live delay-event register with evidence IDs and responsible-party hypotheses.",
            "Review approval, variation, recovery-plan, and notice workflows before disputes escalate.",
        ],
    )


def guard_final_output(
    output: CoordinationOutput,
    agent_outputs: list[AgentOutput],
    evidence: list[EvidenceSpan],
) -> CoordinationOutput:
    valid = {item.span_id for item in evidence}
    output.evidence_ids = [item for item in output.evidence_ids if item in valid]
    output.key_claims = guarded_key_claims(agent_outputs, output.evidence_ids) or output.key_claims
    if output.key_claims and not output.evidence_ids:
        output.key_claims = []
        output.unsupported_claim_rate = 1.0
        output.liability_label = "insufficient_evidence"
    return output


def build_coordination_prompt(
    *,
    case: CaseRecord,
    agent_outputs: list[AgentOutput],
    evidence: list[EvidenceSpan],
    round_index: int,
    computed_metrics: CoordinationOutput,
) -> str:
    evidence_text = "\n".join(
        f"[{span.span_id}] ({span.source}) {span.text}" for span in evidence
    )
    return (
        f"Case ID: {case.case_id}\n"
        f"Round: {round_index}\n\n"
        f"Evidence spans:\n{evidence_text or 'No evidence provided.'}\n\n"
        "Role-agent outputs:\n"
        f"{json.dumps([item.to_dict() for item in agent_outputs], ensure_ascii=False, indent=2)}\n\n"
        "Deterministic disagreement metrics:\n"
        f"{json.dumps(computed_metrics.to_dict(), ensure_ascii=False, indent=2)}\n\n"
        "Produce a conservative decision-support final output using only valid evidence_ids."
    )


def compute_unsupported_claim_rate(agent_outputs: list[AgentOutput]) -> float:
    return unsupported_claim_rate(agent_outputs)
