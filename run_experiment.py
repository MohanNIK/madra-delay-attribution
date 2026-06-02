import argparse
import json
import random
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from madra.io import read_cases
from madra.llm import OpenAICompatibleClient
from madra.metrics import (
    allocation_variance,
    consensus_summary,
    evidence_overlap,
    label_consistency,
    unsupported_claim_summary,
)
from madra.mock_llm import MockLLM
from madra.pipeline import MADRAPipeline


def build_llm(*, mock: bool, model: str | None, temperature: float, seed: int | None, run_index: int):
    if mock:
        return MockLLM(variant=(seed or 0) + run_index)
    return OpenAICompatibleClient(model=model, temperature=temperature)


def run_experiment(
    *,
    dataset_path: str | Path,
    output_path: str | Path,
    mode: str,
    mock: bool,
    max_rounds: int,
    num_runs: int,
    limit: int | None,
    model: str | None,
    temperature: float,
    seed: int | None,
    workers: int = 1,
) -> list[dict]:
    cases = read_cases(dataset_path, limit=limit)
    rows: list[dict] = []
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("", encoding="utf-8")
    allowed_modes = [
        "full",
        "no_evidence_verification",
        "no_coordination",
        "single_round",
        "single_agent",
        "single_agent_same_context",
        "single_agent_long_prompt",
        "rag_only",
        "no_blackboard",
        "multi_agent_without_blackboard",
        "multi_agent_direct_message_only",
        "all_agent_fixed_rounds",
    ]
    if mode not in allowed_modes:
        raise ValueError(f"Unsupported mode {mode}; expected one of {', '.join(allowed_modes)}")
    total_cases = len(cases)

    def process_case(case_index, case) -> list[dict]:
        case_rows: list[dict] = []
        run_predictions: list[dict] = []
        for run_index in range(num_runs):
            print(
                f"[MAD-RA] mode={mode} case={case_index}/{total_cases} "
                f"case_id={case.case_id} run={run_index + 1}/{num_runs}",
                flush=True,
            )
            run_seed = None if seed is None else seed + run_index
            if run_seed is not None:
                random.seed(run_seed)
            llm = build_llm(mock=mock, model=model, temperature=temperature, seed=seed, run_index=run_index)
            pipeline = MADRAPipeline(
                llm=llm,
                mode=mode,
                max_rounds=max_rounds,
                temperature=temperature,
                seed=run_seed,
                run_index=run_index,
            )
            started = time.perf_counter()
            before_stats = dict(getattr(llm, "madra_stats", {}))
            try:
                prediction = pipeline.run(case).to_dict()
                elapsed = time.perf_counter() - started
                after_stats = dict(getattr(llm, "madra_stats", {}))
                prediction["runtime_seconds"] = elapsed
                prediction["api_usage"] = usage_delta(before_stats, after_stats)
                run_predictions.append(prediction)
                case_rows.append(prediction)
            except Exception as exc:
                elapsed = time.perf_counter() - started
                after_stats = dict(getattr(llm, "madra_stats", {}))
                error_row = {
                        "case_id": case.case_id,
                        "mode": mode,
                        "run_index": run_index,
                        "seed": run_seed,
                        "temperature": temperature,
                        "runtime_seconds": elapsed,
                        "api_usage": usage_delta(before_stats, after_stats),
                        "error": {
                            "type": type(exc).__name__,
                            "message": str(exc),
                            "traceback_excerpt": traceback.format_exc(limit=2),
                        },
                    }
                case_rows.append(error_row)
        if num_runs > 1:
            stability = {
                "case_id": case.case_id,
                "mode": mode,
                "stability": {
                    "label_consistency": label_consistency(run_predictions),
                    "allocation_variance": allocation_variance(run_predictions),
                    "evidence_chain_overlap": evidence_overlap(run_predictions),
                    **consensus_summary(run_predictions),
                    **unsupported_claim_summary(run_predictions),
                },
            }
            case_rows.append(stability)
        return case_rows

    indexed_cases = list(enumerate(cases, 1))
    if workers <= 1:
        for case_index, case in indexed_cases:
            for row in process_case(case_index, case):
                rows.append(row)
                append_jsonl(output_path, row)
    else:
        print(f"[MAD-RA] using_workers={workers}", flush=True)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(process_case, case_index, case) for case_index, case in indexed_cases]
            for future in as_completed(futures):
                for row in future.result():
                    rows.append(row)
                    append_jsonl(output_path, row)
    return rows


def usage_delta(before: dict, after: dict) -> dict:
    keys = set(before) | set(after)
    delta = {}
    for key in sorted(keys):
        left = before.get(key, 0)
        right = after.get(key, 0)
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            delta[key] = right - left
    return delta


def append_jsonl(path: str | Path, row: dict) -> None:
    with Path(path).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run MAD-RA experiments over a JSONL dataset.")
    parser.add_argument("--dataset", required=True, help="Path to dataset.jsonl")
    parser.add_argument("--output", required=True, help="Path to predictions.jsonl")
    parser.add_argument(
        "--mode",
        default="full",
        choices=[
            "full",
            "no_evidence_verification",
            "no_coordination",
            "single_round",
            "single_agent",
            "single_agent_same_context",
            "single_agent_long_prompt",
            "rag_only",
            "no_blackboard",
            "multi_agent_without_blackboard",
            "multi_agent_direct_message_only",
            "all_agent_fixed_rounds",
        ],
    )
    parser.add_argument("--mock", action="store_true", help="Use deterministic local mock LLM")
    parser.add_argument("--model", default=None, help="Qwen/DashScope model, defaults to DASHSCOPE_MODEL or qwen-plus")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--num-runs", type=int, default=1)
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=1, help="Concurrent case workers for API experiments")
    args = parser.parse_args()

    run_experiment(
        dataset_path=args.dataset,
        output_path=args.output,
        mode=args.mode,
        mock=args.mock,
        max_rounds=args.max_rounds,
        num_runs=args.num_runs,
        limit=args.limit,
        model=args.model,
        temperature=args.temperature,
        seed=args.seed,
        workers=args.workers,
    )


if __name__ == "__main__":
    main()
