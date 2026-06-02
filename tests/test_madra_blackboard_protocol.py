import json
import tempfile
import unittest
from pathlib import Path

from madra.blackboard import BlackboardState
from madra.messages import ClaimMessage
from madra.mock_llm import MockLLM
from madra.pipeline import MADRAPipeline
from madra.protocol import initialize_blackboard
from tests.test_madra_research_prototype import sample_case


class BlackboardProtocolTests(unittest.TestCase):
    def test_blackboard_initializes_case_state_and_evidence_registry(self):
        case = sample_case()
        board = initialize_blackboard(case)
        self.assertEqual(board.case_record.case_id, "C1")
        self.assertIn("E1", board.evidence_registry.valid_ids())
        self.assertIn("EV-E1", board.argument_graph.nodes)
        self.assertTrue(board.audit_log.events)

    def test_structured_claim_message_schema(self):
        message = ClaimMessage(
            round_id=1,
            sender="owner_agent",
            receiver="coordinator_agent",
            claim_id="C-1",
            evidence_ids=["E1"],
            content={"key_claims": ["Owner delayed approval."]},
            confidence=0.8,
            required_action="verify_and_coordinate",
        )
        data = message.to_dict()
        self.assertEqual(data["message_type"], "claim")
        self.assertEqual(data["evidence_ids"], ["E1"])
        self.assertIn("message_id", data)

    def test_pipeline_exports_blackboard_and_workflow_audit(self):
        result = MADRAPipeline(llm=MockLLM(), max_rounds=2).run(sample_case())
        data = result.to_dict()
        self.assertIn("blackboard_state", data)
        self.assertIn("audit_log", data)
        events = [event["event_type"] for event in data["audit_log"]]
        self.assertIn("task_started", events)
        self.assertIn("evidence_verified", events)
        self.assertIn("final_output_generated", events)
        self.assertTrue(data["blackboard_state"]["workflow_trace"]["steps"])

    def test_all_agent_fixed_rounds_runs_to_configured_round_count(self):
        result = MADRAPipeline(llm=MockLLM(), mode="all_agent_fixed_rounds", max_rounds=2).run(sample_case())
        data = result.to_dict()
        self.assertEqual(data["mode"], "all_agent_fixed_rounds")
        self.assertEqual(data["rounds_completed"], 2)
        self.assertIn("blackboard_state", data)

    def test_audit_log_exports_jsonl(self):
        board = BlackboardState.initialize(sample_case())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audit_log.jsonl"
            board.audit_log.export_jsonl(path)
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(rows[0]["event_type"], "task_started")


if __name__ == "__main__":
    unittest.main()
