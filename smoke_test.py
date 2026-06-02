import json
from pathlib import Path

from madra.mock_llm import MockLLM
from madra.models import CaseRecord
from madra.pipeline import MADRAPipeline


def build_case() -> CaseRecord:
    return CaseRecord.from_dict(
        {
            "case_id": "madra-toy-001",
            "project_type": "building",
            "dispute_type": "delay responsibility",
            "parties": {"owner": "Employer", "contractor": "Main contractor"},
            "facts": ["The owner issued a late design change."],
            "claims": ["The contractor requested an extension of time."],
            "evidence_spans": [
                {"span_id": "E1", "text": "The owner issued a late design change.", "source": "candidate_label"}
            ],
            "reasoning_spans": [],
            "final_decision": "Shared responsibility",
            "liability_label": "shared_responsibility",
            "allocation_ground_truth": {"owner": 60, "contractor": 40}
        }
    )


def main() -> None:
    result = MADRAPipeline(llm=MockLLM(), max_rounds=2).run(build_case())
    assert result.final.liability_label
    Path("examples/mock_result_from_smoke.json").write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("madra-delay-attribution smoke test passed")


if __name__ == "__main__":
    main()
