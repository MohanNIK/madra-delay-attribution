from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean, pstdev

from madra.io import read_cases, read_jsonl
from madra.metrics import allocation_variance, consensus_summary, evidence_overlap, label_consistency, macro_f1_from_counts


def prediction_rows(path: str | Path) -> list[dict]:
    rows = read_jsonl(path)
    return [row for row in rows if "final" in row]


def evaluate_files(dataset_path: str | Path, predictions_path: str | Path, *, hit_k: int = 5) -> dict:
    cases = {case.case_id: case for case in read_cases(dataset_path)}
    preds = prediction_rows(predictions_path)
    labels: list[str] = []
    predicted: list[str] = []
    evidence_precisions: list[float] = []
    evidence_recalls: list[float] = []
    hit_scores: list[float] = []
    unsupported_rates: list[float] = []

    for pred in preds:
        case = cases.get(pred["case_id"])
        if not case:
            continue
        final = pred.get("final", {})
        labels.append(case.liability_label)
        predicted.append(str(final.get("liability_label", "unknown")))
        pred_evidence = list(final.get("evidence_ids", []))
        candidate_evidence = {span.span_id for span in case.evidence_spans if span.source == "candidate_label"}
        gold_evidence = candidate_evidence or case.valid_evidence_ids()
        pred_set = set(pred_evidence)
        evidence_precisions.append(len(pred_set & gold_evidence) / len(pred_set) if pred_set else 0.0)
        evidence_recalls.append(len(pred_set & gold_evidence) / len(gold_evidence) if gold_evidence else 0.0)
        hit_scores.append(1.0 if set(pred_evidence[:hit_k]) & gold_evidence else 0.0)
        unsupported_rates.append(float(final.get("unsupported_claim_rate", 0.0)))

    accuracy = sum(1 for y, p in zip(labels, predicted) if y == p) / len(labels) if labels else 0.0
    macro_f1, per_class = macro_f1_from_counts(labels, predicted)
    return {
        "num_predictions": len(preds),
        "accuracy": accuracy,
        "macro_f1": macro_f1,
        "per_class_f1": per_class,
        "evidence_precision": mean(evidence_precisions) if evidence_precisions else 0.0,
        "evidence_recall": mean(evidence_recalls) if evidence_recalls else 0.0,
        f"hit@{hit_k}": mean(hit_scores) if hit_scores else 0.0,
        "unsupported_claim_rate": mean(unsupported_rates) if unsupported_rates else 0.0,
        "unsupported_claim_rate_std": pstdev(unsupported_rates) if len(unsupported_rates) > 1 else 0.0,
        "label_consistency": label_consistency(preds),
        "allocation_variance": allocation_variance(preds),
        "evidence_chain_overlap": evidence_overlap(preds),
        **consensus_summary(preds),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate MAD-RA predictions.")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--hit-k", type=int, default=5)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    report = evaluate_files(args.dataset, args.predictions, hit_k=args.hit_k)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
