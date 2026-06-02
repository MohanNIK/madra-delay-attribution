from __future__ import annotations

import argparse
from pathlib import Path

from run_experiment import run_experiment


ABLATION_MODES = [
    "full",
    "no_evidence_verification",
    "no_coordination",
    "single_round",
    "single_agent",
    "single_agent_same_context",
    "single_agent_long_prompt",
    "rag_only",
    "no_blackboard",
    "multi_agent_direct_message_only",
    "all_agent_fixed_rounds",
]


def run_ablation_modes(
    *,
    dataset_path,
    output_dir,
    modes=None,
    mock=False,
    model=None,
    temperature=0.0,
    seed=None,
    num_runs=1,
    max_rounds=3,
    limit=None,
) -> None:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for mode in modes or ABLATION_MODES:
        run_experiment(
            dataset_path=dataset_path,
            output_path=output_dir / f"predictions_{mode}.jsonl",
            mode=mode,
            mock=mock,
            max_rounds=max_rounds,
            num_runs=num_runs,
            limit=limit,
            model=model,
            temperature=temperature,
            seed=seed,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run MAD-RA ablation modes.")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--model", default=None)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--num-runs", type=int, default=1)
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    run_ablation_modes(
        dataset_path=args.dataset,
        output_dir=args.output_dir,
        modes=ABLATION_MODES,
        mock=args.mock,
        model=args.model,
        temperature=args.temperature,
        seed=args.seed,
        num_runs=args.num_runs,
        max_rounds=args.max_rounds,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
