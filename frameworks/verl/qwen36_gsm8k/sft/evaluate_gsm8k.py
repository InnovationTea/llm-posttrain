#!/usr/bin/env python3
"""Run deterministic evaluation for the Qwen3.6 GSM8K SFT workflow."""

from __future__ import annotations

import argparse
import json
import os
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import mean
from typing import Any


NUMBER_PATTERN = re.compile(r"-?(?:\d[\d,]*(?:\.\d+)?|\.\d+)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", required=True)
    parser.add_argument(
        "--tokenizer-path",
        help="Tokenizer path; defaults to --model-path.",
    )
    parser.add_argument(
        "--data-file",
        type=Path,
        default=Path("/mnt/data/gsm8k_sft/test.parquet"),
    )
    parser.add_argument("--output-file", type=Path, required=True)
    parser.add_argument(
        "--tensor-parallel-size",
        type=int,
        default=8,
        help="vLLM tensor parallel size; defaults to 8 for Qwen3.6-27B's 24 attention heads.",
    )
    parser.add_argument("--max-model-len", type=int, default=4096)
    parser.add_argument("--max-new-tokens", type=int, default=1024)
    parser.add_argument(
        "--enable-thinking",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Enable the model's internal thinking mode; disabled by default for visible GSM8K solutions.",
    )
    parser.add_argument("--gpu-memory-utilization", type=float, default=0.9)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--limit", type=int, help="Evaluate only the first N rows.")
    return parser.parse_args()


def normalize_number(raw: str) -> str | None:
    try:
        value = Decimal(raw.replace(",", ""))
    except InvalidOperation:
        return None
    if not value.is_finite():
        return None
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def extract_final_answer(text: str) -> str | None:
    candidate = text.rsplit("####", 1)[-1] if "####" in text else text
    matches = NUMBER_PATTERN.findall(candidate)
    return normalize_number(matches[-1]) if matches else None


def get_tensor_parallel_size(requested: int, model_path: str) -> int:
    import torch
    import torch_npu  # noqa: F401  # registers torch.npu
    from transformers import AutoConfig

    count = torch.npu.device_count()
    if count < 1:
        raise RuntimeError("No visible NPU devices")
    if requested < 1:
        raise ValueError("--tensor-parallel-size must be a positive integer")
    if requested > count:
        raise ValueError(
            f"--tensor-parallel-size={requested} exceeds {count} visible NPU devices"
        )

    config = AutoConfig.from_pretrained(model_path, trust_remote_code=True)
    text_config = getattr(config, "text_config", config)
    attention_heads = getattr(text_config, "num_attention_heads", None)
    if attention_heads is not None and attention_heads % requested != 0:
        raise ValueError(
            f"Model has {attention_heads} attention heads, which is not divisible by "
            f"--tensor-parallel-size={requested}"
        )
    return requested


def read_examples(data_file: Path, limit: int | None) -> list[dict[str, str]]:
    from datasets import load_dataset

    if not data_file.is_file():
        raise FileNotFoundError(f"Missing evaluation data: {data_file}")
    dataset = load_dataset(
        "parquet",
        data_files=str(data_file),
        split="train",
    )
    if limit is not None:
        if limit < 1:
            raise ValueError("--limit must be a positive integer")
        dataset = dataset.select(range(min(limit, len(dataset))))

    examples = []
    for index, row in enumerate(dataset):
        messages = row.get("messages")
        if not isinstance(messages, list) or len(messages) != 2:
            raise ValueError(f"Row {index}: expected exactly two messages")
        user, assistant = messages
        if user.get("role") != "user" or assistant.get("role") != "assistant":
            raise ValueError(f"Row {index}: expected user then assistant")
        reference = extract_final_answer(assistant["content"])
        if reference is None or "####" not in assistant["content"]:
            raise ValueError(f"Row {index}: invalid GSM8K reference answer")
        examples.append(
            {
                "question": user["content"],
                "reference_response": assistant["content"],
                "reference": reference,
            }
        )
    if not examples:
        raise ValueError("Evaluation dataset is empty")
    return examples


def summary_path(output_file: Path) -> Path:
    if output_file.suffix:
        return output_file.with_suffix(".summary.json")
    return Path(f"{output_file}.summary.json")


def main() -> None:
    args = parse_args()
    if args.max_model_len <= args.max_new_tokens:
        raise ValueError("--max-model-len must be larger than --max-new-tokens")
    if not 0 < args.gpu_memory_utilization <= 1:
        raise ValueError("--gpu-memory-utilization must be in (0, 1]")

    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("GLOO_SOCKET_IFNAME", "lo")
    os.environ.setdefault("VLLM_WORKER_MULTIPROC_METHOD", "spawn")

    from transformers import AutoTokenizer

    examples = read_examples(args.data_file, args.limit)
    tokenizer_path = args.tokenizer_path or args.model_path
    tokenizer = AutoTokenizer.from_pretrained(
        tokenizer_path,
        trust_remote_code=True,
    )
    prompts = [
        tokenizer.apply_chat_template(
            [{"role": "user", "content": example["question"]}],
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=args.enable_thinking,
        )
        for example in examples
    ]
    prompt_token_lengths = [
        len(input_ids)
        for input_ids in tokenizer(prompts, add_special_tokens=False)["input_ids"]
    ]
    max_prompt_tokens = max(prompt_token_lengths)
    if max_prompt_tokens + args.max_new_tokens > args.max_model_len:
        raise ValueError(
            f"Longest prompt ({max_prompt_tokens}) + --max-new-tokens "
            f"({args.max_new_tokens}) exceeds --max-model-len ({args.max_model_len})"
        )

    tensor_parallel_size = get_tensor_parallel_size(
        args.tensor_parallel_size,
        args.model_path,
    )

    from vllm import LLM, SamplingParams

    llm = LLM(
        model=args.model_path,
        tokenizer=tokenizer_path,
        tensor_parallel_size=tensor_parallel_size,
        distributed_executor_backend="mp",
        dtype="bfloat16",
        max_model_len=args.max_model_len,
        gpu_memory_utilization=args.gpu_memory_utilization,
        seed=args.seed,
    )
    sampling_params = SamplingParams(
        temperature=0.0,
        max_tokens=args.max_new_tokens,
    )
    outputs = llm.generate(prompts, sampling_params, use_tqdm=True)
    if len(outputs) != len(examples):
        raise RuntimeError("vLLM returned an unexpected number of outputs")

    results: list[dict[str, Any]] = []
    for index, (example, output) in enumerate(zip(examples, outputs, strict=True)):
        completion = output.outputs[0]
        prediction = extract_final_answer(completion.text)
        format_valid = "####" in completion.text and prediction is not None
        correct = prediction == example["reference"]
        results.append(
            {
                "index": index,
                **example,
                "prediction": prediction,
                "correct": correct,
                "format_valid": format_valid,
                "strict_correct": correct and format_valid,
                "completion_tokens": len(completion.token_ids),
                "finish_reason": completion.finish_reason,
                "truncated": completion.finish_reason == "length",
                "generation": completion.text,
            }
        )

    total = len(results)
    summary = {
        "model_path": args.model_path,
        "tokenizer_path": tokenizer_path,
        "data_file": str(args.data_file),
        "total": total,
        "correct": sum(row["correct"] for row in results),
        "accuracy": mean(row["correct"] for row in results),
        "strict_accuracy": mean(row["strict_correct"] for row in results),
        "format_valid_rate": mean(row["format_valid"] for row in results),
        "average_completion_tokens": mean(row["completion_tokens"] for row in results),
        "truncated": sum(row["truncated"] for row in results),
        "truncation_rate": mean(row["truncated"] for row in results),
        "tensor_parallel_size": tensor_parallel_size,
        "max_model_len": args.max_model_len,
        "max_new_tokens": args.max_new_tokens,
        "max_prompt_tokens": max_prompt_tokens,
        "enable_thinking": args.enable_thinking,
        "seed": args.seed,
    }

    args.output_file.parent.mkdir(parents=True, exist_ok=True)
    with args.output_file.open("w", encoding="utf-8") as output_stream:
        for row in results:
            output_stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    summary_path(args.output_file).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Per-example results: {args.output_file}")
    print(f"Summary: {summary_path(args.output_file)}")


if __name__ == "__main__":
    main()
