#!/usr/bin/env bash
set -euo pipefail

SCRIPT_PATH=${BASH_SOURCE[0]}
SCRIPT_DIR=$(dirname -- "${SCRIPT_PATH}")
SCRIPT_DIR=$(cd -- "${SCRIPT_DIR}" && pwd)
PROJECT_ROOT=$(cd -- "${SCRIPT_DIR}/../../../.." && pwd)

MODEL_PATH=${MODEL_PATH:-/mnt/model/Qwen3.6-27B}
DATA_DIR=${DATA_DIR:-${SCRIPT_DIR}/data/parquet}
SAVE_PATH=${SAVE_PATH:-/mnt/data/checkpoints/qwen36-27b-create-my-card-sft}
TOKEN_REPORT=${TOKEN_REPORT:-${DATA_DIR}/token_stats.json}
OOM_PROBE_FILE=${OOM_PROBE_FILE:-${DATA_DIR}/oom_probe.parquet}
TRAIN_DEVICE=${TRAIN_DEVICE:-npu}

DRY_RUN=${DRY_RUN:-1}
DRY_RUN_STEPS=${DRY_RUN_STEPS:-2}
RUN_TOKEN_PREFLIGHT=${RUN_TOKEN_PREFLIGHT:-1}
PROBE_ROWS=${PROBE_ROWS:-256}
PROBE_POOL_SIZE=${PROBE_POOL_SIZE:-8}

NPROC_PER_NODE=${NPROC_PER_NODE:-}
MASTER_ADDR=${MASTER_ADDR:-127.0.0.1}
MASTER_PORT=${MASTER_PORT:-29500}
SP_SIZE=${SP_SIZE:-auto}
TRAIN_BATCH_SIZE=${TRAIN_BATCH_SIZE:-}
MICRO_BATCH_SIZE_PER_GPU=${MICRO_BATCH_SIZE_PER_GPU:-1}

MAX_PROMPT_TOKENS=${MAX_PROMPT_TOKENS:-24576}
MAX_OUTPUT_TOKENS=${MAX_OUTPUT_TOKENS:-8192}
HARD_MAX_TOTAL_TOKENS=${HARD_MAX_TOTAL_TOKENS:-32768}
MIN_MAX_LENGTH=${MIN_MAX_LENGTH:-2048}
LENGTH_ALIGNMENT=${LENGTH_ALIGNMENT:-256}
MAX_LENGTH=${MAX_LENGTH:-auto}
MAX_TOKEN_LEN_PER_GPU=${MAX_TOKEN_LEN_PER_GPU:-auto}

LORA_RANK=${LORA_RANK:-0}
LORA_ALPHA=${LORA_ALPHA:-64}
LORA_TARGET_MODULES=${LORA_TARGET_MODULES:-all-linear}
LEARNING_RATE=${LEARNING_RATE:-}
TOTAL_EPOCHS=${TOTAL_EPOCHS:-3}
WEIGHT_DECAY=${WEIGHT_DECAY:-0.01}
WARMUP_RATIO=${WARMUP_RATIO:-0.03}

PARAM_OFFLOAD=${PARAM_OFFLOAD:-false}
OPTIMIZER_OFFLOAD=${OPTIMIZER_OFFLOAD:-false}
ACTIVATION_OFFLOAD=${ACTIVATION_OFFLOAD:-false}
USE_TORCH_COMPILE=${USE_TORCH_COMPILE:-false}
FSDP_STRATEGY=${FSDP_STRATEGY:-fsdp}
RESUME_MODE=${RESUME_MODE:-disable}
LOGGER=${LOGGER:-console}
MAX_CKPT_TO_KEEP=${MAX_CKPT_TO_KEEP:-2}
LOG_DIR=${LOG_DIR:-/mnt/data/logs/qwen36-27b-create-my-card-sft}
PROJECT_NAME=${PROJECT_NAME:-qwen36-create-my-card-sft}
EXPERIMENT_NAME=${EXPERIMENT_NAME:-qwen36-27b-full-sft}

export HYDRA_FULL_ERROR=1
export TOKENIZERS_PARALLELISM=false
export PYTHONUNBUFFERED=1
export PYTORCH_CUDA_ALLOC_CONF=${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}
export PYTORCH_NPU_ALLOC_CONF=${PYTORCH_NPU_ALLOC_CONF:-expandable_segments:True}

fail() {
  echo "Error: $*" >&2
  exit 1
}

is_positive_int() {
  [[ "$1" =~ ^[1-9][0-9]*$ ]]
}

is_nonnegative_int() {
  [[ "$1" =~ ^[0-9]+$ ]]
}

validate_bool() {
  case "$2" in
    true|false) ;;
    *) fail "$1 must be true or false, got: $2" ;;
  esac
}

[[ -d "${MODEL_PATH}" ]] || fail "MODEL_PATH does not exist: ${MODEL_PATH}"
[[ -f "${DATA_DIR}/train.parquet" ]] || fail "missing ${DATA_DIR}/train.parquet"
[[ -f "${DATA_DIR}/validation.parquet" ]] || fail "missing ${DATA_DIR}/validation.parquet"

case "${DRY_RUN}" in 0|1) ;; *) fail "DRY_RUN must be 0 or 1" ;; esac
case "${RUN_TOKEN_PREFLIGHT}" in 0|1) ;; *) fail "RUN_TOKEN_PREFLIGHT must be 0 or 1" ;; esac
case "${TRAIN_DEVICE}" in cuda|npu) ;; *) fail "TRAIN_DEVICE must be cuda or npu" ;; esac
validate_bool PARAM_OFFLOAD "${PARAM_OFFLOAD}"
validate_bool OPTIMIZER_OFFLOAD "${OPTIMIZER_OFFLOAD}"
validate_bool ACTIVATION_OFFLOAD "${ACTIVATION_OFFLOAD}"
validate_bool USE_TORCH_COMPILE "${USE_TORCH_COMPILE}"

for value_name in DRY_RUN_STEPS PROBE_ROWS PROBE_POOL_SIZE MICRO_BATCH_SIZE_PER_GPU \
  MAX_PROMPT_TOKENS MAX_OUTPUT_TOKENS HARD_MAX_TOTAL_TOKENS MIN_MAX_LENGTH LENGTH_ALIGNMENT; do
  value=${!value_name}
  is_positive_int "${value}" || fail "${value_name} must be a positive integer, got: ${value}"
done
is_nonnegative_int "${LORA_RANK}" || fail "LORA_RANK must be a non-negative integer"
is_positive_int "${LORA_ALPHA}" || fail "LORA_ALPHA must be a positive integer"

if [[ -z "${NPROC_PER_NODE}" ]]; then
  NPROC_PER_NODE=$(TRAIN_DEVICE="${TRAIN_DEVICE}" python3 - <<'PY'
import os
import torch

device = os.environ["TRAIN_DEVICE"]
if device == "cuda":
    print(torch.cuda.device_count())
else:
    import torch_npu  # noqa: F401
    print(torch.npu.device_count())
PY
  )
fi
is_positive_int "${NPROC_PER_NODE}" || fail "NPROC_PER_NODE must be a positive integer"

preflight_args=(
  --model-path "${MODEL_PATH}"
  --train-parquet "${DATA_DIR}/train.parquet"
  --validation-parquet "${DATA_DIR}/validation.parquet"
  --report "${TOKEN_REPORT}"
  --max-prompt-tokens "${MAX_PROMPT_TOKENS}"
  --max-output-tokens "${MAX_OUTPUT_TOKENS}"
  --hard-max-total-tokens "${HARD_MAX_TOTAL_TOKENS}"
  --length-alignment "${LENGTH_ALIGNMENT}"
  --minimum-max-length "${MIN_MAX_LENGTH}"
)
if [[ "${DRY_RUN}" == "1" ]]; then
  preflight_args+=(
    --probe-output "${OOM_PROBE_FILE}"
    --probe-rows "${PROBE_ROWS}"
    --probe-pool-size "${PROBE_POOL_SIZE}"
  )
fi

if [[ "${RUN_TOKEN_PREFLIGHT}" == "1" ]]; then
  python3 "${SCRIPT_DIR}/analyze_tokens.py" "${preflight_args[@]}"
else
  [[ -f "${TOKEN_REPORT}" ]] || fail "RUN_TOKEN_PREFLIGHT=0 requires existing ${TOKEN_REPORT}"
fi

read -r OBSERVED_MAX_TOTAL RECOMMENDED_MAX_LENGTH MODEL_CONTEXT_LENGTH < <(
  python3 - "${TOKEN_REPORT}" <<'PY'
import json
import sys

report = json.load(open(sys.argv[1], encoding="utf-8"))
print(
    report["observedMaxTotalTokens"],
    report["recommendedMaxLength"],
    report.get("modelContextLength") or 0,
)
PY
)

if [[ "${MAX_LENGTH}" == "auto" ]]; then
  MAX_LENGTH=${RECOMMENDED_MAX_LENGTH}
else
  is_positive_int "${MAX_LENGTH}" || fail "MAX_LENGTH must be auto or a positive integer"
fi
((MAX_LENGTH >= OBSERVED_MAX_TOTAL)) || fail \
  "MAX_LENGTH=${MAX_LENGTH} is smaller than observed maximum ${OBSERVED_MAX_TOTAL}; truncation is forbidden"
if ((MODEL_CONTEXT_LENGTH > 0 && MAX_LENGTH > MODEL_CONTEXT_LENGTH)); then
  fail "MAX_LENGTH=${MAX_LENGTH} exceeds model context ${MODEL_CONTEXT_LENGTH}"
fi

if [[ "${SP_SIZE}" == "auto" ]]; then
  desired_sp=1
  if ((MAX_LENGTH > 16384)); then
    desired_sp=4
  elif ((MAX_LENGTH > 8192)); then
    desired_sp=2
  fi
  SP_SIZE=1
  for candidate in 4 2 1; do
    if ((candidate <= desired_sp && candidate <= NPROC_PER_NODE && NPROC_PER_NODE % candidate == 0)); then
      SP_SIZE=${candidate}
      break
    fi
  done
else
  is_positive_int "${SP_SIZE}" || fail "SP_SIZE must be auto or a positive integer"
fi
((NPROC_PER_NODE % SP_SIZE == 0)) || fail \
  "NPROC_PER_NODE=${NPROC_PER_NODE} must be divisible by SP_SIZE=${SP_SIZE}"
DP_SIZE=$((NPROC_PER_NODE / SP_SIZE))

if [[ "${MAX_TOKEN_LEN_PER_GPU}" == "auto" ]]; then
  per_device_unaligned=$(( (MAX_LENGTH + SP_SIZE - 1) / SP_SIZE ))
  MAX_TOKEN_LEN_PER_GPU=$((
    ((per_device_unaligned + LENGTH_ALIGNMENT - 1) / LENGTH_ALIGNMENT) * LENGTH_ALIGNMENT
  ))
fi
is_positive_int "${MAX_TOKEN_LEN_PER_GPU}" || fail \
  "MAX_TOKEN_LEN_PER_GPU must be auto or a positive integer"
EFFECTIVE_MICRO_TOKEN_BUDGET=$((MAX_TOKEN_LEN_PER_GPU * SP_SIZE))
((EFFECTIVE_MICRO_TOKEN_BUDGET >= OBSERVED_MAX_TOTAL)) || fail \
  "MAX_TOKEN_LEN_PER_GPU * SP_SIZE is below the longest sample"

if [[ -z "${TRAIN_BATCH_SIZE}" ]]; then
  TRAIN_BATCH_SIZE=$((DP_SIZE * 2))
fi
is_positive_int "${TRAIN_BATCH_SIZE}" || fail "TRAIN_BATCH_SIZE must be a positive integer"
((TRAIN_BATCH_SIZE % DP_SIZE == 0)) || fail \
  "TRAIN_BATCH_SIZE=${TRAIN_BATCH_SIZE} must be divisible by DP_SIZE=${DP_SIZE}"
LOCAL_BATCH_SIZE=$((TRAIN_BATCH_SIZE / DP_SIZE))
((LOCAL_BATCH_SIZE % MICRO_BATCH_SIZE_PER_GPU == 0)) || fail \
  "local batch ${LOCAL_BATCH_SIZE} must be divisible by micro batch ${MICRO_BATCH_SIZE_PER_GPU}"

if [[ -z "${LEARNING_RATE}" ]]; then
  if ((LORA_RANK > 0)); then
    LEARNING_RATE=1e-5
  else
    LEARNING_RATE=1e-6
  fi
fi
if ((LORA_RANK > 0)); then
  TRAINING_MODE=LoRA
  LORA_SUMMARY="rank=${LORA_RANK}, alpha=${LORA_ALPHA}, targets=${LORA_TARGET_MODULES}"
else
  TRAINING_MODE=full-parameter
  LORA_SUMMARY="disabled (rank=0)"
fi

if [[ "${DRY_RUN}" == "1" ]]; then
  required_probe_rows=$((TRAIN_BATCH_SIZE * DRY_RUN_STEPS))
  ((PROBE_ROWS >= required_probe_rows)) || fail \
    "PROBE_ROWS=${PROBE_ROWS} is below TRAIN_BATCH_SIZE*DRY_RUN_STEPS=${required_probe_rows}"
  [[ -f "${OOM_PROBE_FILE}" ]] || fail "OOM probe was not created: ${OOM_PROBE_FILE}"
  TRAIN_FILE=${OOM_PROBE_FILE}
else
  TRAIN_FILE=${DATA_DIR}/train.parquet
fi

case "${LOGGER}" in
  console) logger_config='["console"]' ;;
  wandb) logger_config='["console","wandb"]' ;;
  *) fail "LOGGER must be console or wandb" ;;
esac
case "${RESUME_MODE}" in disable|auto) ;; *) fail "RESUME_MODE must be disable or auto" ;; esac

if [[ "${DRY_RUN}" == "0" && "${RESUME_MODE}" == "disable" ]] && \
  compgen -G "${SAVE_PATH}/global_step_*" >/dev/null; then
  fail "${SAVE_PATH} already contains checkpoints; use a new path or RESUME_MODE=auto"
fi

mkdir -p -- "${LOG_DIR}"
LOG_FILE=${LOG_FILE:-${LOG_DIR}/run-$(date +%Y%m%d-%H%M%S)-$$.log}
exec > >(tee -a "${LOG_FILE}") 2>&1

echo "============================================================"
echo "Qwen3.6-27B CreateMyCard veRL SFT"
echo "Model:                        ${MODEL_PATH}"
echo "Train file:                   ${TRAIN_FILE}"
echo "Validation:                   ${DATA_DIR}/validation.parquet"
echo "Checkpoint:                   ${SAVE_PATH}"
echo "Device processes / SP / DP:   ${NPROC_PER_NODE} / ${SP_SIZE} / ${DP_SIZE}"
echo "Observed / configured length: ${OBSERVED_MAX_TOTAL} / ${MAX_LENGTH}"
echo "Prompt / output hard limits:  ${MAX_PROMPT_TOKENS} / ${MAX_OUTPUT_TOKENS}"
echo "Per-device token budget:      ${MAX_TOKEN_LEN_PER_GPU}"
echo "Effective SP token budget:    ${EFFECTIVE_MICRO_TOKEN_BUDGET}"
echo "Global / local / micro batch: ${TRAIN_BATCH_SIZE} / ${LOCAL_BATCH_SIZE} / ${MICRO_BATCH_SIZE_PER_GPU}"
echo "Training mode:                ${TRAINING_MODE}"
echo "LoRA:                         ${LORA_SUMMARY}"
echo "Gradient checkpointing:       true"
echo "Param / optimizer offload:    ${PARAM_OFFLOAD} / ${OPTIMIZER_OFFLOAD}"
echo "Activation offload:           ${ACTIVATION_OFFLOAD}"
echo "Learning rate / epochs:       ${LEARNING_RATE} / ${TOTAL_EPOCHS}"
echo "Dry run / steps:              ${DRY_RUN} / ${DRY_RUN_STEPS}"
echo "Token report:                 ${TOKEN_REPORT}"
echo "Log:                          ${LOG_FILE}"
echo "============================================================"

extra_args=()
if [[ "${DRY_RUN}" == "1" ]]; then
  extra_args+=(
    "trainer.total_training_steps=${DRY_RUN_STEPS}"
    trainer.save_freq=-1
    trainer.test_freq=-1
    trainer.resume_mode=disable
    'checkpoint.save_contents=["model","extra"]'
  )
else
  extra_args+=(
    "trainer.total_epochs=${TOTAL_EPOCHS}"
    trainer.save_freq=after_each_epoch
    trainer.test_freq=after_each_epoch
    "trainer.max_ckpt_to_keep=${MAX_CKPT_TO_KEEP}"
    "trainer.resume_mode=${RESUME_MODE}"
    'checkpoint.save_contents=["model","optimizer","extra"]'
  )
fi

lora_args=("model.lora_rank=${LORA_RANK}")
if ((LORA_RANK > 0)); then
  lora_args+=(
    "model.lora_alpha=${LORA_ALPHA}"
    "model.target_modules=${LORA_TARGET_MODULES}"
  )
fi

cd "${PROJECT_ROOT}"

torchrun \
  --nnodes=1 \
  --node_rank=0 \
  --nproc_per_node="${NPROC_PER_NODE}" \
  --master_addr="${MASTER_ADDR}" \
  --master_port="${MASTER_PORT}" \
  -m verl.trainer.sft_trainer \
  "data.train_files=${TRAIN_FILE}" \
  "data.val_files=${DATA_DIR}/validation.parquet" \
  "data.train_batch_size=${TRAIN_BATCH_SIZE}" \
  "data.micro_batch_size_per_gpu=${MICRO_BATCH_SIZE_PER_GPU}" \
  "data.max_length=${MAX_LENGTH}" \
  "data.max_token_len_per_gpu=${MAX_TOKEN_LEN_PER_GPU}" \
  data.use_dynamic_bsz=true \
  data.messages_key=messages \
  data.enable_thinking_key=enable_thinking \
  data.enable_thinking_default=false \
  'data.apply_chat_template_kwargs={enable_thinking:false}' \
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
  "${lora_args[@]}" \
  engine=fsdp \
  "engine.strategy=${FSDP_STRATEGY}" \
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
  "optim.lr_warmup_steps_ratio=${WARMUP_RATIO}" \
  "optim.weight_decay=${WEIGHT_DECAY}" \
  'optim.betas=[0.9,0.95]' \
  optim.clip_grad=1.0 \
  "trainer.default_local_dir=${SAVE_PATH}" \
  "trainer.project_name=${PROJECT_NAME}" \
  "trainer.experiment_name=${EXPERIMENT_NAME}" \
  "trainer.logger=${logger_config}" \
  "trainer.device=${TRAIN_DEVICE}" \
  trainer.nnodes=1 \
  "trainer.n_gpus_per_node=${NPROC_PER_NODE}" \
  "${extra_args[@]}" \
  "$@"
