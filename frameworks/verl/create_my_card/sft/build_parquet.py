#!/usr/bin/env python3
"""Build veRL SFT parquet files from TaskSpec and Design Compact DSL sources."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_SYSTEM_PROMPT = BASE_DIR / "data" / "source" / "system_prompt.md"
DEFAULT_TASKSPEC = BASE_DIR / "data" / "source" / "taskspec.json"
DEFAULT_COMPACT_DSL = BASE_DIR / "data" / "source" / "design_compact_dsl.jsonl"
DEFAULT_OUTPUT_DIR = BASE_DIR / "data" / "parquet"
SCHEMA_VERSION = "create-my-card-sft/v1"


class DataValidationError(ValueError):
    """Raised when source data cannot be converted without ambiguity."""


@dataclass(frozen=True)
class TaskSpecRecord:
    sample_id: str
    task_spec: dict[str, Any]


@dataclass(frozen=True)
class CompactDslRecord:
    sample_id: str
    compact_dsl: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--system-prompt", type=Path, default=DEFAULT_SYSTEM_PROMPT)
    parser.add_argument("--taskspec", type=Path, default=DEFAULT_TASKSPEC)
    parser.add_argument("--compact-dsl", type=Path, default=DEFAULT_COMPACT_DSL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--validation-ratio",
        type=float,
        default=0.05,
        help="Fraction reserved for validation. Use 0 to create an empty validation split.",
    )
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def _require_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise DataValidationError(f"{label} file does not exist: {path}")


def _load_json(path: Path, label: str) -> Any:
    _require_file(path, label)
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise DataValidationError(
            f"{label} is not valid JSON at line {exc.lineno}, column {exc.colno}: {path}"
        ) from exc


def _validate_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DataValidationError(f"{label}.id must be a non-empty string")
    if value != value.strip():
        raise DataValidationError(f"{label}.id must not contain leading or trailing whitespace: {value!r}")
    return value


def load_system_prompt(path: Path) -> str:
    _require_file(path, "system prompt")
    return path.read_text(encoding="utf-8-sig").strip()


def load_taskspec_records(path: Path) -> list[TaskSpecRecord]:
    payload = _load_json(path, "TaskSpec")
    if not isinstance(payload, list):
        raise DataValidationError("TaskSpec root must be a JSON array")

    records: list[TaskSpecRecord] = []
    seen: set[str] = set()
    for index, item in enumerate(payload, start=1):
        label = f"TaskSpec record {index}"
        if not isinstance(item, dict):
            raise DataValidationError(f"{label} must be an object")
        sample_id = _validate_id(item.get("id"), label)
        if sample_id in seen:
            raise DataValidationError(f"duplicate TaskSpec id: {sample_id}")
        task_spec = item.get("taskSpec")
        if not isinstance(task_spec, dict):
            raise DataValidationError(f"{label}.taskSpec must be an object")
        try:
            json.dumps(task_spec, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise DataValidationError(f"{label}.taskSpec is not strict JSON: {exc}") from exc
        seen.add(sample_id)
        records.append(TaskSpecRecord(sample_id=sample_id, task_spec=task_spec))
    return records


def load_compact_dsl_records(path: Path) -> list[CompactDslRecord]:
    _require_file(path, "Design Compact DSL")
    records: list[CompactDslRecord] = []
    seen: set[str] = set()

    with path.open("r", encoding="utf-8-sig") as stream:
        for line_number, raw_line in enumerate(stream, start=1):
            if not raw_line.strip():
                continue
            try:
                item = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise DataValidationError(
                    "Design Compact DSL JSONL is invalid at "
                    f"line {line_number}, column {exc.colno}: {path}"
                ) from exc
            label = f"Design Compact DSL record at line {line_number}"
            if not isinstance(item, dict):
                raise DataValidationError(f"{label} must be an object")
            sample_id = _validate_id(item.get("id"), label)
            if sample_id in seen:
                raise DataValidationError(f"duplicate Design Compact DSL id: {sample_id}")
            compact_dsl = item.get("designCompactDsl")
            if not isinstance(compact_dsl, str) or not compact_dsl.strip():
                raise DataValidationError(f"{label}.designCompactDsl must be a non-empty string")
            compact_dsl = compact_dsl.strip()
            lowered = compact_dsl.lower()
            if "<think>" in lowered or "</think>" in lowered:
                raise DataValidationError(f"{label} must not contain <think> tags")
            if compact_dsl.startswith("```") or compact_dsl.endswith("```"):
                raise DataValidationError(f"{label} must contain raw DSL without Markdown fences")
            seen.add(sample_id)
            records.append(CompactDslRecord(sample_id=sample_id, compact_dsl=compact_dsl))
    return records


def pair_records(
    taskspec_records: Iterable[TaskSpecRecord],
    compact_dsl_records: Iterable[CompactDslRecord],
) -> list[tuple[TaskSpecRecord, CompactDslRecord]]:
    taskspec_records = list(taskspec_records)
    compact_dsl_records = list(compact_dsl_records)
    if not taskspec_records and not compact_dsl_records:
        raise DataValidationError(
            "source data is empty; add matching records to taskspec.json and design_compact_dsl.jsonl"
        )

    taskspec_ids = {record.sample_id for record in taskspec_records}
    compact_by_id = {record.sample_id: record for record in compact_dsl_records}
    compact_ids = set(compact_by_id)
    missing_dsl = sorted(taskspec_ids - compact_ids)
    missing_taskspec = sorted(compact_ids - taskspec_ids)
    if missing_dsl or missing_taskspec:
        details = []
        if missing_dsl:
            details.append(f"missing Design Compact DSL ids: {missing_dsl}")
        if missing_taskspec:
            details.append(f"missing TaskSpec ids: {missing_taskspec}")
        raise DataValidationError("; ".join(details))

    return [(task_record, compact_by_id[task_record.sample_id]) for task_record in taskspec_records]


def canonicalize_taskspec(task_spec: dict[str, Any]) -> str:
    return json.dumps(
        task_spec,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=False,
        allow_nan=False,
    )


def build_row(
    system_prompt: str,
    task_record: TaskSpecRecord,
    compact_record: CompactDslRecord,
) -> dict[str, Any]:
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.extend(
        [
            {"role": "user", "content": canonicalize_taskspec(task_record.task_spec)},
            {"role": "assistant", "content": compact_record.compact_dsl},
        ]
    )
    return {
        "id": task_record.sample_id,
        "messages": messages,
        "enable_thinking": False,
    }


def split_rows(
    rows: list[dict[str, Any]], validation_ratio: float, seed: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not 0 <= validation_ratio < 1:
        raise DataValidationError("validation ratio must be in the range [0, 1)")
    if validation_ratio == 0:
        return rows, []
    if len(rows) < 2:
        raise DataValidationError("at least two samples are required when validation ratio is greater than 0")

    validation_count = max(1, round(len(rows) * validation_ratio))
    validation_count = min(validation_count, len(rows) - 1)
    shuffled_ids = [row["id"] for row in rows]
    random.Random(seed).shuffle(shuffled_ids)
    validation_ids = set(shuffled_ids[:validation_count])
    train_rows = [row for row in rows if row["id"] not in validation_ids]
    validation_rows = [row for row in rows if row["id"] in validation_ids]
    return train_rows, validation_rows


def _parquet_schema():
    try:
        import pyarrow as pa
    except ImportError as exc:
        raise RuntimeError(
            "pyarrow is required to build parquet files; install requirements.txt in the training environment"
        ) from exc

    message_type = pa.struct(
        [
            pa.field("role", pa.string(), nullable=False),
            pa.field("content", pa.string(), nullable=False),
        ]
    )
    return pa.schema(
        [
            pa.field("id", pa.string(), nullable=False),
            pa.field("messages", pa.list_(message_type), nullable=False),
            pa.field("enable_thinking", pa.bool_(), nullable=False),
        ]
    )


def write_parquet(rows: list[dict[str, Any]], output_path: Path) -> None:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError(
            "pyarrow is required to build parquet files; install requirements.txt in the training environment"
        ) from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows, schema=_parquet_schema())
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            dir=output_path.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        pq.write_table(table, temporary_path, compression="zstd")
        if pq.read_metadata(temporary_path).num_rows != len(rows):
            raise RuntimeError(f"parquet row-count verification failed: {output_path}")
        os.replace(temporary_path, output_path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_atomic(payload: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            dir=output_path.parent,
            delete=False,
        ) as temporary:
            temporary.write(serialized)
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, output_path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def build_dataset(
    *,
    system_prompt_path: Path,
    taskspec_path: Path,
    compact_dsl_path: Path,
    output_dir: Path,
    validation_ratio: float,
    seed: int,
) -> dict[str, Any]:
    system_prompt = load_system_prompt(system_prompt_path)
    pairs = pair_records(
        load_taskspec_records(taskspec_path),
        load_compact_dsl_records(compact_dsl_path),
    )
    rows = [build_row(system_prompt, task_record, compact_record) for task_record, compact_record in pairs]
    train_rows, validation_rows = split_rows(rows, validation_ratio, seed)

    train_path = output_dir / "train.parquet"
    validation_path = output_dir / "validation.parquet"
    write_parquet(train_rows, train_path)
    write_parquet(validation_rows, validation_path)

    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "thinkingMode": False,
        "systemPromptIncluded": bool(system_prompt),
        "validationRatio": validation_ratio,
        "seed": seed,
        "sources": {
            "systemPrompt": {
                "path": str(system_prompt_path.resolve()),
                "sha256": sha256_file(system_prompt_path),
            },
            "taskSpec": {
                "path": str(taskspec_path.resolve()),
                "sha256": sha256_file(taskspec_path),
            },
            "designCompactDsl": {
                "path": str(compact_dsl_path.resolve()),
                "sha256": sha256_file(compact_dsl_path),
            },
        },
        "splits": {
            "train": {
                "count": len(train_rows),
                "ids": [row["id"] for row in train_rows],
                "sha256": sha256_file(train_path),
            },
            "validation": {
                "count": len(validation_rows),
                "ids": [row["id"] for row in validation_rows],
                "sha256": sha256_file(validation_path),
            },
        },
        "parquetColumns": ["id", "messages", "enable_thinking"],
    }
    write_json_atomic(manifest, output_dir / "manifest.json")
    return manifest


def main() -> None:
    args = parse_args()
    try:
        manifest = build_dataset(
            system_prompt_path=args.system_prompt,
            taskspec_path=args.taskspec,
            compact_dsl_path=args.compact_dsl,
            output_dir=args.output_dir,
            validation_ratio=args.validation_ratio,
            seed=args.seed,
        )
    except (DataValidationError, RuntimeError) as exc:
        raise SystemExit(f"error: {exc}") from exc

    print(f"Saved veRL SFT parquet files to: {args.output_dir.resolve()}")
    print(json.dumps(manifest["splits"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
