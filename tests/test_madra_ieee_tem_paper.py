import json
import tempfile
import unittest
from pathlib import Path

from madra.paper_writing import (
    PaperSectionDraft,
    build_ieee_tem_manuscript,
    build_reference_library,
    run_paper_writing_pipeline,
)


class IEEETEMPaperWritingTests(unittest.TestCase):
    def test_paper_section_schema_requires_auditable_fields(self):
        with self.assertRaises(ValueError):
            PaperSectionDraft.from_dict({"section_name": "Introduction"})

        draft = PaperSectionDraft.from_dict(
            {
                "section_name": "Introduction",
                "claims_used": ["MAD-RA is an evidence-grounded framework."],
                "citations_used": ["[1]", "[2]"],
                "missing_evidence_flags": [],
                "draft_text": "Construction delay responsibility attribution requires evidence-grounded deliberation [1], [2].",
                "review_notes": ["No invented pilot result."],
            }
        )
        self.assertEqual(draft.section_name, "Introduction")
        self.assertIn("[1]", draft.citations_used)

    def test_reference_library_has_at_least_sixty_entries(self):
        references = build_reference_library()
        self.assertGreaterEqual(len(references), 60)
        self.assertTrue(all("gold standard" not in item.lower() for item in references))

    def test_mock_pipeline_writes_tem_manuscript_and_audit_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            metrics = output_dir / "metrics_500.json"
            quality = output_dir / "stage2_report.json"
            token = output_dir / "token_usage_500.json"
            runtime = output_dir / "runtime_500.json"
            metrics.write_text(
                json.dumps(
                    {
                        "num_predictions": 500,
                        "accuracy": 0.42,
                        "macro_f1": 0.38,
                        "evidence_precision": 0.74,
                        "evidence_recall": 0.45,
                        "hit@5": 0.81,
                        "unsupported_claim_rate": 0.27,
                        "consensus_score_mean": 0.72,
                        "consensus_score_std": 0.08,
                    }
                ),
                encoding="utf-8",
            )
            quality.write_text(
                json.dumps(
                    {
                        "successful_json_rate": 1.0,
                        "schema_compliance_rate": 1.0,
                        "retry_rate": 0.0,
                        "malformed_output_rate": 0.0,
                        "unsupported_claim_rate_mean": 0.31,
                    }
                ),
                encoding="utf-8",
            )
            token.write_text(json.dumps({"average_tokens_per_case": 12000, "average_api_calls_per_case": 4}), encoding="utf-8")
            runtime.write_text(json.dumps({"average_running_time_per_case": 52.0}), encoding="utf-8")

            package = run_paper_writing_pipeline(
                output_dir=output_dir,
                metrics_path=metrics,
                calibration_report_path=quality,
                token_usage_path=token,
                runtime_path=runtime,
                mock=True,
            )

            manuscript = package.manuscript_path.read_text(encoding="utf-8")
            audit = json.loads(package.audit_path.read_text(encoding="utf-8"))
            self.assertIn("Managerial Relevance Statement", manuscript)
            self.assertIn("machine-assisted candidate labels", manuscript)
            self.assertNotIn("gold standard", manuscript.lower())
            self.assertNotIn("gold-standard", manuscript.lower())
            self.assertNotIn("automatic judge", manuscript.lower())
            self.assertGreaterEqual(audit["reference_count"], 60)
            self.assertEqual(audit["uses_ieee_tem_sections"], True)

    def test_builder_uses_placeholders_when_results_are_absent(self):
        manuscript = build_ieee_tem_manuscript(
            sections=[],
            metrics={},
            calibration_report={},
            token_usage={},
            runtime={},
            references=build_reference_library(),
        )
        self.assertIn("[500-case pilot results pending]", manuscript)
        self.assertIn("not a legal advice system", manuscript)


if __name__ == "__main__":
    unittest.main()
