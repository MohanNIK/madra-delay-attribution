import json
import tempfile
import unittest
from pathlib import Path

from madra.tem_harness import build_dataset_profile, run_tem_harness


class TEMHarnessTests(unittest.TestCase):
    def test_dataset_profile_counts_cases_and_evidence(self):
        rows = [
            {
                "case_id": "C1",
                "project_type": "building",
                "liability_label": "owner_responsibility",
                "evidence_spans": [{"span_id": "E1", "text": "x"}],
                "reasoning_spans": [],
                "facts": ["f"],
                "claims": ["c"],
            },
            {
                "case_id": "C2",
                "project_type": "road",
                "liability_label": "shared_responsibility",
                "evidence_spans": [{"span_id": "E1", "text": "x"}, {"span_id": "E2", "text": "y"}],
                "reasoning_spans": [{"span_id": "R1", "text": "r"}],
                "facts": ["f1", "f2"],
                "claims": [],
            },
        ]
        profile = build_dataset_profile(rows, human_checked_rows=[{"case_id": "C1"}])
        self.assertEqual(profile["num_cases"], 2)
        self.assertEqual(profile["human_checked_cases"], 1)
        self.assertEqual(profile["liability_label_counts"]["owner_responsibility"], 1)
        self.assertEqual(profile["evidence_count_mean"], 1.5)

    def test_harness_creates_manuscript_figures_and_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = root / "dataset.jsonl"
            dataset.write_text(
                "\n".join(
                    json.dumps(
                        {
                            "case_id": f"C{i}",
                            "project_type": "building",
                            "dispute_type": "delay responsibility",
                            "parties": {"owner": "Owner", "contractor": "Contractor"},
                            "facts": ["Owner delayed approval."],
                            "claims": ["Contractor claimed extension."],
                            "evidence_spans": [{"span_id": "E1", "text": "Owner delayed approval.", "source": "case"}],
                            "reasoning_spans": [],
                            "final_decision": "Owner responsible.",
                            "liability_label": "owner_responsibility",
                            "allocation_ground_truth": {"owner": 100, "contractor": 0},
                        },
                        ensure_ascii=False,
                    )
                    for i in range(3)
                )
                + "\n",
                encoding="utf-8",
            )
            output = root / "out"
            package = run_tem_harness(
                dataset_path=dataset,
                output_dir=output,
                human_checked_path=None,
                metrics_path=None,
                calibration_report_path=None,
                calibration_metrics_path=None,
                token_usage_path=None,
                runtime_path=None,
                write_docx=False,
            )
            manuscript = package["manuscript_path"].read_text(encoding="utf-8")
            audit = json.loads(package["audit_path"].read_text(encoding="utf-8"))
            self.assertIn("Managerial Relevance Statement", manuscript)
            self.assertIn("[FORMAL_500_RESULTS_TO_BE_UPDATED]", manuscript)
            self.assertGreaterEqual(audit["reference_count"], 60)
            self.assertTrue((output / "figures" / "fig1_madra_architecture.svg").exists())
            self.assertTrue((output / "figure_prompts.md").exists())

    def test_harness_docx_embeds_real_tables_and_figures(self):
        try:
            from docx import Document
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"python-docx unavailable: {exc}")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dataset = root / "dataset.jsonl"
            dataset.write_text(
                "\n".join(
                    json.dumps(
                        {
                            "case_id": f"C{i}",
                            "project_type": "building",
                            "dispute_type": "delay responsibility",
                            "parties": {"owner": "Owner", "contractor": "Contractor"},
                            "facts": ["Owner delayed approval."],
                            "claims": ["Contractor claimed extension."],
                            "evidence_spans": [{"span_id": "E1", "text": "Owner delayed approval.", "source": "case"}],
                            "reasoning_spans": [],
                            "final_decision": "Owner responsible.",
                            "liability_label": "owner_responsibility",
                            "allocation_ground_truth": {"owner": 100, "contractor": 0},
                        },
                        ensure_ascii=False,
                    )
                    for i in range(3)
                )
                + "\n",
                encoding="utf-8",
            )
            output = root / "out"
            package = run_tem_harness(
                dataset_path=dataset,
                output_dir=output,
                human_checked_path=None,
                metrics_path=None,
                calibration_report_path=None,
                calibration_metrics_path=None,
                token_usage_path=None,
                runtime_path=None,
                write_docx=True,
            )
            doc = Document(str(package["docx_path"]))
            self.assertGreaterEqual(len(doc.inline_shapes), 6)
            self.assertGreaterEqual(len(doc.tables), 5)
            self.assertEqual(round(doc.sections[0].top_margin.inches, 3), 0.787)
            self.assertEqual(doc.styles["Normal"].font.name, "Times New Roman")


if __name__ == "__main__":
    unittest.main()
