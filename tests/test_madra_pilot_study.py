import csv
import json
import tempfile
import unittest
from pathlib import Path

from prepare_pilot_dataset import build_pilot_dataset
from run_experiment import run_experiment
from run_pilot_study import summarize_prediction_quality, write_run_statistics
from madra.agents import agent_specs_for_mode


def write_structured_case(path: Path, case_id: str) -> None:
    data = {
        "case_id": case_id,
        "source_file": f"{case_id}.docx",
        "structured_segments": {
            "facts": "发包人迟延提交设计变更，承包人主张工期顺延。",
            "issues": "延误责任归属。",
            "reasoning": "法院认为设计变更与审批迟延对工期造成影响。",
            "decision": "酌定发包人承担主要责任。",
        },
        "project_context": {"summary": "住宅项目建设工程施工合同纠纷"},
        "delay_events": [
            {"text": "发包人迟延提交设计变更", "span_start": 0, "span_end": 12}
        ],
        "claims_defenses": {"claims": ["承包人主张工期顺延"], "defenses": ["发包人抗辩承包人管理不当"]},
        "evidence_mentions": [
            {"text": "设计变更通知载明提交时间晚于合同约定", "span_start": 20, "span_end": 42}
        ],
        "source_span_pointers": [
            {"role_label": "reasoning", "text": "法院认为设计变更与审批迟延对工期造成影响", "span_start": 50, "span_end": 72}
        ],
        "case_year": 2021,
    }
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


class PilotStudyTests(unittest.TestCase):
    def test_prepare_pilot_dataset_uses_candidate_label_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            structured = root / "structured"
            structured.mkdir()
            write_structured_case(structured / "C1.json", "C1")
            labels = root / "candidate.csv"
            with labels.open("w", encoding="utf-8-sig", newline="") as fh:
                writer = csv.DictWriter(
                    fh,
                    fieldnames=[
                        "case_id",
                        "candidate_responsibility_label",
                        "candidate_outcome_label",
                        "evidence_span",
                        "confidence",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "case_id": "C1",
                        "candidate_responsibility_label": "owner",
                        "candidate_outcome_label": "partial",
                        "evidence_span": "设计变更通知载明提交时间晚于合同约定",
                        "confidence": "0.91",
                    }
                )

            out = root / "dataset.jsonl"
            candidate_out = root / "candidate_labels_500.csv"
            weak_out = root / "weak_labels_500.csv"
            human_out = root / "human_checked_50.jsonl"
            summary = build_pilot_dataset(
                structured_dir=structured,
                candidate_label_paths=[labels],
                dataset_output=out,
                candidate_labels_output=candidate_out,
                weak_labels_output=weak_out,
                human_checked_output=human_out,
                limit=1,
                human_checked_size=1,
                seed=3,
            )
            self.assertEqual(summary["num_cases"], 1)
            row = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(row["liability_label"], "owner_responsibility")
            self.assertIn("E1", {item["span_id"] for item in row["evidence_spans"]})
            self.assertTrue(candidate_out.exists())
            self.assertTrue(weak_out.exists())
            self.assertTrue(human_out.exists())

    def test_new_controlled_single_agent_modes_are_available(self):
        self.assertEqual(len(agent_specs_for_mode("single_agent_same_context")), 1)
        self.assertEqual(agent_specs_for_mode("single_agent_long_prompt")[0].name, "single_agent_long_prompt")

    def test_run_statistics_and_quality_report_are_emitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = root / "dataset.jsonl"
            prediction_path = root / "predictions.jsonl"
            stats_dir = root / "stats"
            case = {
                "case_id": "C1",
                "project_type": "building",
                "dispute_type": "delay responsibility",
                "parties": {"owner": "Owner", "contractor": "Contractor"},
                "facts": ["Owner delayed approval."],
                "claims": ["Contractor requested extension."],
                "evidence_spans": [
                    {"span_id": "E1", "text": "Owner delayed approval.", "source": "case"},
                    {"span_id": "E2", "text": "Contractor recovery planning was also disputed.", "source": "case"},
                ],
                "reasoning_spans": [{"span_id": "R1", "text": "Owner delay was accepted.", "source": "reasoning"}],
                "final_decision": "Owner responsible.",
                "liability_label": "owner_responsibility",
                "allocation_ground_truth": {"owner": 100, "contractor": 0},
            }
            dataset.write_text(json.dumps(case, ensure_ascii=False) + "\n", encoding="utf-8")
            rows = run_experiment(
                dataset_path=dataset,
                output_path=prediction_path,
                mode="full",
                mock=True,
                max_rounds=2,
                num_runs=1,
                limit=None,
                model=None,
                temperature=0.0,
                seed=11,
            )
            quality = summarize_prediction_quality(rows)
            self.assertIn("successful_json_rate", quality)
            write_run_statistics(rows=rows, output_dir=stats_dir, stage_name="500")
            self.assertTrue((stats_dir / "cost_500.json").exists())
            self.assertTrue((stats_dir / "runtime_500.json").exists())
            self.assertTrue((stats_dir / "token_usage_500.json").exists())


if __name__ == "__main__":
    unittest.main()
