# Qwen3.6 Ascend Smoke Test Design

## Goal

Provide a reproducible, single-node GRPO smoke test for `/mnt/model/Qwen3.6-27B` on 16 Ascend 910C 64 GB NPUs in the existing verl container.

## Scope

The smoke test trains for two optimizer steps on GSM8K text data. Qwen3.6 is a visual-language model, but verl accepts samples without media fields and uses its text-only path, so the test intentionally excludes images. This checks model loading, FSDP2, vLLM-Ascend rollout, rule reward, HCCL, and actor/reference weight updates without claiming multimodal coverage.

## Components

- `prepare_gsm8k_smoke.sh` downloads GSM8K with verl's shipped preprocessor and writes its parquet files under `/mnt/data/verl-smoke/gsm8k` by default.
- `run_qwen3_6_27b_grpo_smoke.sh` validates required paths and NPU availability, then launches `verl.trainer.main_ppo` with small fixed limits suitable for a smoke test.
- A Python standard-library test statically checks the scripts expose required safety checks and the expected verl configuration contract. Hardware execution is intentionally not part of local CI.

## Configuration

The launch script defaults to one 16-device NPU node, FSDP size 16, rollout tensor parallelism 4, two samples per prompt, a global train batch size of 8, and a single training epoch capped at two steps. It uses conservative sequence limits (512 prompt and 512 response tokens), bf16-compatible framework defaults, parameter/optimizer offload, and a rollout memory utilization setting of 0.35.

Every host-specific value is environment-overridable: model/data paths, output directories, Ray temporary storage, NPU topology, rollout parallelism, and the trainer limits. Logs and checkpoints go under `/mnt/data/verl-smoke` by default instead of the Git checkout.

## Failure Handling

The scripts fail before launching Ray when the model directory, parquet files, or `torch_npu` are absent. They retain the required Ascend HCCL and Ray visibility environment settings. A startup message makes it explicit that the test only verifies text-mode Qwen3.6, not visual input processing.

## Verification

Local verification runs the static Python test and shell syntax checks. The remote operator first prepares data, then runs the script with `TOTAL_TRAINING_STEPS=2`; successful completion is indicated by two training steps, a saved checkpoint, and a timestamped log without NPU/vLLM errors.
