#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(cd -- "${SCRIPT_DIR}/../../.." && pwd)

MODEL_PATH=${MODEL_PATH:-/mnt/model/Qwen3.6-27B}
DATA_DIR=${DATA_DIR:-/mnt/data/gsm8k_sft}

DRY_RUN=${DRY_RUN:-1}
if [[ -z "${SAVE_PATH:-}" ]]; then
  if [[ "${DRY_RUN}" == "1" ]]; then
    SAVE_PATH=/mnt/data/checkpoints/qwen36-27b-gsm8k-sft-dry-run
  else
    SAVE_PATH=/mnt/data/checkpoints/qwen36-27b-gsm8k-sft
  fi
fi
NPROC_PER_NODE=${NPROC_PER_NODE:-}
MASTER_ADDR=${MASTER_ADDR:-127.0.0.1}
MASTER_PORT=${MASTER_PORT:-29500}
TRAIN_BATCH_SIZE=${TRAIN_BATCH_SIZE:-}
MICRO_BATCH_SIZE_PER_GPU=${MICRO_BATCH_SIZE_PER_GPU:-1}
MAX_LENGTH=${MAX_LENGTH:-2048}
MAX_TOKEN_LEN_PER_GPU=${MAX_TOKEN_LEN_PER_GPU:-${MAX_LENGTH}}
LEARNING_RATE=${LEARNING_RATE:-1e-6}
TOTAL_EPOCHS=${TOTAL_EPOCHS:-1}
DRY_RUN_STEPS=${DRY_RUN_STEPS:-2}
SP_SIZE=${SP_SIZE:-1}
PARAM_OFFLOAD=${PARAM_OFFLOAD:-false}
OPTIMIZER_OFFLOAD=${OPTIMIZER_OFFLOAD:-false}
ACTIVATION_OFFLOAD=${ACTIVATION_OFFLOAD:-false}
USE_TORCH_COMPILE=${USE_TORCH_COMPILE:-false}
LOGGER=${LOGGER:-console}
MAX_CKPT_TO_KEEP=${MAX_CKPT_TO_KEEP:-2}
RESUME_MODE=${RESUME_MODE:-disable}
LOG_DIR=${LOG_DIR:-/mnt/data/logs/qwen36-27b-gsm8k-sft}
LOG_FILE=${LOG_FILE:-}

export HYDRA_FULL_ERROR=1
export TOKENIZERS_PARALLELISM=false
export PYTORCH_NPU_ALLOC_CONF=${PYTORCH_NPU_ALLOC_CONF:-expandable_segments:True}
export PYTHONUNBUFFERED=1

if [[ "${DRY_RUN}" == "1" ]]; then
  run_mode=dry-run
else
  run_mode=train
fi
if [[ -z "${LOG_FILE}" ]]; then
  LOG_FILE="${LOG_DIR}/${run_mode}-$(date +%Y%m%d-%H%M%S)-$$.log"
fi
mkdir -p -- "$(dirname -- "${LOG_FILE}")"
exec > >(tee -a "${LOG_FILE}") 2>&1

echo "Run started at $(date '+%Y-%m-%d %H:%M:%S %z')"
echo "Persistent log: ${LOG_FILE}"

if [[ ! -d "${MODEL_PATH}" ]]; then
  echo "Error: MODEL_PATH does not exist: ${MODEL_PATH}" >&2
  exit 1
fi
if [[ ! -f "${DATA_DIR}/train.parquet" || ! -f "${DATA_DIR}/validation.parquet" ]]; then
  echo "Error: expected train.parquet and validation.parquet in ${DATA_DIR}" >&2
  exit 1
fi

case "${DRY_RUN}" in
  0|1) ;;
  *)
    echo "Error: DRY_RUN must be '0' or '1', got: ${DRY_RUN}" >&2
    exit 1
    ;;
esac
if [[ "${DRY_RUN}" == "0" ]]; then
  case "${RESUME_MODE}" in
    disable|auto) ;;
    *)
      echo "Error: RESUME_MODE must be 'disable' or 'auto', got: ${RESUME_MODE}" >&2
      exit 1
      ;;
  esac
  if [[ "${RESUME_MODE}" == "disable" ]] && \
    compgen -G "${SAVE_PATH}/global_step_*" >/dev/null; then
    echo "Error: ${SAVE_PATH} already contains checkpoints." >&2
    echo "Use a new SAVE_PATH, or set RESUME_MODE=auto to continue that run." >&2
    exit 1
  fi
  if [[ "${RESUME_MODE}" == "auto" ]] && \
    [[ ! -f "${SAVE_PATH}/latest_checkpointed_iteration.txt" ]]; then
    echo "Error: RESUME_MODE=auto requires a checkpoint tracker in ${SAVE_PATH}." >&2
    exit 1
  fi
fi

if [[ -z "${NPROC_PER_NODE}" ]]; then
  NPROC_PER_NODE=$(python3 - <<'PY'
import torch
import torch_npu  # noqa: F401
print(torch.npu.device_count())
PY
  )
fi
if ! [[ "${NPROC_PER_NODE}" =~ ^[1-9][0-9]*$ ]]; then
  echo "Error: NPROC_PER_NODE must be a positive integer, got: ${NPROC_PER_NODE}" >&2
  exit 1
fi
if ! [[ "${SP_SIZE}" =~ ^[1-9][0-9]*$ ]]; then
  echo "Error: SP_SIZE must be a positive integer, got: ${SP_SIZE}" >&2
  exit 1
fi
if ((NPROC_PER_NODE % SP_SIZE != 0)); then
  echo "Error: NPROC_PER_NODE=${NPROC_PER_NODE} must be divisible by SP_SIZE=${SP_SIZE}" >&2
  exit 1
fi
if [[ -z "${TRAIN_BATCH_SIZE}" ]]; then
  TRAIN_BATCH_SIZE=$((NPROC_PER_NODE * 2))
fi
DP_SIZE=$((NPROC_PER_NODE / SP_SIZE))
if ! [[ "${TRAIN_BATCH_SIZE}" =~ ^[1-9][0-9]*$ ]]; then
  echo "Error: TRAIN_BATCH_SIZE must be a positive integer, got: ${TRAIN_BATCH_SIZE}" >&2
  exit 1
fi
if ((TRAIN_BATCH_SIZE % DP_SIZE != 0)); then
  echo "Error: global batch ${TRAIN_BATCH_SIZE} is not divisible by DP size ${DP_SIZE}" >&2
  exit 1
fi
LOCAL_BATCH_SIZE=$((TRAIN_BATCH_SIZE / DP_SIZE))
if ! [[ "${MICRO_BATCH_SIZE_PER_GPU}" =~ ^[1-9][0-9]*$ ]]; then
  echo "Error: MICRO_BATCH_SIZE_PER_GPU must be a positive integer, got: ${MICRO_BATCH_SIZE_PER_GPU}" >&2
  exit 1
fi
if ((LOCAL_BATCH_SIZE % MICRO_BATCH_SIZE_PER_GPU != 0)); then
  echo "Error: local batch ${LOCAL_BATCH_SIZE} is not divisible by micro batch ${MICRO_BATCH_SIZE_PER_GPU}" >&2
  exit 1
fi

extra_args=()
if [[ "${DRY_RUN}" == "1" ]]; then
  if ! [[ "${DRY_RUN_STEPS}" =~ ^[1-9][0-9]*$ ]]; then
    echo "Error: DRY_RUN_STEPS must be a positive integer, got: ${DRY_RUN_STEPS}" >&2
    exit 1
  fi
  dry_run_train_samples=$((TRAIN_BATCH_SIZE * DRY_RUN_STEPS))
  extra_args+=(
    "data.train_max_samples=${dry_run_train_samples}"
    "data.val_max_samples=${TRAIN_BATCH_SIZE}"
    trainer.save_freq=-1
    trainer.test_freq=-1
    trainer.resume_mode=disable
    "trainer.total_training_steps=${DRY_RUN_STEPS}"
    'checkpoint.save_contents=["model","extra"]'
  )
else
  extra_args+=(
    trainer.save_freq=after_each_epoch
    trainer.test_freq=after_each_epoch
    "trainer.max_ckpt_to_keep=${MAX_CKPT_TO_KEEP}"
    "trainer.resume_mode=${RESUME_MODE}"
  )
fi

case "${LOGGER}" in
  console)
    logger_config='["console"]'
    ;;
  wandb)
    logger_config='["console","wandb"]'
    ;;
  *)
    echo "Error: LOGGER must be 'console' or 'wandb', got: ${LOGGER}" >&2
    exit 1
    ;;
esac

echo "============================================================"
echo "Qwen3.6-27B GSM8K full-parameter SFT"
echo "Project root:          ${PROJECT_ROOT}"
echo "Model:                 ${MODEL_PATH}"
echo "Data:                  ${DATA_DIR}"
echo "Checkpoint:            ${SAVE_PATH}"
echo "Visible NPU processes: ${NPROC_PER_NODE}"
echo "Rendezvous:            ${MASTER_ADDR}:${MASTER_PORT}"
echo "SP / DP size:          ${SP_SIZE} / ${DP_SIZE}"
echo "Global batch size:      ${TRAIN_BATCH_SIZE}"
echo "Local batch / DP rank:  ${LOCAL_BATCH_SIZE}"
echo "Micro batch / NPU:      ${MICRO_BATCH_SIZE_PER_GPU}"
echo "Max length / token cap:  ${MAX_LENGTH} / ${MAX_TOKEN_LEN_PER_GPU}"
echo "Epochs / learning rate: ${TOTAL_EPOCHS} / ${LEARNING_RATE}"
if [[ "${DRY_RUN}" == "1" ]]; then
  echo "Mode / optimizer steps: dry-run / ${DRY_RUN_STEPS}"
else
  echo "Mode / resume:          train / ${RESUME_MODE}"
fi
echo "============================================================"

cd "${PROJECT_ROOT}"

torchrun \
  --nnodes=1 \
  --node_rank=0 \
  --nproc_per_node="${NPROC_PER_NODE}" \
  --master_addr="${MASTER_ADDR}" \
  --master_port="${MASTER_PORT}" \
  -m verl.trainer.sft_trainer \
  "data.train_files=${DATA_DIR}/train.parquet" \
  "data.val_files=${DATA_DIR}/validation.parquet" \
  "data.train_batch_size=${TRAIN_BATCH_SIZE}" \
  "data.micro_batch_size_per_gpu=${MICRO_BATCH_SIZE_PER_GPU}" \
  "data.max_length=${MAX_LENGTH}" \
  "data.max_token_len_per_gpu=${MAX_TOKEN_LEN_PER_GPU}" \
  data.use_dynamic_bsz=true \
  data.messages_key=messages \
  data.enable_thinking_default=null \
  data.pad_mode=no_padding \
  data.truncation=error \
  data.ignore_input_ids_mismatch=false \
  data.num_workers=2 \
  model=hf_model \
  "model.path=${MODEL_PATH}" \
  model.trust_remote_code=true \
  model.enable_gradient_checkpointing=true \
  "model.enable_activation_offload=${ACTIVATION_OFFLOAD}" \
  model.use_remove_padding=true \
  model.use_fused_kernels=false \
  model.lora_rank=0 \
  engine=fsdp \
  engine.strategy=fsdp \
  engine.dtype=bfloat16 \
  engine.model_dtype=fp32 \
  engine.reshard_after_forward=true \
  "engine.ulysses_sequence_parallel_size=${SP_SIZE}" \
  "engine.param_offload=${PARAM_OFFLOAD}" \
  "engine.optimizer_offload=${OPTIMIZER_OFFLOAD}" \
  "engine.use_torch_compile=${USE_TORCH_COMPILE}" \
  optim=fsdp \
  "optim.lr=${LEARNING_RATE}" \
  optim.lr_scheduler_type=cosine \
  optim.lr_warmup_steps_ratio=0.03 \
  optim.weight_decay=0.01 \
  'optim.betas=[0.9,0.95]' \
  optim.clip_grad=1.0 \
  "trainer.default_local_dir=${SAVE_PATH}" \
  trainer.project_name=qwen36-gsm8k-sft \
  trainer.experiment_name=qwen36-27b-full-sft \
  "trainer.logger=${logger_config}" \
  "trainer.total_epochs=${TOTAL_EPOCHS}" \
  trainer.device=npu \
  trainer.nnodes=1 \
  "trainer.n_gpus_per_node=${NPROC_PER_NODE}" \
  "${extra_args[@]}" \
  "$@"
