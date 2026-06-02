from __future__ import annotations

import argparse
import json
from pathlib import Path

from madra.io import read_cases
from madra.llm import OpenAICompatibleClient
from madra.mock_llm import MockLLM
from madra.pipeline import MADRAPipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Run MAD-RA on one CaseRecord from a JSONL file.")
    parser.add_argument("--dataset", required=True, help="JSONL dataset containing CaseRecord rows")
    parser.add_argument("--case-id", default=None, help="Case ID to run; defaults to the first row")
    parser.add_argument("--output", required=True, help="Output JSON file")
    parser.add_argument(
        "--mode",
        default="full",
        choices=["full", "no_evidence_verification", "no_coordination", "single_round", "single_agent", "rag_only"],
    )
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--model", default=None)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--max-rounds", type=int, default=3)
    args = parser.parse_args()

    cases = read_cases(args.dataset)
    if args.case_id:
        selected = [case for case in cases if case.case_id == args.case_id]
        if not selected:
            raise SystemExit(f"Case not found: {args.case_id}")
        case = selected[0]
    else:
        case = cases[0]

    llm = MockLLM(variant=args.seed or 0) if args.mock else OpenAICompatibleClient(
        model=args.model,
        temperature=args.temperature,
    )
    result = MADRAPipeline(
        llm=llm,
        mode=args.mode,
        max_rounds=args.max_rounds,
        temperature=args.temperature,
        seed=args.seed,
    ).run(case)
    Path(args.output).write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
