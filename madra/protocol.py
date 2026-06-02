from __future__ import annotations

from pathlib import Path
from typing import Any

from .agents import RoleAgent
from .blackboard import BlackboardState
from .coordinator import CoordinationAgent, deterministic_coordinate
from .messages import ChallengeMessage, CoordinatorFeedback, VerificationMessage
from .metrics import composite_disagreement, unsupported_claim_rate
from .models import AgentOutput, CaseRecord, CoordinationOutput, EvidenceSpan


def initialize_blackboard(case_record: CaseRecord) -> BlackboardState:
    return BlackboardState.initialize(case_record)


def post_initial_task(blackboard: BlackboardState, *, round_index: int) -> None:
    input_state = blackboard.state_id
    blackboard.audit_log.append(
        "task_started",
        actor="coordinator_agent",
        round_id=round_index,
        details={"case_id": blackboard.case_record.case_id, "state_id": input_state},
    )
    output_state = blackboard.next_state_id()
    blackboard.workflow_trace.record(
        actor="coordinator_agent",
        input_state_id=input_state,
        output_state_id=output_state,
        trigger_condition="new_deliberation_round",
        output_summary="Coordinator posted role-specific responsibility attribution task to the shared blackboard.",
    )


def run_argument_round(
    *,
    blackboard: BlackboardState,
    agents: list[RoleAgent],
    evidence: list[EvidenceSpan],
    round_index: int,
    coordinator_feedback: str = "",
) -> list[AgentOutput]:
    input_state = blackboard.state_id
    outputs: list[AgentOutput] = []
    for agent in agents:
        _, output = agent.write_message(
            blackboard=blackboard,
            evidence=evidence,
            round_index=round_index,
            coordinator_feedback=coordinator_feedback,
        )
        outputs.append(output)
    output_state = blackboard.next_state_id()
    blackboard.workflow_trace.record(
        actor="role_agents",
        input_state_id=input_state,
        output_state_id=output_state,
        trigger_condition="coordinator_task_posted",
        output_summary=f"{len(outputs)} structured ClaimMessages submitted to the blackboard.",
    )
    return outputs


def run_cross_examination_round(
    *,
    blackboard: BlackboardState,
    agent_outputs: list[AgentOutput],
    round_index: int,
) -> None:
    labels = {output.liability_label for output in agent_outputs}
    if len(labels) <= 1:
        return
    message = ChallengeMessage(
        round_id=round_index,
        sender="coordinator_agent",
        receiver="role_agents",
        claim_id=f"label-conflict-R{round_index}",
        evidence_ids=sorted({eid for output in agent_outputs for eid in output.evidence_ids}),
        content={"conflict_type": "label_conflict", "labels": sorted(labels)},
        confidence=1.0,
        required_action="respond_to_label_conflict",
    )
    blackboard.post_message(message)


def run_evidence_verification(
    *,
    blackboard: BlackboardState,
    agent_outputs: list[AgentOutput],
    evidence: list[EvidenceSpan],
    round_index: int,
) -> list[dict[str, Any]]:
    valid = {span.span_id for span in evidence}
    records: list[dict[str, Any]] = []
    for output in agent_outputs:
        for claim in output.key_claims:
            status = "support" if set(output.evidence_ids) & valid and claim not in output.unsupported_claims else "missing"
            if claim in output.unsupported_claims:
                status = "missing"
            record = {
                "round_id": round_index,
                "agent_role": output.agent_role,
                "claim": claim,
                "evidence_ids": [eid for eid in output.evidence_ids if eid in valid],
                "verification_status": status,
            }
            records.append(record)
    blackboard.verification_records.extend(records)
    blackboard.audit_log.append(
        "evidence_verified",
        actor="evidence_verification_agent",
        round_id=round_index,
        details={"records": len(records)},
    )
    verification_message = VerificationMessage(
        round_id=round_index,
        sender="evidence_verification_agent",
        receiver="coordinator_agent",
        claim_id=f"verification-R{round_index}",
        evidence_ids=sorted({eid for output in agent_outputs for eid in output.evidence_ids if eid in valid}),
        content={"verification_records": records},
        confidence=1.0,
        required_action="update_conflict_graph",
    )
    blackboard.post_message(verification_message)
    input_state = blackboard.state_id
    output_state = blackboard.next_state_id()
    blackboard.workflow_trace.record(
        actor="evidence_verification_agent",
        input_state_id=input_state,
        output_state_id=output_state,
        trigger_condition="agent_argument_submitted",
        output_summary=f"Verified {len(records)} claim-evidence links.",
    )
    return records


def update_conflict_graph(
    *,
    blackboard: BlackboardState,
    agent_outputs: list[AgentOutput],
    coordination: CoordinationOutput | None = None,
) -> None:
    labels = {output.liability_label for output in agent_outputs}
    if len(labels) > 1:
        blackboard.conflict_graph.add_conflict(
            conflict_type="label_conflict",
            description="Role agents disagree on responsibility label.",
            agent_roles=[output.agent_role for output in agent_outputs],
            evidence_ids=sorted({eid for output in agent_outputs for eid in output.evidence_ids}),
        )
    allocations = {tuple(sorted(output.allocation.items())) for output in agent_outputs}
    if len(allocations) > 1:
        blackboard.conflict_graph.add_conflict(
            conflict_type="allocation_conflict",
            description="Role agents provide different allocation vectors.",
            agent_roles=[output.agent_role for output in agent_outputs],
            evidence_ids=[],
        )
    evidence_sets = {tuple(sorted(output.evidence_ids)) for output in agent_outputs}
    if len(evidence_sets) > 1:
        blackboard.conflict_graph.add_conflict(
            conflict_type="evidence_conflict",
            description="Role agents cite different evidence chains.",
            agent_roles=[output.agent_role for output in agent_outputs],
            evidence_ids=sorted({eid for output in agent_outputs for eid in output.evidence_ids}),
        )
    unsupported = [claim for output in agent_outputs for claim in output.unsupported_claims]
    if unsupported:
        blackboard.conflict_graph.add_conflict(
            conflict_type="causality_or_evidence_conflict",
            description="Unsupported or weakly supported responsibility claims remain.",
            agent_roles=[output.agent_role for output in agent_outputs if output.unsupported_claims],
            evidence_ids=[],
        )
    if coordination:
        blackboard.consensus_state.disagreement_score = coordination.disagreement_score
        blackboard.consensus_state.consensus_score = coordination.consensus_score
        blackboard.consensus_state.unsupported_claim_rate = coordination.unsupported_claim_rate
        blackboard.consensus_state.round_index = len({m.round_id for m in blackboard.message_pool})
    blackboard.audit_log.append(
        "conflict_detected",
        actor="coordinator_agent",
        round_id=blackboard.consensus_state.round_index,
        details={"open_conflicts": len(blackboard.conflict_graph.open_conflicts())},
    )


def trigger_targeted_redeliberation(
    *,
    blackboard: BlackboardState,
    round_index: int,
) -> str:
    conflicts = blackboard.conflict_graph.open_conflicts()
    if not conflicts:
        return ""
    summaries = [
        f"{item['conflict_type']}: {item['description']} evidence={','.join(item.get('evidence_ids', [])) or 'none'}"
        for item in conflicts[-4:]
    ]
    feedback = "Targeted re-deliberation required on conflict points: " + "; ".join(summaries)
    message = CoordinatorFeedback(
        round_id=round_index,
        sender="coordinator_agent",
        receiver="relevant_role_agents",
        claim_id=f"targeted-feedback-R{round_index}",
        evidence_ids=sorted({eid for item in conflicts for eid in item.get("evidence_ids", [])}),
        content={"targeted_feedback": feedback, "conflicts": conflicts[-4:]},
        confidence=1.0,
        required_action="revise_only_conflicted_claims",
    )
    blackboard.post_message(message)
    blackboard.revision_history.append(message.to_dict())
    blackboard.audit_log.append(
        "feedback_posted",
        actor="coordinator_agent",
        round_id=round_index,
        details={"message_id": message.message_id},
    )
    return feedback


def check_stop_condition(
    *,
    blackboard: BlackboardState,
    disagreement_threshold: float,
    unsupported_threshold: float,
    consensus_threshold: float,
    round_index: int,
    max_rounds: int,
) -> bool:
    state = blackboard.consensus_state
    satisfied = (
        state.disagreement_score <= disagreement_threshold
        and state.unsupported_claim_rate <= unsupported_threshold
        and state.consensus_score >= consensus_threshold
    ) or round_index >= max_rounds
    state.stop_condition_satisfied = satisfied
    blackboard.audit_log.append(
        "re_deliberation_completed" if not satisfied else "final_output_generated",
        actor="coordinator_agent",
        round_id=round_index,
        details=state.to_dict(),
    )
    return satisfied


def coordinate_blackboard_round(
    *,
    blackboard: BlackboardState,
    coordinator: CoordinationAgent,
    case: CaseRecord,
    agent_outputs: list[AgentOutput],
    evidence: list[EvidenceSpan],
    round_index: int,
    no_coordination: bool = False,
) -> CoordinationOutput:
    if no_coordination:
        coordination = deterministic_coordinate(case, agent_outputs[:1], evidence)
    else:
        coordination = coordinator.coordinate(
            case=case,
            agent_outputs=agent_outputs,
            evidence=evidence,
            round_index=round_index,
        )
    blackboard.consensus_state.disagreement_score = coordination.disagreement_score
    blackboard.consensus_state.consensus_score = coordination.consensus_score
    blackboard.consensus_state.unsupported_claim_rate = coordination.unsupported_claim_rate
    blackboard.consensus_state.round_index = round_index
    update_conflict_graph(blackboard=blackboard, agent_outputs=agent_outputs, coordination=coordination)
    return coordination


def export_audit_log(blackboard: BlackboardState, path: str | Path) -> None:
    blackboard.audit_log.export_jsonl(path)
