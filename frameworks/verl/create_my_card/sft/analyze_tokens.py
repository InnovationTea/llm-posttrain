#!/usr/bin/env python3
"""Measure Qwen3.6 SFT token lengths and build a worst-case OOM probe split."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = BASE_DIR / "data" / "parquet"


class TokenValidationError(ValueError):
    """Raised when tokenization is inconsistent with the SFT contract."""


@dataclass(frozen=True)
class AnalyzedRow:
    split: str
    sample_id: str
    prompt_tokens: int
    assistant_tokens: int
    total_tokens: int
    source_row: dict[str, Any]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--train-parquet", type=Path, default=DEFAULT_DATA_DIR / "train.parquet")
    parser.add_argument(
        "--validation-parquet",
        type=Path,
        default=DEFAULT_DATA_DIR / "validation.parquet",
    )
    parser.add_argument("--report", type=Path, default=DEFAULT_DATA_DIR / "token_stats.json")
    parser.add_argument("--max-prompt-tokens", type=int, default=24_576)
    parser.add_argument("--max-output-tokens", type=int, default=8_192)
    parser.add_argument("--hard-max-total-tokens", type=int, default=32_768)
    parser.add_argument("--length-alignment", type=int, default=256)
    parser.add_argument("--minimum-max-length", type=int, default=2_048)
    parser.add_argument("--probe-output", type=Path)
    parser.add_argument("--probe-rows", type=int, default=256)
    parser.add_argument("--probe-pool-size", type=int, default=8)
    return parser.parse_args()


def normalize_input_ids(tokenized: Any) -> list[int]:
    if isinstance(tokenized, Mapping):
        tokenized = tokenized.get("input_ids")
    if hasattr(tokenized, "tolist"):
        tokenized = tokenized.tolist()
    if tokenized and isinstance(tokenized[0], list):
        if len(tokenized) != 1:
            raise TokenValidationError("chat template unexpectedly returned a batch")
        tokenized = tokenized[0]
    if not isinstance(tokenized, list) or not all(isinstance(value, int) for value in tokenized):
        raise TokenValidationError(
            f"chat template returned unsupported input_ids type: {type(tokenized).__name__}"
        )
    return tokenized


def apply_template(tokenizer: Any, messages: list[dict[str, str]], *, generation: bool) -> list[int]:
    tokenized = tokenizer.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=generation,
        enable_thinking=False,
    )
    return normalize_input_ids(tokenized)


def validate_messages(messages: Any, sample_id: str) -> list[dict[str, str]]:
    if not isinstance(messages, list):
        raise TokenValidationError(f"{sample_id}: messages must be a list")
    roles = [message.get("role") if isinstance(message, dict) else None for message in messages]
    if roles not in (["user", "assistant"], ["system", "user", "assistant"]):
        raise TokenValidationError(
            f"{sample_id}: roles must be user/assistant or system/user/assistant, got {roles}"
        )
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            raise TokenValidationError(f"{sample_id}: message {index} must be an object")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise TokenValidationError(f"{sample_id}: {message.get('role')} content is empty")
    assistant = messages[-1]["content"].lower()
    if "<think>" in assistant or "</think>" in assistant:
        raise TokenValidationError(f"{sample_id}: assistant label contains <think> tags")
    return messages


def analyze_row(row: dict[str, Any], tokenizer: Any, split: str, row_index: int) -> AnalyzedRow:
    sample_id = row.get("id")
    if not isinstance(sample_id, str) or not sample_id:
        raise TokenValidationError(f"{split} row {row_index}: id must be a non-empty string")
    if row.get("enable_thinking") is not False:
        raise TokenValidationError(f"{split}/{sample_id}: enable_thinking must be false")
    messages = validate_messages(row.get("messages"), f"{split}/{sample_id}")

    prompt_ids = apply_template(tokenizer, messages[:-1], generation=True)
    full_ids = apply_template(tokenizer, messages, generation=False)
    if full_ids[: len(prompt_ids)] != prompt_ids:
        raise TokenValidationError(
            f"{split}/{sample_id}: training sequence does not start with the non-thinking inference prompt"
        )
    assistant_tokens = len(full_ids) - len(prompt_ids)
    if assistant_tokens <= 0:
        raise TokenValidationError(f"{split}/{sample_id}: assistant has no trainable tokens")
    return AnalyzedRow(
        split=split,
        sample_id=sample_id,
        prompt_tokens=len(prompt_ids),
        assistant_tokens=assistant_tokens,
        total_tokens=len(full_ids),
        source_row=row,
    )


def analyze_rows(rows: Iterable[dict[str, Any]], tokenizer: Any, split: str) -> list[AnalyzedRow]:
    analyzed = [analyze_row(row, tokenizer, split, index) for index, row in enumerate(rows)]
    if not analyzed:
        raise TokenValidationError(f"{split} split is empty")
    return analyzed


def percentile(sorted_values: list[int], quantile: float) -> int:
    if not sorted_values:
        raise TokenValidationError("cannot calculate percentiles for an empty sequence")
    index = max(0, min(len(sorted_values) - 1, math.ceil(len(sorted_values) * quantile) - 1))
    return sorted_values[index]


def summarize(values: Iterable[int]) -> dict[str, int]:
    sorted_values = sorted(values)
    return {
        "min": sorted_values[0],
        "p50": percentile(sorted_values, 0.50),
        "p90": percentile(sorted_values, 0.90),
        "p95": percentile(sorted_values, 0.95),
        "p99": percentile(sorted_values, 0.99),
        "max": sorted_values[-1],
    }


def align_up(value: int, alignment: int) -> int:
    if value < 0 or alignment <= 0:
        raise TokenValidationError("value must be non-negative and alignment must be positive")
    return ((value + alignment - 1) // alignment) * alignment


def detect_model_context_length(config: Any, tokenizer: Any) -> int | None:
    candidates: list[Any] = [
        getattr(config, "max_position_embeddings", None),
        getattr(getattr(config, "text_config", None), "max_position_embeddings", None),
        getattr(tokenizer, "model_max_length", None),
    ]
    valid = [value for value in candidates if isinstance(value, int) and 0 < value < 10_000_000]
    return min(valid) if valid else None


def collect_violations(
    rows: Iterable[AnalyzedRow],
    *,
    max_prompt_tokens: int,
    max_output_tokens: int,
    hard_max_total_tokens: int,
    model_context_length: int | None,
) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    for row in rows:
        reasons: list[str] = []
        if max_prompt_tokens > 0 and row.prompt_tokens > max_prompt_tokens:
            reasons.append("prompt")
        if max_output_tokens > 0 and row.assistant_tokens > max_output_tokens:
            reasons.append("assistant")
        if hard_max_total_tokens > 0 and row.total_tokens > hard_max_total_tokens:
            reasons.append("hard_total")
        if model_context_length is not None and row.total_tokens > model_context_length:
            reasons.append("model_context")
        if reasons:
            violations.append(
                {
                    "split": row.split,
                    "id": row.sample_id,
                    "promptTokens": row.prompt_tokens,
                    "assistantTokens": row.assistant_tokens,
                    "totalTokens": row.total_tokens,
                    "reasons": reasons,
                }
            )
    return violations


def load_parquet(path: Path) -> tuple[list[dict[str, Any]], Any]:
    if not path.is_file():
        raise FileNotFoundError(f"parquet file does not exist: {path}")
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError("pyarrow is required; install requirements.txt") from exc
    table = pq.read_table(path)
    required = {"id", "messages", "enable_thinking"}
    missing = required - set(table.column_names)
    if missing:
        raise TokenValidationError(f"{path} is missing columns: {sorted(missing)}")
    return table.to_pylist(), table.schema


def write_json_atomic(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            temporary_path = Path(stream.name)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def write_oom_probe(
    analyzed_train: list[AnalyzedRow],
    source_schema: Any,
    output_path: Path,
    *,
    probe_rows: int,
    pool_size: int,
) -> None:
    if probe_rows <= 0 or pool_size <= 0:
        raise TokenValidationError("probe rows and pool size must be positive")
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError("pyarrow is required; install requirements.txt") from exc

    longest = sorted(analyzed_train, key=lambda row: (-row.total_tokens, row.sample_id))
    pool = longest[: min(pool_size, len(longest))]
    probe: list[dict[str, Any]] = []
    for index in range(probe_rows):
        selected = pool[index % len(pool)]
        row = dict(selected.source_row)
        row["id"] = f"{selected.sample_id}__oom_probe_{index:04d}"
        probe.append(row)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(probe, schema=source_schema)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
        pq.write_table(table, temporary_path, compression="zstd")
        os.replace(temporary_path, output_path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def build_report(
    analyzed: list[AnalyzedRow],
    *,
    model_path: str,
    model_context_length: int | None,
    chat_template_sha256: str,
    max_prompt_tokens: int,
    max_output_tokens: int,
    hard_max_total_tokens: int,
    minimum_max_length: int,
    length_alignment: int,
) -> dict[str, Any]:
    observed_max = max(row.total_tokens for row in analyzed)
    recommended = max(minimum_max_length, align_up(observed_max, length_alignment))
    violations = collect_violations(
        analyzed,
        max_prompt_tokens=max_prompt_tokens,
        max_output_tokens=max_output_tokens,
        hard_max_total_tokens=hard_max_total_tokens,
        model_context_length=model_context_length,
    )
    splits: dict[str, Any] = {}
    for split in sorted({row.split for row in analyzed}):
        rows = [row for row in analyzed if row.split == split]
        splits[split] = {
            "count": len(rows),
            "promptTokens": summarize(row.prompt_tokens for row in rows),
            "assistantTokens": summarize(row.assistant_tokens for row in rows),
            "totalTokens": summarize(row.total_tokens for row in rows),
        }
    per_sample = [
        {
            "split": row.split,
            "id": row.sample_id,
            "promptTokens": row.prompt_tokens,
            "assistantTokens": row.assistant_tokens,
            "totalTokens": row.total_tokens,
        }
        for row in sorted(analyzed, key=lambda item: (item.split, item.sample_id))
    ]
    longest = sorted(analyzed, key=lambda row: (-row.total_tokens, row.split, row.sample_id))[:10]
    return {
        "modelPath": model_path,
        "thinkingMode": False,
        "chatTemplateSha256": chat_template_sha256,
        "modelContextLength": model_context_length,
        "limits": {
            "maxPromptTokens": max_prompt_tokens,
            "maxAssistantTokens": max_output_tokens,
            "hardMaxTotalTokens": hard_max_total_tokens,
        },
        "recommendedMaxLength": recommended,
        "observedMaxTotalTokens": observed_max,
        "splits": splits,
        "longestSamples": [
            {
                "split": row.split,
                "id": row.sample_id,
                "promptTokens": row.prompt_tokens,
                "assistantTokens": row.assistant_tokens,
                "totalTokens": row.total_tokens,
            }
            for row in longest
        ],
        "violations": violations,
        "perSample": per_sample,
    }


def main() -> None:
    args = parse_args()
    for label, value in (
        ("--length-alignment", args.length_alignment),
        ("--minimum-max-length", args.minimum_max_length),
        ("--probe-rows", args.probe_rows),
        ("--probe-pool-size", args.probe_pool_size),
    ):
        if value <= 0:
            raise SystemExit(f"error: {label} must be positive")

    try:
        from transformers import AutoConfig, AutoTokenizer
    except ImportError as exc:
        raise SystemExit("error: transformers is required in the veRL training environment") from exc

    tokenizer = AutoTokenizer.from_pretrained(args.model_path, trust_remote_code=True)
    config = AutoConfig.from_pretrained(args.model_path, trust_remote_code=True)
    chat_template = getattr(tokenizer, "chat_template", None)
    if not isinstance(chat_template, str) or not chat_template:
        raise SystemExit("error: tokenizer has no chat template")

    try:
        train_rows, train_schema = load_parquet(args.train_parquet)
        validation_rows, _ = load_parquet(args.validation_parquet)
        analyzed_train = analyze_rows(train_rows, tokenizer, "train")
        analyzed_validation = analyze_rows(validation_rows, tokenizer, "validation")
        analyzed = analyzed_train + analyzed_validation
        report = build_report(
            analyzed,
            model_path=args.model_path,
            model_context_length=detect_model_context_length(config, tokenizer),
            chat_template_sha256=hashlib.sha256(chat_template.encode("utf-8")).hexdigest(),
            max_prompt_tokens=args.max_prompt_tokens,
            max_output_tokens=args.max_output_tokens,
            hard_max_total_tokens=args.hard_max_total_tokens,
            minimum_max_length=args.minimum_max_length,
            length_alignment=args.length_alignment,
        )
        write_json_atomic(report, args.report)
        if not report["violations"] and args.probe_output is not None:
            write_oom_probe(
                analyzed_train,
                train_schema,
                args.probe_output,
                probe_rows=args.probe_rows,
                pool_size=args.probe_pool_size,
            )
    except (FileNotFoundError, RuntimeError, TokenValidationError) as exc:
        raise SystemExit(f"error: {exc}") from exc

    print(json.dumps({key: value for key, value in report.items() if key != "perSample"}, ensure_ascii=False, indent=2))
    if report["violations"]:
        raise SystemExit(
            f"error: {len(report['violations'])} samples exceed token limits; see {args.report}"
        )


if __name__ == "__main__":
    main()
