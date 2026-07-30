# Qwen3.6-27B Ascend GRPO Smoke Test

This guide runs the Qwen3.6-27B text-only GRPO smoke test on one Ascend A3
node with 16 Ascend 910C NPUs. It verifies the `verl` FSDP2, vLLM-Ascend,
HCCL, GSM8K rule-reward, actor, and reference-policy path. It does not test
image or video inputs.

## Prerequisites

Run the commands inside the Ascend `verl` Docker container.

- The model directory is mounted at `/mnt/model/Qwen3.6-27B`.
- `/mnt/data` is writable. The scripts store parquet data, Ray temporary
  files, logs, and checkpoints there.
- The container has a `verl` source checkout containing
  `examples/data_preprocess/gsm8k.py`. Set `VERL_HOME` to that checkout.
- The container can reach Hugging Face while preparing GSM8K. The preparation
  step is skipped when both parquet files already exist.

Check the environment before preparing data:

```bash
npu-smi info
python3 -c 'import torch_npu, verl; print(torch_npu.__file__); print(verl.__file__)'
ls -ld /mnt/model/Qwen3.6-27B /mnt/data
```

If the source checkout location is unknown, locate the shipped preprocessor:

```bash
find /workspace /root -path '*/examples/data_preprocess/gsm8k.py' -print 2>/dev/null
```

In the commands below, replace `/workspace/verl` with the directory that
contains the `examples` and `verl` directories.

## Prepare GSM8K

From the mounted post-training repository (`/workspace` in the default
container launcher):

```bash
cd /workspace

VERL_HOME=/workspace/verl \
  bash frameworks/verl/prepare_gsm8k_smoke.sh
```

The script downloads and converts GSM8K into:

```text
/mnt/data/verl-smoke/gsm8k/train.parquet
/mnt/data/verl-smoke/gsm8k/test.parquet
```

To use a different persistent location, set `DATA_DIR`:

```bash
VERL_HOME=/workspace/verl \
DATA_DIR=/mnt/data/my-gsm8k \
  bash frameworks/verl/prepare_gsm8k_smoke.sh
```

## Run the Smoke Test

Run the default two-step test after the parquet files are present:

```bash
cd /workspace
bash frameworks/verl/run_qwen3_6_27b_grpo_smoke.sh
```

The default configuration is:

| Setting | Value |
| --- | --- |
| Model | `/mnt/model/Qwen3.6-27B` |
| Devices | 16 Ascend NPUs on one node |
| Training backend | FSDP2, size 16 |
| Rollout backend | vLLM-Ascend, tensor parallel size 4 |
| Algorithm | GRPO with two rollouts per prompt |
| Global prompt batch | 8 |
| Sequence lengths | 512 prompt tokens and 512 response tokens |
| Training steps | 2 |

Logs, Ray temporary files, and checkpoints are written to:

```text
/mnt/data/verl-smoke/logs/verl-qwen36-smoke/qwen3_6-27b-grpo-gsm8k/
/mnt/data/verl-smoke/checkpoints/verl-qwen36-smoke/qwen3_6-27b-grpo-gsm8k/
/mnt/data/verl-smoke/ray/
```

The script always uses `trainer.resume_mode=disable`, so a smoke test does
not resume an earlier checkpoint.

## Common Overrides

All machine-specific values are environment variables. For example, use a
different data location and retain only one training step:

```bash
DATA_DIR=/mnt/data/my-gsm8k \
OUTPUT_DIR=/mnt/data/qwen36-smoke-output \
TOTAL_TRAINING_STEPS=1 \
  bash frameworks/verl/run_qwen3_6_27b_grpo_smoke.sh
```

For a lower-memory first attempt, lower rollout memory utilization and reduce
the response length:

```bash
ROLLOUT_GPU_MEM_UTIL=0.30 \
MAX_RESPONSE_LENGTH=256 \
  bash frameworks/verl/run_qwen3_6_27b_grpo_smoke.sh
```

`PPO_MINI_BATCH_SIZE` must divide `TRAIN_BATCH_SIZE * ROLLOUT_N`, and
`ROLLOUT_N` must be at least 2 for GRPO. The launcher validates both before
starting Ray.

## Failure Checks

- `Model directory not found`: set `MODEL_PATH` to the mounted Qwen3.6-27B
  directory.
- `GSM8K parquet files not found`: run the preparation script, or set
  `TRAIN_FILE` and `TEST_FILE` to existing parquet files.
- `torch_npu is unavailable`: enter the Ascend `verl` container and verify
  that the NPU devices were passed through Docker.
- HCCL or vLLM initialization failure: preserve the timestamped log under
  `LOG_DIR`; do not increase batch or token limits until the two-step run
  initializes successfully.

The test uses text-only GSM8K samples intentionally. A multimodal test needs
a dataset with image fields and `<image>` placeholders, such as Geometry3K
or OpenR1MM, and should be treated as a separate validation step.
