from __future__ import annotations

from .agents import AgentSpec, RoleAgent, agent_specs_for_mode
from .coordinator import CoordinationAgent, deterministic_coordinate
from .llm import LLMClient
from .models import CaseInput, CaseRecord, DeliberationRound, MADRAResult
from .protocol import (
    check_stop_condition,
    coordinate_blackboard_round,
    initialize_blackboard,
    post_initial_task,
    run_argument_round,
    run_cross_examination_round,
    run_evidence_verification,
    trigger_targeted_redeliberation,
)
from .retrieval import KeywordRetriever


class MADRAPipeline:
    def __init__(
        self,
        *,
        llm: LLMClient,
        retriever: KeywordRetriever | None = None,
        agents: list[AgentSpec] | None = None,
        mode: str = "full",
        agents_mode: str | None = None,
        max_rounds: int = 3,
        top_k: int = 6,
        disagreement_threshold: float = 0.25,
        unsupported_threshold: float = 0.35,
        consensus_threshold: float = 0.75,
        temperature: float = 0.0,
        seed: int | None = None,
        run_index: int = 0,
    ):
        self.llm = llm
        self.retriever = retriever
        self.mode = agents_mode or mode
        self.agent_specs = agents or agent_specs_for_mode(self.mode)
        self.max_rounds = 1 if self.mode == "single_round" else max_rounds
        if self.mode == "single_round":
            self.agent_specs = agent_specs_for_mode("full")
        if self.mode == "all_agent_fixed_rounds":
            self.agent_specs = agent_specs_for_mode("full")
        self.top_k = top_k
        self.disagreement_threshold = disagreement_threshold
        self.unsupported_threshold = unsupported_threshold
        self.consensus_threshold = consensus_threshold
        self.temperature = temperature
        self.seed = seed
        self.run_index = run_index

    def run(self, case: CaseRecord | CaseInput) -> MADRAResult:
        record = case.to_record() if isinstance(case, CaseInput) else case
        retriever = self.retriever or KeywordRetriever.from_case_record(record)
        evidence = retriever.retrieve(record.text_for_prompt(), top_k=self.top_k)
        role_agents = [RoleAgent(spec, self.llm) for spec in self.agent_specs]
        if self.mode in {"no_blackboard", "multi_agent_without_blackboard", "multi_agent_direct_message_only"}:
            return self._run_direct(record, evidence, role_agents)
        coordinator = CoordinationAgent(self.llm, use_llm=False)
        blackboard = initialize_blackboard(record)
        rounds: list[DeliberationRound] = []
        feedback = ""

        for round_index in range(1, self.max_rounds + 1):
            post_initial_task(blackboard, round_index=round_index)
            agent_outputs = run_argument_round(
                blackboard=blackboard,
                agents=role_agents,
                evidence=evidence,
                round_index=round_index,
                coordinator_feedback=feedback,
            )
            run_cross_examination_round(
                blackboard=blackboard,
                agent_outputs=agent_outputs,
                round_index=round_index,
            )
            run_evidence_verification(
                blackboard=blackboard,
                agent_outputs=agent_outputs,
                evidence=evidence,
                round_index=round_index,
            )
            coordination = coordinate_blackboard_round(
                blackboard=blackboard,
                coordinator=coordinator,
                case=record,
                agent_outputs=agent_outputs,
                evidence=evidence,
                round_index=round_index,
                no_coordination=self.mode == "no_coordination",
            )
            rounds.append(
                DeliberationRound(
                    round_index=round_index,
                    agent_outputs=agent_outputs,
                    coordination=coordination,
                )
            )
            if self.mode == "all_agent_fixed_rounds":
                if round_index >= self.max_rounds:
                    check_stop_condition(
                        blackboard=blackboard,
                        disagreement_threshold=self.disagreement_threshold,
                        unsupported_threshold=self.unsupported_threshold,
                        consensus_threshold=self.consensus_threshold,
                        round_index=round_index,
                        max_rounds=self.max_rounds,
                    )
                    break
                feedback = (
                    "Fixed all-agent re-deliberation: all role agents should review all prior "
                    "conflicts and revise their full responsibility assessment."
                )
                continue
            if check_stop_condition(
                blackboard=blackboard,
                disagreement_threshold=self.disagreement_threshold,
                unsupported_threshold=self.unsupported_threshold,
                consensus_threshold=self.consensus_threshold,
                round_index=round_index,
                max_rounds=self.max_rounds,
            ):
                break
            feedback = trigger_targeted_redeliberation(blackboard=blackboard, round_index=round_index)

        return MADRAResult(
            case_id=record.case_id,
            final=rounds[-1].coordination,
            rounds=rounds,
            mode=self.mode,
            run_index=self.run_index,
            seed=self.seed,
            temperature=self.temperature,
            audit_log=blackboard.audit_log.to_dict(),
            blackboard_state=blackboard.to_dict(),
        )

    def _run_direct(
        self,
        record: CaseRecord,
        evidence,
        role_agents: list[RoleAgent],
    ) -> MADRAResult:
        coordinator = CoordinationAgent(self.llm, use_llm=False)
        rounds: list[DeliberationRound] = []
        feedback = ""
        for round_index in range(1, self.max_rounds + 1):
            agent_outputs = [
                agent.reason(
                    case=record,
                    evidence=evidence,
                    round_index=round_index,
                    coordinator_feedback=feedback,
                )
                for agent in role_agents
            ]
            coordination = coordinator.coordinate(
                case=record,
                agent_outputs=agent_outputs,
                evidence=evidence,
                round_index=round_index,
            )
            rounds.append(
                DeliberationRound(
                    round_index=round_index,
                    agent_outputs=agent_outputs,
                    coordination=coordination,
                )
            )
            if (
                coordination.disagreement_score <= self.disagreement_threshold
                and coordination.unsupported_claim_rate <= self.unsupported_threshold
                and coordination.consensus_score >= self.consensus_threshold
            ):
                break
            feedback = "Direct-message re-deliberation on conflicts: " + "; ".join(coordination.conflict_points)
        return MADRAResult(
            case_id=record.case_id,
            final=rounds[-1].coordination,
            rounds=rounds,
            mode=self.mode,
            run_index=self.run_index,
            seed=self.seed,
            temperature=self.temperature,
        )
