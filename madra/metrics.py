from __future__ import annotations

import math
from statistics import mean, pstdev
from typing import Any

from .models import AgentOutput


def label_disagreement(outputs: list[AgentOutput]) -> float:
    labels = [item.liability_label for item in outputs]
    if len(labels) <= 1:
        return 0.0
    majority = max(set(labels), key=labels.count)
    return 1.0 - labels.count(majority) / len(labels)


def allocation_disagreement(outputs: list[AgentOutput]) -> float:
    if len(outputs) <= 1:
        return 0.0
    parties = sorted({party for output in outputs for party in output.allocation})
    if not parties:
        return 0.0
    vectors = [[output.allocation.get(party, 0.0) / 100.0 for party in parties] for output in outputs]
    distances: list[float] = []
    for i, left in enumerate(vectors):
        for right in vectors[i + 1 :]:
            distances.append(sum(abs(a - b) for a, b in zip(left, right)) / 2.0)
    return min(mean(distances), 1.0) if distances else 0.0


def evidence_disagreement(outputs: list[AgentOutput]) -> float:
    if len(outputs) <= 1:
        return 0.0
    sets = [set(output.evidence_ids) for output in outputs]
    distances: list[float] = []
    for i, left in enumerate(sets):
        for right in sets[i + 1 :]:
            union = left | right
            if not union:
                distances.append(0.0)
            else:
                distances.append(1.0 - len(left & right) / len(union))
    return mean(distances) if distances else 0.0


def unsupported_claim_rate(outputs: list[AgentOutput]) -> float:
    total = sum(len(output.key_claims) for output in outputs)
    if total == 0:
        return 0.0
    unsupported = sum(len(output.unsupported_claims) for output in outputs)
    return min(unsupported / total, 1.0)


def composite_disagreement(
    outputs: list[AgentOutput],
    *,
    label_weight: float = 0.35,
    allocation_weight: float = 0.25,
    evidence_weight: float = 0.25,
    unsupported_weight: float = 0.15,
) -> float:
    weight_sum = label_weight + allocation_weight + evidence_weight + unsupported_weight
    if weight_sum <= 0:
        label_weight, allocation_weight, evidence_weight, unsupported_weight = 0.35, 0.25, 0.25, 0.15
        weight_sum = 1.0
    score = (
        (label_weight / weight_sum) * label_disagreement(outputs)
        + (allocation_weight / weight_sum) * allocation_disagreement(outputs)
        + (evidence_weight / weight_sum) * evidence_disagreement(outputs)
        + (unsupported_weight / weight_sum) * unsupported_claim_rate(outputs)
    )
    return min(max(score, 0.0), 1.0)


def label_consistency(predictions: list[dict[str, Any]]) -> float:
    labels = [item.get("final", {}).get("liability_label") for item in predictions if item.get("final")]
    labels = [label for label in labels if label]
    if not labels:
        return 0.0
    majority = max(set(labels), key=labels.count)
    return labels.count(majority) / len(labels)


def allocation_variance(predictions: list[dict[str, Any]]) -> float:
    values: list[float] = []
    parties = sorted(
        {
            party
            for item in predictions
            for party in item.get("final", {}).get("allocation", {})
        }
    )
    if not parties:
        return 0.0
    for party in parties:
        party_values = [float(item.get("final", {}).get("allocation", {}).get(party, 0.0)) for item in predictions]
        if len(party_values) > 1:
            avg = mean(party_values)
            values.append(mean([(value - avg) ** 2 for value in party_values]))
    return mean(values) if values else 0.0


def evidence_overlap(predictions: list[dict[str, Any]]) -> float:
    evidence_sets = [set(item.get("final", {}).get("evidence_ids", [])) for item in predictions]
    evidence_sets = [item for item in evidence_sets if item]
    if len(evidence_sets) <= 1:
        return 1.0 if evidence_sets else 0.0
    overlaps: list[float] = []
    for i, left in enumerate(evidence_sets):
        for right in evidence_sets[i + 1 :]:
            union = left | right
            overlaps.append(len(left & right) / len(union) if union else 1.0)
    return mean(overlaps) if overlaps else 0.0


def consensus_summary(predictions: list[dict[str, Any]]) -> dict[str, float]:
    values = [float(item.get("final", {}).get("consensus_score", 0.0)) for item in predictions]
    if not values:
        return {"consensus_score_mean": 0.0, "consensus_score_std": 0.0}
    return {
        "consensus_score_mean": mean(values),
        "consensus_score_std": pstdev(values) if len(values) > 1 else 0.0,
    }


def unsupported_claim_summary(predictions: list[dict[str, Any]]) -> dict[str, float]:
    values = [float(item.get("final", {}).get("unsupported_claim_rate", 0.0)) for item in predictions]
    if not values:
        return {"unsupported_claim_rate_mean": 0.0, "unsupported_claim_rate_std": 0.0}
    return {
        "unsupported_claim_rate_mean": mean(values),
        "unsupported_claim_rate_std": pstdev(values) if len(values) > 1 else 0.0,
    }


def macro_f1_from_counts(labels: list[str], predictions: list[str]) -> tuple[float, dict[str, float]]:
    classes = sorted(set(labels) | set(predictions))
    per_class: dict[str, float] = {}
    for cls in classes:
        tp = sum(1 for y, p in zip(labels, predictions) if y == cls and p == cls)
        fp = sum(1 for y, p in zip(labels, predictions) if y != cls and p == cls)
        fn = sum(1 for y, p in zip(labels, predictions) if y == cls and p != cls)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        per_class[cls] = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return (mean(per_class.values()) if per_class else 0.0, per_class)


def finite_or_zero(value: float) -> float:
    return value if math.isfinite(value) else 0.0
