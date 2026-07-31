#!/usr/bin/env python3
"""Prepare GSM8K chat-style parquet files for the Qwen3.6 veRL SFT workflow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_DATASET = "openai/gsm8k"
DEFAULT_INSTRUCTION = 'Let\'s think step by step and output the final answer after "####".'


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/mnt/data/gsm8k_sft"),
        help="Directory for train, validation, test parquet files and metadata.json.",
    )
    parser.add_argument(
        "--dataset-path",
        default=DEFAULT_DATASET,
        help="Hugging Face dataset name or local GSM8K dataset path.",
    )
    parser.add_argument(
        "--dataset-config",
        default="default",
        help="Dataset configuration passed to datasets.load_dataset.",
    )
    parser.add_argument(
        "--dataset-revision",
        help="Optional Hugging Face dataset revision or commit hash.",
    )
    parser.add_argument(
        "--instruction",
        default=DEFAULT_INSTRUCTION,
        help="Instruction appended to every GSM8K question.",
    )
    parser.add_argument(
        "--validation-ratio",
        type=float,
        default=0.1,
        help="Fraction of the official train split reserved for validation.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Seed used for the train/validation split.",
    )
    return parser.parse_args()


def to_messages(example: dict, instruction: str) -> dict:
    question = example["question"].strip()
    answer = example["answer"].strip()
    return {
        "messages": [
            {"role": "user", "content": f"{question} {instruction}"},
            {"role": "assistant", "content": answer},
        ]
    }


def load_gsm8k(
    dataset_path: str,
    dataset_config: str,
    dataset_revision: str | None = None,
):
    from datasets import load_dataset

    load_kwargs = {"revision": dataset_revision} if dataset_revision else {}
    dataset = load_dataset(dataset_path, dataset_config, **load_kwargs)
    missing_splits = {"train", "test"} - set(dataset.keys())
    if missing_splits:
        raise ValueError(f"Dataset is missing required splits: {sorted(missing_splits)}")
    return dataset


def main() -> None:
    args = parse_args()
    from datasets import DatasetDict

    if not 0 < args.validation_ratio < 1:
        raise ValueError("--validation-ratio must be between 0 and 1")

    args.output_dir.mkdir(parents=True, exist_ok=True)

    dataset = load_gsm8k(
        args.dataset_path,
        args.dataset_config,
        args.dataset_revision,
    )
    train_validation = dataset["train"].train_test_split(
        test_size=args.validation_ratio,
        seed=args.seed,
    )
    source_splits = {
        "train": train_validation["train"],
        "validation": train_validation["test"],
        "test": dataset["test"],
    }

    prepared = DatasetDict()
    for split, source in source_splits.items():
        prepared[split] = source.map(
            lambda example: to_messages(example, args.instruction),
            remove_columns=source.column_names,
            desc=f"Preparing GSM8K {split} for SFT",
        )
        prepared[split].to_parquet(args.output_dir / f"{split}.parquet")

    metadata = {
        "dataset_path": args.dataset_path,
        "dataset_config": args.dataset_config,
        "dataset_revision": args.dataset_revision,
        "instruction": args.instruction,
        "validation_ratio": args.validation_ratio,
        "seed": args.seed,
        "format": {"messages": ["user", "assistant"]},
        "splits": {split: len(prepared[split]) for split in prepared},
        "source_fingerprints": {
            split: getattr(source, "_fingerprint", None)
            for split, source in source_splits.items()
        },
        "prepared_fingerprints": {
            split: getattr(prepared[split], "_fingerprint", None)
            for split in prepared
        },
    }
    (args.output_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Saved SFT data to: {args.output_dir}")
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
