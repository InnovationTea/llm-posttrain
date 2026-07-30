#!/usr/bin/env python3
"""Compare paired before/after GSM8K evaluation results."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from statistics import mean
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--output-file", type=Path, required=True)
    parser.add_argument("--bootstrap-samples", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def load_results(path: Path) -> dict[int, dict[str, Any]]:
    rows: dict[int, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as input_stream:
        for line_number, line in enumerate(input_stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            index = row["index"]
            if index in rows:
                raise ValueError(f"{path}:{line_number}: duplicate index {index}")
            rows[index] = row
    if not rows:
        raise ValueError(f"No evaluation rows found in {path}")
    return rows


def load_summary(result_path: Path) -> dict[str, Any]:
    summary_path = (
        result_path.with_suffix(".summary.json")
        if result_path.suffix
        else Path(f"{result_path}.summary.json")
    )
    if not summary_path.is_file():
        raise FileNotFoundError(f"Missing evaluation summary: {summary_path}")
    return json.loads(summary_path.read_text(encoding="utf-8"))


def bootstrap_interval(
    differences: list[int],
    samples: int,
    seed: int,
) -> list[float]:
    if samples < 1:
        raise ValueError("--bootstrap-samples must be positive")
    rng = random.Random(seed)
    size = len(differences)
    estimates = sorted(
        sum(differences[rng.randrange(size)] for _ in range(size)) / size
        for _ in range(samples)
    )
    return [
        estimates[round((samples - 1) * 0.025)],
        estimates[round((samples - 1) * 0.975)],
    ]


def paired_differences(pairs: list[tuple[dict, dict]], key: str) -> list[int]:
    return [int(after[key]) - int(before[key]) for before, after in pairs]


def transition_report(
    pairs: list[tuple[dict, dict]],
    key: str,
) -> tuple[dict[str, int], list[int], list[int]]:
    improved = [
        before["index"] for before, after in pairs if not before[key] and after[key]
    ]
    regressed = [
        before["index"] for before, after in pairs if before[key] and not after[key]
    ]
    report = {
        "wrong_to_right": len(improved),
        "right_to_wrong": len(regressed),
        "both_correct": sum(before[key] and after[key] for before, after in pairs),
        "both_wrong": sum(not before[key] and not after[key] for before, after in pairs),
    }
    return report, improved, regressed


def main() -> None:
    args = parse_args()
    before = load_results(args.before)
    after = load_results(args.after)
    before_summary = load_summary(args.before)
    after_summary = load_summary(args.after)

    for field in (
        "tokenizer_path",
        "tensor_parallel_size",
        "max_model_len",
        "max_new_tokens",
        "enable_thinking",
        "seed",
    ):
        if before_summary[field] != after_summary[field]:
            raise ValueError(f"Evaluation setting differs between runs: {field}")
    if before.keys() != after.keys():
        raise ValueError("Before and after files contain different example indices")

    pairs = []
    for index in sorted(before):
        before_row = before[index]
        after_row = after[index]
        for field in ("question", "reference"):
            if before_row[field] != after_row[field]:
                raise ValueError(f"Example {index}: {field} differs between runs")
        pairs.append((before_row, after_row))

    answer_transitions, answer_improved, answer_regressed = transition_report(pairs, "correct")
    strict_transitions, strict_improved, strict_regressed = transition_report(
        pairs,
        "strict_correct",
    )
    answer_differences = paired_differences(pairs, "correct")
    strict_differences = paired_differences(pairs, "strict_correct")

    report = {
        "before_file": str(args.before),
        "after_file": str(args.after),
        "before_model": before_summary["model_path"],
        "after_model": after_summary["model_path"],
        "total": len(pairs),
        "before_accuracy": mean(row[0]["correct"] for row in pairs),
        "after_accuracy": mean(row[1]["correct"] for row in pairs),
        "accuracy_delta": mean(answer_differences),
        "accuracy_delta_95pct_bootstrap": bootstrap_interval(
            answer_differences,
            args.bootstrap_samples,
            args.seed,
        ),
        "before_strict_accuracy": mean(row[0]["strict_correct"] for row in pairs),
        "after_strict_accuracy": mean(row[1]["strict_correct"] for row in pairs),
        "strict_accuracy_delta": mean(strict_differences),
        "strict_accuracy_delta_95pct_bootstrap": bootstrap_interval(
            strict_differences,
            args.bootstrap_samples,
            args.seed,
        ),
        "before_format_valid_rate": mean(row[0]["format_valid"] for row in pairs),
        "after_format_valid_rate": mean(row[1]["format_valid"] for row in pairs),
        "format_valid_rate_delta": mean(paired_differences(pairs, "format_valid")),
        "before_truncated": sum(row[0]["truncated"] for row in pairs),
        "after_truncated": sum(row[1]["truncated"] for row in pairs),
        "before_truncation_rate": mean(row[0]["truncated"] for row in pairs),
        "after_truncation_rate": mean(row[1]["truncated"] for row in pairs),
        "truncation_rate_delta": mean(paired_differences(pairs, "truncated")),
        "before_average_completion_tokens": mean(row[0]["completion_tokens"] for row in pairs),
        "after_average_completion_tokens": mean(row[1]["completion_tokens"] for row in pairs),
        "answer_transitions": answer_transitions,
        "strict_transitions": strict_transitions,
        "answer_improved_indices": answer_improved,
        "answer_regressed_indices": answer_regressed,
        "strict_improved_indices": strict_improved,
        "strict_regressed_indices": strict_regressed,
        "bootstrap_samples": args.bootstrap_samples,
        "seed": args.seed,
    }

    args.output_file.parent.mkdir(parents=True, exist_ok=True)
    args.output_file.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Comparison saved to: {args.output_file}")


if __name__ == "__main__":
    main()
