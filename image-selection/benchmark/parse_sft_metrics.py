#!/usr/bin/env python3
"""Extract comparable SFT metrics from a veRL console log."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from statistics import mean, median
from typing import Any


NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
METRIC_PATTERN = re.compile(
    rf"(?P<quote>['\"]?)(?P<key>[A-Za-z_][A-Za-z0-9_./-]*)"
    rf"(?P=quote)\s*[:=]\s*(?P<value>{NUMBER}|nan|inf|-inf)",
    re.IGNORECASE,
)
SEVERE_ERROR_PATTERN = re.compile(
    r"traceback|runtimeerror|out of memory|\boom\b|hccl.*(?:error|timeout)|childfailed",
    re.IGNORECASE,
)
NONFINITE_PATTERN = re.compile(
    r"(?:loss|grad[_/]?norm)[^\n,}]*[:=]\s*(?:nan|[-+]?inf)\b",
    re.IGNORECASE,
)

STEP_KEYS = {"step", "global_step"}
STEP_TIME_KEYS = {
    "step_time",
    "step_time_s",
    "time_per_step",
    "time_per_step_s",
    "timing_s/step",
    "time/step",
    "train/step_time",
    "train/step_time_s",
}
TOKEN_KEYS = {
    "num_tokens",
    "total_tokens",
    "valid_tokens",
    "global_valid_tokens",
    "tokens_per_batch",
    "train/num_tokens",
    "train/total_tokens",
    "train/valid_tokens",
    "train/global_valid_tokens",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-file", type=Path, required=True)
    parser.add_argument("--output-file", type=Path, required=True)
    parser.add_argument("--text-output", type=Path)
    parser.add_argument("--expected-steps", type=int, required=True)
    parser.add_argument("--warmup-steps", type=int, default=5)
    return parser.parse_args()


def normalized_key(key: str) -> str:
    return key.strip().lower()


def final_component(key: str) -> str:
    return re.split(r"[/.]", normalized_key(key))[-1]


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = round((len(ordered) - 1) * quantile)
    return ordered[index]


def find_named_value(metrics: dict[str, float], keys: set[str]) -> float | None:
    for key, value in metrics.items():
        normalized = normalized_key(key)
        if normalized in keys:
            return value
    return None


def find_step(metrics: dict[str, float]) -> int | None:
    for key, value in metrics.items():
        if final_component(key) in STEP_KEYS and "time" not in normalized_key(key):
            if math.isfinite(value) and value >= 0 and value.is_integer():
                return int(value)
    return None


def find_metric_by_component(
    metrics: dict[str, float], components: set[str]
) -> float | None:
    for key, value in metrics.items():
        if final_component(key) in components:
            return value
    return None


def parse_log(text: str) -> dict[str, Any]:
    steps: dict[int, dict[str, float]] = {}
    severe_errors: list[dict[str, Any]] = []
    nonfinite_metrics: list[dict[str, Any]] = []
    global_batch_size: int | None = None
    npu_count: int | None = None
    memory_values: dict[str, list[float]] = {}

    for line_number, line in enumerate(text.splitlines(), start=1):
        if match := re.search(r"Global batch size:\s*(\d+)", line, re.IGNORECASE):
            global_batch_size = int(match.group(1))
        if match := re.search(
            r"(?:Visible NPU processes|Visible NPU count):\s*(\d+)",
            line,
            re.IGNORECASE,
        ):
            npu_count = int(match.group(1))

        if SEVERE_ERROR_PATTERN.search(line):
            severe_errors.append({"line": line_number, "text": line[-500:]})
        if NONFINITE_PATTERN.search(line):
            nonfinite_metrics.append({"line": line_number, "text": line[-500:]})

        metrics: dict[str, float] = {}
        for match in METRIC_PATTERN.finditer(line):
            try:
                metrics[match.group("key")] = float(match.group("value"))
            except ValueError:
                continue
        if not metrics:
            continue

        for key, value in metrics.items():
            normalized = normalized_key(key)
            if "memory" in normalized and math.isfinite(value):
                memory_values.setdefault(key, []).append(value)

        step = find_step(metrics)
        if step is None:
            continue
        record = steps.setdefault(step, {})

        step_time = find_named_value(metrics, STEP_TIME_KEYS)
        if step_time is not None and math.isfinite(step_time) and step_time > 0:
            record["step_time_s"] = step_time

        loss = find_metric_by_component(metrics, {"loss"})
        if loss is not None:
            record["loss"] = loss
        grad_norm = find_metric_by_component(metrics, {"grad_norm", "gradnorm"})
        if grad_norm is not None:
            record["grad_norm"] = grad_norm
        token_count = find_named_value(metrics, TOKEN_KEYS)
        if token_count is not None and math.isfinite(token_count) and token_count > 0:
            record["effective_tokens"] = token_count

    return {
        "steps": steps,
        "global_batch_size": global_batch_size,
        "npu_count": npu_count,
        "severe_errors": severe_errors,
        "nonfinite_metrics": nonfinite_metrics,
        "memory_values": memory_values,
    }


def summarize(
    parsed: dict[str, Any], expected_steps: int, warmup_steps: int
) -> dict[str, Any]:
    steps: dict[int, dict[str, float]] = parsed["steps"]
    observed_steps = sorted(steps)
    measured_step_ids = [step for step in observed_steps if step > warmup_steps]
    step_times = [
        steps[step]["step_time_s"]
        for step in measured_step_ids
        if "step_time_s" in steps[step]
    ]
    losses = [
        steps[step]["loss"] for step in observed_steps if "loss" in steps[step]
    ]
    grad_norms = [
        steps[step]["grad_norm"]
        for step in observed_steps
        if "grad_norm" in steps[step]
    ]
    token_counts = [
        steps[step]["effective_tokens"]
        for step in measured_step_ids
        if "effective_tokens" in steps[step] and "step_time_s" in steps[step]
    ]
    token_times = [
        steps[step]["step_time_s"]
        for step in measured_step_ids
        if "effective_tokens" in steps[step] and "step_time_s" in steps[step]
    ]

    mean_step_time = mean(step_times) if step_times else None
    global_batch_size = parsed["global_batch_size"]
    npu_count = parsed["npu_count"]
    samples_per_second = (
        global_batch_size / mean_step_time
        if global_batch_size is not None and mean_step_time is not None
        else None
    )
    tokens_per_second = (
        sum(token_counts) / sum(token_times) if token_counts and token_times else None
    )

    missing: list[str] = []
    if not step_times:
        missing.append("step time was not found in the log")
    if global_batch_size is None:
        missing.append("global batch size was not found in the log")
    if not token_counts:
        missing.append("per-step effective token count was not found in the log")
    if npu_count is None:
        missing.append("NPU count was not found in the log")

    memory_peaks = {
        key: max(values) for key, values in parsed["memory_values"].items() if values
    }
    completed = bool(observed_steps) and max(observed_steps) >= expected_steps
    valid = (
        completed
        and not parsed["severe_errors"]
        and not parsed["nonfinite_metrics"]
    )
    return {
        "schema_version": 1,
        "status": "PASS" if valid else "FAIL",
        "expected_steps": expected_steps,
        "warmup_steps": warmup_steps,
        "observed_steps": observed_steps,
        "max_observed_step": max(observed_steps) if observed_steps else None,
        "completed_expected_steps": completed,
        "measured_step_ids": measured_step_ids,
        "global_batch_size": global_batch_size,
        "npu_count": npu_count,
        "step_time": {
            "count": len(step_times),
            "mean_s": mean_step_time,
            "median_s": median(step_times) if step_times else None,
            "p95_s": percentile(step_times, 0.95),
            "min_s": min(step_times) if step_times else None,
            "max_s": max(step_times) if step_times else None,
        },
        "samples_per_second": samples_per_second,
        "samples_per_second_per_npu": (
            samples_per_second / npu_count
            if samples_per_second is not None and npu_count
            else None
        ),
        "effective_tokens_per_second": tokens_per_second,
        "effective_tokens_per_second_per_npu": (
            tokens_per_second / npu_count
            if tokens_per_second is not None and npu_count
            else None
        ),
        "loss": {
            "count": len(losses),
            "first": losses[0] if losses else None,
            "last": losses[-1] if losses else None,
            "min": min(losses) if losses else None,
            "max": max(losses) if losses else None,
        },
        "grad_norm": {
            "count": len(grad_norms),
            "min": min(grad_norms) if grad_norms else None,
            "max": max(grad_norms) if grad_norms else None,
        },
        "memory_peaks_from_log": memory_peaks,
        "severe_errors": parsed["severe_errors"][:20],
        "nonfinite_metrics": parsed["nonfinite_metrics"][:20],
        "unavailable_metrics": missing,
    }


def format_value(value: float | None, unit: str = "") -> str:
    return "unavailable" if value is None else f"{value:.3f}{unit}"


def render_text(summary: dict[str, Any]) -> str:
    step_time = summary["step_time"]
    lines = [
        f"status: {summary['status']}",
        f"completed steps: {summary['max_observed_step']} / {summary['expected_steps']}",
        f"measured steps: {step_time['count']} (warmup={summary['warmup_steps']})",
        f"mean step time: {format_value(step_time['mean_s'], ' s')}",
        f"p95 step time: {format_value(step_time['p95_s'], ' s')}",
        f"samples/s: {format_value(summary['samples_per_second'])}",
        f"samples/s/NPU: {format_value(summary['samples_per_second_per_npu'])}",
        f"effective tokens/s: {format_value(summary['effective_tokens_per_second'])}",
        "effective tokens/s/NPU: "
        f"{format_value(summary['effective_tokens_per_second_per_npu'])}",
        f"severe errors: {len(summary['severe_errors'])}",
        f"non-finite loss/grad_norm: {len(summary['nonfinite_metrics'])}",
    ]
    if summary["unavailable_metrics"]:
        lines.append("unavailable:")
        lines.extend(f"- {item}" for item in summary["unavailable_metrics"])
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    if args.expected_steps < 1:
        raise ValueError("--expected-steps must be positive")
    if args.warmup_steps < 0 or args.warmup_steps >= args.expected_steps:
        raise ValueError("--warmup-steps must be in [0, expected_steps)")
    if not args.log_file.is_file():
        raise FileNotFoundError(f"Missing log file: {args.log_file}")

    parsed = parse_log(args.log_file.read_text(encoding="utf-8", errors="replace"))
    summary = summarize(parsed, args.expected_steps, args.warmup_steps)
    args.output_file.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    text_report = render_text(summary)
    if args.text_output:
        args.text_output.write_text(text_report, encoding="utf-8")
    print(text_report, end="")
    if summary["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
