import json
import tempfile
import unittest
from pathlib import Path

from evaluate_results import evaluate_files
from run_experiment import run_experiment
from madra.coordinator import compute_deliberation_metrics
from madra.llm import parse_json_object
from madra.metrics import evidence_overlap, label_consistency
from madra.models import (
    AgentOutput,
    CaseRecord,
    EvidenceSpan,
    SchemaValidationError,
)
from madra.mock_llm import MockLLM
from madra.pipeline import MADRAPipeline


class BadThenGoodLLM:
    def __init__(self):
        self.calls = 0

    def complete_json(self, *, system_prompt, user_prompt, schema_name):
        self.calls += 1
        if self.calls == 1:
            return {"liability_label": "owner_responsibility"}
        return {
            "agent_role": schema_name,
            "liability_label": "owner_responsibility",
            "allocation": {"owner": 100},
            "key_claims": ["Owner approval delay caused the compensable delay."],
            "evidence_ids": ["E1"],
            "reasoning_steps": ["E1 records delayed approval."],
            "uncertainty": 0.1,
            "unsupported_claims": [],
        }


def sample_case() -> CaseRecord:
    return CaseRecord.from_dict(
        {
            "case_id": "C1",
            "project_type": "building",
            "dispute_type": "delay responsibility",
            "parties": {"owner": "Employer", "contractor": "Contractor"},
            "facts": ["The owner issued a design change.", "Approval was delayed."],
            "claims": ["The contractor claimed extension of time."],
            "evidence_spans": [
                {"span_id": "E1", "text": "The owner issued a design change and approval was delayed.", "source": "judgment"},
                {"span_id": "E2", "text": "The contractor did not submit an updated recovery plan.", "source": "judgment"},
            ],
            "reasoning_spans": [
                {"span_id": "R1", "text": "The tribunal found both parties contributed to delay.", "source": "reasoning"}
            ],
            "final_decision": "Shared responsibility.",
            "liability_label": "shared_responsibility",
            "allocation_ground_truth": {"owner": 60, "contractor": 40},
        }
    )


class ResearchPrototypeTests(unittest.TestCase):
    def test_case_record_preserves_stable_evidence_ids(self):
        case = sample_case()
        self.assertEqual(case.case_id, "C1")
        self.assertEqual(case.evidence_spans[0].span_id, "E1")
        self.assertIn("E2", case.valid_evidence_ids())

    def test_agent_output_schema_requires_research_fields(self):
        with self.assertRaises(SchemaValidationError):
            AgentOutput.from_dict({"agent_role": "owner_agent"}, valid_evidence_ids={"E1"})

        output = AgentOutput.from_dict(
            {
                "agent_role": "owner_agent",
                "liability_label": "owner_responsibility",
                "allocation": {"owner": 100},
                "key_claims": ["Owner delayed approval."],
                "evidence_ids": ["E1"],
                "reasoning_steps": ["E1 supports owner responsibility."],
                "uncertainty": 0.2,
                "unsupported_claims": [],
            },
            valid_evidence_ids={"E1"},
        )
        self.assertEqual(output.agent_role, "owner_agent")

    def test_schema_retry_repairs_bad_agent_output(self):
        case = sample_case()
        pipeline = MADRAPipeline(llm=BadThenGoodLLM(), max_rounds=1, agents_mode="single_agent")
        result = pipeline.run(case)
        self.assertEqual(result.rounds_completed, 1)
        self.assertEqual(result.rounds[0].agent_outputs[0].agent_role, "single_agent")

    def test_disagreement_metrics_combine_label_allocation_and_evidence(self):
        outputs = [
            AgentOutput.from_dict(
                {
                    "agent_role": "owner_agent",
                    "liability_label": "owner_responsibility",
                    "allocation": {"owner": 100, "contractor": 0},
                    "key_claims": ["Owner delayed approval."],
                    "evidence_ids": ["E1"],
                    "reasoning_steps": ["E1 supports the claim."],
                    "uncertainty": 0.1,
                    "unsupported_claims": [],
                },
                valid_evidence_ids={"E1", "E2"},
            ),
            AgentOutput.from_dict(
                {
                    "agent_role": "contractor_agent",
                    "liability_label": "contractor_responsibility",
                    "allocation": {"owner": 0, "contractor": 100},
                    "key_claims": ["Contractor failed recovery."],
                    "evidence_ids": ["E2"],
                    "reasoning_steps": ["E2 supports the claim."],
                    "uncertainty": 0.2,
                    "unsupported_claims": [],
                },
                valid_evidence_ids={"E1", "E2"},
            ),
        ]
        metrics = compute_deliberation_metrics(outputs)
        self.assertGreater(metrics["disagreement_score"], 0.5)
        self.assertLess(metrics["consensus_score"], 0.5)

    def test_pipeline_full_mode_outputs_management_implications_and_guarded_evidence(self):
        result = MADRAPipeline(llm=MockLLM(), max_rounds=2).run(sample_case())
        data = result.to_dict()
        self.assertIn("management_implications", data["final"])
        self.assertTrue(data["final"]["evidence_ids"])
        self.assertLessEqual(data["final"]["disagreement_score"], 0.25)

    def test_stability_helpers(self):
        predictions = [
            {"final": {"liability_label": "shared_responsibility", "allocation": {"owner": 60}, "evidence_ids": ["E1", "E2"], "consensus_score": 0.8}},
            {"final": {"liability_label": "shared_responsibility", "allocation": {"owner": 70}, "evidence_ids": ["E1"], "consensus_score": 0.9}},
        ]
        self.assertEqual(label_consistency(predictions), 1.0)
        self.assertEqual(evidence_overlap(predictions), 0.5)

    def test_experiment_and_evaluation_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            dataset = tmp_path / "dataset.jsonl"
            predictions = tmp_path / "predictions.jsonl"
            dataset.write_text(json.dumps(sample_case().to_dict(), ensure_ascii=False) + "\n", encoding="utf-8")

            run_experiment(
                dataset_path=dataset,
                output_path=predictions,
                mode="full",
                mock=True,
                max_rounds=2,
                num_runs=2,
                limit=None,
                model=None,
                temperature=0.0,
                seed=7,
            )
            report = evaluate_files(dataset, predictions, hit_k=2)
            self.assertIn("accuracy", report)
            self.assertIn("macro_f1", report)
            self.assertIn("evidence_recall", report)

    def test_json_parser_handles_fenced_json(self):
        parsed = parse_json_object("```json\n{\"a\": 1}\n```")
        self.assertEqual(parsed["a"], 1)


if __name__ == "__main__":
    unittest.main()
