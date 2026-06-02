from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

from evaluate_results import evaluate_files
from prepare_pilot_dataset import build_pilot_dataset
from run_ablation import ABLATION_MODES, run_ablation_modes
from run_experiment import run_experiment
from madra.io import read_jsonl


def summarize_prediction_quality(rows: list[dict[str, Any]]) -> dict[str, float]:
    predictions = [row for row in rows if "final" in row]
    errors = [row for row in rows if "error" in row]
    total_rows = len(predictions) + len(errors)
    total = len(predictions)
    usage = [row.get("api_usage", {}) for row in predictions]
    usage += [row.get("api_usage", {}) for row in errors]
    retries = sum(float(item.get("schema_retry_count", 0.0)) for item in usage)
    failures = sum(float(item.get("schema_failure_count", 0.0)) for item in usage)
    malformed = sum(float(item.get("malformed_output_count", 0.0)) for item in usage)
    calls = sum(float(item.get("api_calls", 0.0)) for item in usage)
    unsupported = [float(row.get("final", {}).get("unsupported_claim_rate", 0.0)) for row in predictions]
    return {
        "num_predictions": float(total),
        "num_errors": float(len(errors)),
        "successful_json_rate": total / total_rows if total_rows else 0.0,
        "schema_compliance_rate": total / total_rows if total_rows else 0.0,
        "retry_rate": retries / calls if calls else 0.0,
        "schema_failure_rate": failures / calls if calls else 0.0,
        "malformed_output_rate": malformed / calls if calls else 0.0,
        "unsupported_claim_rate_mean": mean(unsupported) if unsupported else 0.0,
        "unsupported_claim_rate_std": pstdev(unsupported) if len(unsupported) > 1 else 0.0,
    }


def write_run_statistics(*, rows: list[dict[str, Any]], output_dir: str | Path, stage_name: str) -> None:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    predictions = [row for row in rows if "final" in row]
    usage = [row.get("api_usage", {}) for row in predictions]
    runtimes = [float(row.get("runtime_seconds", 0.0)) for row in predictions]
    token_totals = [float(item.get("total_tokens", 0.0)) for item in usage]
    cost_per_1k = float(os.environ.get("MADRA_COST_PER_1K_TOKENS", "0"))
    avg_tokens = mean(token_totals) if token_totals else 0.0
    quality = summarize_prediction_quality(rows)
    write_json(output / f"token_usage_{stage_name}.json", {
        "average_tokens_per_case": avg_tokens,
        "total_tokens": sum(token_totals),
        "average_api_calls_per_case": mean([float(item.get("api_calls", 0.0)) for item in usage]) if usage else 0.0,
        **quality,
    })
    write_json(output / f"runtime_{stage_name}.json", {
        "average_running_time_per_case": mean(runtimes) if runtimes else 0.0,
        "total_running_time_seconds": sum(runtimes),
        **quality,
    })
    write_json(output / f"cost_{stage_name}.json", {
        "average_api_cost_per_case": avg_tokens / 1000.0 * cost_per_1k,
        "estimated_total_api_cost": sum(token_totals) / 1000.0 * cost_per_1k,
        "cost_per_1k_tokens_assumption": cost_per_1k,
        **quality,
    })


def write_json(path: str | Path, data: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def build_stability_subset(dataset_path: str | Path, output_path: str | Path, *, limit: int = 100) -> None:
    rows = read_jsonl(dataset_path)
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = str(row.get("liability_label", "unknown"))
        groups.setdefault(key, []).append(row)
    selected = []
    labels = sorted(groups)
    while len(selected) < limit and any(groups.values()):
        for label in labels:
            if groups[label] and len(selected) < limit:
                selected.append(groups[label].pop(0))
    Path(output_path).write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in selected) + ("\n" if selected else ""),
        encoding="utf-8",
    )


def run_stage_workflow(args: argparse.Namespace) -> None:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    dataset_path = output_dir / "dataset_madra_500.jsonl"
    build_pilot_dataset(
        structured_dir=args.structured_dir,
        candidate_label_paths=args.candidate_label,
        dataset_output=dataset_path,
        candidate_labels_output=output_dir / "candidate_labels_500.csv",
        weak_labels_output=output_dir / "weak_labels_500.csv",
        human_checked_output=output_dir / "human_checked_50.jsonl",
        limit=args.limit,
        human_checked_size=args.human_checked_size,
        seed=args.seed,
    )

    stage1 = run_experiment(
        dataset_path=dataset_path,
        output_path=output_dir / "stage1_mock_10_predictions.jsonl",
        mode="full",
        mock=True,
        max_rounds=args.max_rounds,
        num_runs=1,
        limit=10,
        model=args.model,
        temperature=0.0,
        seed=args.seed,
    )
    write_json(output_dir / "stage1_mock_10_quality.json", summarize_prediction_quality(stage1))

    if args.skip_api:
        return

    stage2 = run_experiment(
        dataset_path=dataset_path,
        output_path=output_dir / "stage2_qwen_30_calibration_predictions.jsonl",
        mode="full",
        mock=False,
        max_rounds=args.calibration_max_rounds,
        num_runs=1,
        limit=30,
        model=args.model,
        temperature=args.temperature,
        seed=args.seed,
    )
    write_json(output_dir / "stage2_qwen_30_calibration_report.json", summarize_prediction_quality(stage2))
    if args.stop_after_calibration:
        return

    stage3 = run_experiment(
        dataset_path=dataset_path,
        output_path=output_dir / "stage3_qwen_500_predictions.jsonl",
        mode="full",
        mock=False,
        max_rounds=args.max_rounds,
        num_runs=1,
        limit=args.limit,
        model=args.model,
        temperature=args.temperature,
        seed=args.seed,
    )
    write_run_statistics(rows=stage3, output_dir=output_dir, stage_name="500")
    write_json(output_dir / "metrics_500.json", evaluate_files(dataset_path, output_dir / "stage3_qwen_500_predictions.jsonl"))
    run_ablation_modes(
        dataset_path=dataset_path,
        output_dir=output_dir / "ablation_500",
        modes=ABLATION_MODES,
        mock=False,
        model=args.model,
        temperature=args.temperature,
        seed=args.seed,
        num_runs=1,
        max_rounds=args.max_rounds,
        limit=args.limit,
    )
    stability_dataset = output_dir / "stability_subset_100.jsonl"
    build_stability_subset(dataset_path, stability_dataset, limit=100)
    stability_rows = run_experiment(
        dataset_path=stability_dataset,
        output_path=output_dir / "stability_100_num_runs_3.jsonl",
        mode="full",
        mock=False,
        max_rounds=args.max_rounds,
        num_runs=3,
        limit=None,
        model=args.model,
        temperature=args.temperature,
        seed=args.seed,
    )
    write_json(output_dir / "stability_100_summary.json", summarize_prediction_quality(stability_rows))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the staged MAD-RA SCI pilot study workflow.")
    parser.add_argument("--structured-dir", default="data/3_structured_cases")
    parser.add_argument("--candidate-label", action="append", default=[
        "data/gold/gold500_v1.csv",
        "data/gold/candidate_gold_strict_v1.csv",
        "data/gold/candidate_gold_extended_v1.csv",
    ])
    parser.add_argument("--output-dir", default="outputs/pilot_500")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--human-checked-size", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--model", default=None)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("--calibration-max-rounds", type=int, default=1)
    parser.add_argument("--skip-api", action="store_true")
    parser.add_argument("--stop-after-calibration", action="store_true")
    args = parser.parse_args()
    run_stage_workflow(args)


if __name__ == "__main__":
    main()
