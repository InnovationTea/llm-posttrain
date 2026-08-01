#!/usr/bin/env python3
"""Extract comparable GRPO metrics from a veRL console log."""

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
GLOBAL_STEP_PATTERN = re.compile(r"global[ _]step\s*[:=]?\s*(\d+)", re.IGNORECASE)
SEVERE_ERROR_PATTERN = re.compile(
    r"traceback|runtimeerror|out of memory|\boom\b|hccl.*(?:error|timeout)|childfailed",
    re.IGNORECASE,
)
NONFINITE_PATTERN = re.compile(
    r"(?:loss|grad[_/]?norm|reward|advantage)[^\n,}]*[:=]\s*(?:nan|[-+]?inf)\b",
    re.IGNORECASE,
)

TIMING_KEYS = {
    "gen": "timing_s/gen",
    "old_log_prob": "timing_s/old_log_prob",
    "ref": "timing_s/ref",
    "update_actor": "timing_s/update_actor",
    "update_weights": "timing_s/update_weights",
    "step": "timing_s/step",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-file", type=Path, required=True)
    parser.add_argument("--output-file", type=Path, required=True)
    parser.add_argument("--text-output", type=Path)
    parser.add_argument("--expected-steps", type=int, required=True)
    parser.add_argument("--warmup-steps", type=int, default=5)
    parser.add_argument("--prompt-batch-size", type=int, default=8)
    parser.add_argument("--rollout-n", type=int, default=4)
    parser.add_argument("--npu-count", type=int, default=16)
    return parser.parse_args()


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * quantile)]


def find_metric(metrics: dict[str, float], wanted: str) -> float | None:
    wanted = wanted.lower()
    for key, value in metrics.items():
        if key.lower() == wanted:
            return value
    return None


def find_component(metrics: dict[str, float], component: str) -> float | None:
    for key, value in metrics.items():
        if re.split(r"[/.]", key.lower())[-1] == component:
            return value
    return None


def find_step(line: str, metrics: dict[str, float]) -> int | None:
    if match := GLOBAL_STEP_PATTERN.search(line):
        return int(match.group(1))
    for key, value in metrics.items():
        component = re.split(r"[/.]", key.lower())[-1]
        if component in {"step", "global_step"} and "timing" not in key.lower():
            if math.isfinite(value) and value >= 0 and value.is_integer():
                return int(value)
    return None


def parse_log(text: str) -> dict[str, Any]:
    steps: dict[int, dict[str, float]] = {}
    severe_errors: list[dict[str, Any]] = []
    nonfinite_metrics: list[dict[str, Any]] = []
    memory_values: dict[str, list[float]] = {}

    for line_number, line in enumerate(text.splitlines(), start=1):
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
            if "memory" in key.lower() and math.isfinite(value):
                memory_values.setdefault(key, []).append(value)

        step = find_step(line, metrics)
        if step is None:
            continue
        record = steps.setdefault(step, {})
        for output_name, log_key in TIMING_KEYS.items():
            value = find_metric(metrics, log_key)
            if value is not None and math.isfinite(value) and value >= 0:
                record[f"timing_{output_name}_s"] = value

        for output_name, log_key in {
            "response_length_mean": "response_length/mean",
            "response_length_max": "response_length/max",
            "response_clip_ratio": "response_length/clip_ratio",
            "reward_mean": "critic/rewards/mean",
            "advantage_mean": "critic/advantages/mean",
            "actor_loss": "actor/loss",
            "actor_grad_norm": "actor/grad_norm",
        }.items():
            value = find_metric(metrics, log_key)
            if value is not None:
                record[output_name] = value

        # Some veRL versions omit the namespace for these common fields.
        if "reward_mean" not in record:
            value = find_component(metrics, "reward_mean")
            if value is not None:
                record["reward_mean"] = value

    return {
        "steps": steps,
        "severe_errors": severe_errors,
        "nonfinite_metrics": nonfinite_metrics,
        "memory_values": memory_values,
    }


def metric_stats(values: list[float]) -> dict[str, float | int | None]:
    return {
        "count": len(values),
        "mean": mean(values) if values else None,
        "median": median(values) if values else None,
        "p95": percentile(values, 0.95),
        "min": min(values) if values else None,
        "max": max(values) if values else None,
    }


def summarize(
    parsed: dict[str, Any],
    expected_steps: int,
    warmup_steps: int,
    prompt_batch_size: int,
    rollout_n: int,
    npu_count: int,
) -> dict[str, Any]:
    steps: dict[int, dict[str, float]] = parsed["steps"]
    observed_steps = sorted(steps)
    measured_step_ids = [step for step in observed_steps if step > warmup_steps]

    timing: dict[str, dict[str, float | int | None]] = {}
    for name in TIMING_KEYS:
        values = [
            steps[step][f"timing_{name}_s"]
            for step in measured_step_ids
            if f"timing_{name}_s" in steps[step]
        ]
        timing[name] = metric_stats(values)

    responses_per_step = prompt_batch_size * rollout_n
    rollout_tokens = 0.0
    rollout_seconds = 0.0
    rollout_token_steps = 0
    for step in measured_step_ids:
        record = steps[step]
        if "response_length_mean" in record and "timing_gen_s" in record:
            rollout_tokens += record["response_length_mean"] * responses_per_step
            rollout_seconds += record["timing_gen_s"]
            rollout_token_steps += 1
    rollout_tokens_per_second = (
        rollout_tokens / rollout_seconds if rollout_seconds > 0 else None
    )

    completed = bool(observed_steps) and max(observed_steps) >= expected_steps
    valid = (
        completed
        and not parsed["severe_errors"]
        and not parsed["nonfinite_metrics"]
    )
    unavailable: list[str] = []
    if not timing["step"]["count"]:
        unavailable.append("timing_s/step was not found in the log")
    if not timing["gen"]["count"]:
        unavailable.append("timing_s/gen was not found in the log")
    if rollout_tokens_per_second is None:
        unavailable.append(
            "response_length/mean and timing_s/gen were not both available"
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
        "prompt_batch_size": prompt_batch_size,
        "rollout_n": rollout_n,
        "responses_per_step": responses_per_step,
        "npu_count": npu_count,
        "timing_s": timing,
        "rollout_output_tokens_per_second": rollout_tokens_per_second,
        "rollout_output_tokens_per_second_per_npu": (
            rollout_tokens_per_second / npu_count
            if rollout_tokens_per_second is not None
            else None
        ),
        "rollout_token_steps": rollout_token_steps,
        "reward_mean": metric_stats(
            [steps[s]["reward_mean"] for s in measured_step_ids if "reward_mean" in steps[s]]
        ),
        "response_length_mean": metric_stats(
            [
                steps[s]["response_length_mean"]
                for s in measured_step_ids
                if "response_length_mean" in steps[s]
            ]
        ),
        "memory_peaks_from_log": {
            key: max(values)
            for key, values in parsed["memory_values"].items()
            if values
        },
        "severe_errors": parsed["severe_errors"][:20],
        "nonfinite_metrics": parsed["nonfinite_metrics"][:20],
        "unavailable_metrics": unavailable,
    }


def format_value(value: float | None, unit: str = "") -> str:
    return "unavailable" if value is None else f"{value:.3f}{unit}"


def render_text(summary: dict[str, Any]) -> str:
    timing = summary["timing_s"]
    lines = [
        f"status: {summary['status']}",
        f"completed steps: {summary['max_observed_step']} / {summary['expected_steps']}",
        f"measured steps: {len(summary['measured_step_ids'])} "
        f"(warmup={summary['warmup_steps']})",
        f"mean step time: {format_value(timing['step']['mean'], ' s')}",
        f"p95 step time: {format_value(timing['step']['p95'], ' s')}",
        f"mean rollout time: {format_value(timing['gen']['mean'], ' s')}",
        f"mean actor update time: {format_value(timing['update_actor']['mean'], ' s')}",
        "rollout output tokens/s: "
        f"{format_value(summary['rollout_output_tokens_per_second'])}",
        "rollout output tokens/s/NPU: "
        f"{format_value(summary['rollout_output_tokens_per_second_per_npu'])}",
        f"mean response length: {format_value(summary['response_length_mean']['mean'])}",
        f"mean reward: {format_value(summary['reward_mean']['mean'])}",
        f"severe errors: {len(summary['severe_errors'])}",
        f"non-finite metrics: {len(summary['nonfinite_metrics'])}",
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
    if min(args.prompt_batch_size, args.rollout_n, args.npu_count) < 1:
        raise ValueError("batch size, rollout-n and NPU count must be positive")
    if not args.log_file.is_file():
        raise FileNotFoundError(f"Missing log file: {args.log_file}")

    parsed = parse_log(args.log_file.read_text(encoding="utf-8", errors="replace"))
    summary = summarize(
        parsed,
        args.expected_steps,
        args.warmup_steps,
        args.prompt_batch_size,
        args.rollout_n,
        args.npu_count,
    )
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
