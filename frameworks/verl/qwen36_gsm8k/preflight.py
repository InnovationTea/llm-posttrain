#!/usr/bin/env python3
"""Validate Ascend, Qwen3.6 metadata, chat template, and optional SFT data."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from statistics import median
from typing import Any


REQUIRED_PACKAGES = ("torch", "torch-npu", "transformers", "verl")
OPTIONAL_PACKAGES = ("vllm", "vllm-ascend")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument(
        "--sample-size",
        type=int,
        default=-1,
        help="Maximum rows checked per split; -1 checks every row.",
    )
    parser.add_argument(
        "--max-length",
        type=int,
        default=2048,
        help="Maximum sequence length passed to veRL's SFT dataset validation.",
    )
    return parser.parse_args()


def package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "not installed"


def load_tokenizer_and_processor(model_path: Path) -> tuple[Any, Any | None, str]:
    from transformers import AutoProcessor, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
    try:
        processor = AutoProcessor.from_pretrained(model_path, trust_remote_code=True)
    except (ValueError, TypeError, OSError, ImportError):
        return tokenizer, None, "AutoTokenizer"
    return tokenizer, processor, "AutoProcessor"


def normalize_input_ids(tokenized: Any) -> list[int]:
    if isinstance(tokenized, Mapping):
        tokenized = tokenized.get("input_ids")
    if hasattr(tokenized, "tolist"):
        tokenized = tokenized.tolist()
    if tokenized and isinstance(tokenized[0], list):
        tokenized = tokenized[0]
    if not isinstance(tokenized, list):
        raise TypeError(f"Unexpected chat-template output: {type(tokenized).__name__}")
    return tokenized


def apply_chat_template(
    tokenizer: Any,
    messages: list[dict[str, str]],
) -> list[int]:
    tokenized = tokenizer.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=False,
    )
    return normalize_input_ids(tokenized)


def apply_evaluation_prompt(
    tokenizer: Any,
    user_message: dict[str, str],
) -> list[int]:
    tokenized = tokenizer.apply_chat_template(
        [user_message],
        tokenize=True,
        add_generation_prompt=True,
        enable_thinking=False,
    )
    return normalize_input_ids(tokenized)


def validate_messages(messages: Any, row_index: int) -> None:
    if not isinstance(messages, list) or len(messages) != 2:
        raise ValueError(f"Row {row_index}: messages must contain exactly user and assistant turns")
    expected_roles = ("user", "assistant")
    for turn, expected_role in zip(messages, expected_roles, strict=True):
        if not isinstance(turn, dict):
            raise TypeError(f"Row {row_index}: each message must be a mapping")
        if turn.get("role") != expected_role:
            raise ValueError(
                f"Row {row_index}: expected role {expected_role!r}, got {turn.get('role')!r}"
            )
        if not isinstance(turn.get("content"), str) or not turn["content"].strip():
            raise ValueError(f"Row {row_index}: {expected_role} content is empty")
    if "####" not in messages[1]["content"]:
        raise ValueError(f"Row {row_index}: assistant answer does not contain GSM8K '####' marker")


def percentile(sorted_values: list[int], quantile: float) -> int:
    if not sorted_values:
        raise ValueError("Cannot calculate percentile for an empty list")
    index = round((len(sorted_values) - 1) * quantile)
    return sorted_values[index]


def validate_dataset(
    data_dir: Path,
    tokenizer: Any,
    processor: Any | None,
    sample_size: int,
    max_length: int,
) -> dict[str, Any]:
    from datasets import load_dataset
    from omegaconf import OmegaConf
    from verl.utils.dataset.multiturn_sft_dataset import MultiTurnSFTDataset

    split_paths = {
        split: data_dir / f"{split}.parquet"
        for split in ("train", "validation", "test")
    }
    for path in split_paths.values():
        if not path.is_file():
            raise FileNotFoundError(f"Missing SFT dataset file: {path}")

    dataset = load_dataset(
        "parquet",
        data_files={split: str(path) for split, path in split_paths.items()},
    )
    data_config = OmegaConf.create(
        {
            "messages_key": "messages",
            "tools_key": "tools",
            "enable_thinking_key": "enable_thinking",
            "enable_thinking_default": None,
            "apply_chat_template_kwargs": {},
            "pad_mode": "no_padding",
            "max_length": max_length,
            "truncation": "error",
            "ignore_input_ids_mismatch": False,
            "shuffle": False,
        }
    )

    report: dict[str, Any] = {}
    for split, parquet_path in split_paths.items():
        split_dataset = dataset[split]
        if "messages" not in split_dataset.column_names:
            raise ValueError(f"{split} parquet must contain a top-level 'messages' column")
        if len(split_dataset) == 0:
            raise ValueError(f"{split} parquet is empty")

        checked_rows = (
            len(split_dataset) if sample_size == -1 else min(sample_size, len(split_dataset))
        )
        for index, row in enumerate(split_dataset.select(range(checked_rows))):
            validate_messages(row["messages"], index)

        trainer_dataset = MultiTurnSFTDataset(
            parquet_files=str(parquet_path),
            tokenizer=tokenizer,
            processor=processor,
            config=data_config,
            max_samples=checked_rows,
        )

        lengths: list[int] = []
        for index in range(len(trainer_dataset)):
            try:
                item = trainer_dataset[index]
            except Exception as error:
                raise RuntimeError(f"{split} row {index} failed veRL SFT validation") from error
            sequence_length = int(item["input_ids"].numel())
            assistant_length = int(item["loss_mask"].sum().item())
            if assistant_length <= 0:
                raise ValueError(
                    f"{split} row {index}: assistant loss mask contains no trainable tokens"
                )
            if index == 0:
                evaluation_prompt_ids = apply_evaluation_prompt(
                    tokenizer,
                    split_dataset[index]["messages"][0],
                )
                training_ids = normalize_input_ids(item["input_ids"])
                if training_ids[: len(evaluation_prompt_ids)] != evaluation_prompt_ids:
                    raise ValueError(
                        f"{split}: SFT input IDs do not start with the non-thinking "
                        "evaluation prompt"
                    )
            lengths.append(sequence_length)

        sorted_lengths = sorted(lengths)
        report[split] = {
            "rows": len(split_dataset),
            "checked_rows": checked_rows,
            "evaluation_prompt_prefix_aligned": True,
            "token_length": {
                "min": sorted_lengths[0],
                "median": int(median(sorted_lengths)),
                "p95": percentile(sorted_lengths, 0.95),
                "max": sorted_lengths[-1],
                "longest_row": lengths.index(max(lengths)),
            },
        }
    return report


def main() -> None:
    args = parse_args()
    if args.sample_size == 0 or args.sample_size < -1:
        raise ValueError("--sample-size must be -1 or a positive integer")
    if args.max_length < 1:
        raise ValueError("--max-length must be a positive integer")
    if not args.model_path.is_dir():
        raise FileNotFoundError(f"Model directory does not exist: {args.model_path}")
    if not (args.model_path / "config.json").is_file():
        raise FileNotFoundError(f"Missing model config: {args.model_path / 'config.json'}")
    weight_files = [
        *args.model_path.glob("*.safetensors"),
        *args.model_path.glob("pytorch_model*.bin"),
    ]
    if not weight_files:
        raise FileNotFoundError(f"No Hugging Face model weights found in {args.model_path}")

    import torch
    import torch_npu  # noqa: F401  # registers torch.npu
    from transformers import AutoConfig

    packages = {name: package_version(name) for name in REQUIRED_PACKAGES + OPTIONAL_PACKAGES}
    missing = [name for name in REQUIRED_PACKAGES if packages[name] == "not installed"]
    if missing:
        raise RuntimeError(f"Missing required packages: {', '.join(missing)}")
    if not torch.npu.is_available():
        raise RuntimeError("torch.npu.is_available() is False")
    npu_count = torch.npu.device_count()
    if npu_count < 1:
        raise RuntimeError("No visible Ascend NPU devices")

    config = AutoConfig.from_pretrained(args.model_path, trust_remote_code=True)
    tokenizer, processor, processor_loader = load_tokenizer_and_processor(args.model_path)
    if not getattr(tokenizer, "chat_template", None):
        raise RuntimeError("The model processor/tokenizer has no chat_template")

    smoke_messages = [
        {"role": "user", "content": "What is 1 + 1?"},
        {"role": "assistant", "content": "1 + 1 = 2. #### 2"},
    ]
    smoke_ids = apply_chat_template(tokenizer, smoke_messages)
    if not smoke_ids:
        raise RuntimeError("Chat template produced no input IDs")

    report: dict[str, Any] = {
        "packages": packages,
        "npu": {"available": True, "count": npu_count},
        "model": {
            "path": str(args.model_path),
            "model_type": getattr(config, "model_type", None),
            "architectures": getattr(config, "architectures", None),
            "processor_loader": processor_loader,
            "weight_files": len(weight_files),
            "chat_template_smoke_tokens": len(smoke_ids),
        },
    }
    if args.data_dir:
        report["dataset"] = validate_dataset(
            args.data_dir,
            tokenizer,
            processor,
            args.sample_size,
            args.max_length,
        )

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("\nPreflight passed. The next safe step is a two-step distributed SFT dry run.")


if __name__ == "__main__":
    main()
