#!/usr/bin/env bash
set -euo pipefail

MODEL_PATH=${MODEL_PATH:-/mnt/model/Qwen3.6-27B}
DATA_DIR=${DATA_DIR:-/mnt/data/verl-smoke/gsm8k}
TRAIN_FILE=${TRAIN_FILE:-"${DATA_DIR}/train.parquet"}
TEST_FILE=${TEST_FILE:-"${DATA_DIR}/test.parquet"}
OUTPUT_DIR=${OUTPUT_DIR:-/mnt/data/verl-smoke}
RAY_TMPDIR=${RAY_TMPDIR:-"${OUTPUT_DIR}/ray"}
PROJECT_NAME=${PROJECT_NAME:-verl-qwen36-smoke}
EXPERIMENT_NAME=${EXPERIMENT_NAME:-qwen3_6-27b-grpo-gsm8k}

NDEVICES_PER_NODE=${NDEVICES_PER_NODE:-16}
NNODES=${NNODES:-1}
FSDP_SIZE=${FSDP_SIZE:-${NDEVICES_PER_NODE}}
GEN_TP=${GEN_TP:-4}
ROLLOUT_GPU_MEM_UTIL=${ROLLOUT_GPU_MEM_UTIL:-0.35}
ROLLOUT_N=${ROLLOUT_N:-2}
TRAIN_BATCH_SIZE=${TRAIN_BATCH_SIZE:-8}
PPO_MINI_BATCH_SIZE=${PPO_MINI_BATCH_SIZE:-16}
MAX_PROMPT_LENGTH=${MAX_PROMPT_LENGTH:-512}
MAX_RESPONSE_LENGTH=${MAX_RESPONSE_LENGTH:-512}
TOTAL_TRAINING_STEPS=${TOTAL_TRAINING_STEPS:-2}

CHECKPOINT_DIR=${CHECKPOINT_DIR:-"${OUTPUT_DIR}/checkpoints/${PROJECT_NAME}/${EXPERIMENT_NAME}"}
LOG_DIR=${LOG_DIR:-"${OUTPUT_DIR}/logs/${PROJECT_NAME}/${EXPERIMENT_NAME}"}

if [[ ! -d "${MODEL_PATH}" ]]; then
    echo "Model directory not found: ${MODEL_PATH}" >&2
    exit 1
fi

if [[ ! -f "${TRAIN_FILE}" || ! -f "${TEST_FILE}" ]]; then
    echo "GSM8K parquet files not found. Run frameworks/verl/prepare_gsm8k_smoke.sh first." >&2
    exit 1
fi

if ! python3 -c "import torch_npu"; then
    echo "torch_npu is unavailable; run this inside the Ascend verl container." >&2
    exit 1
fi

if (( NDEVICES_PER_NODE < 1 || FSDP_SIZE < 1 || GEN_TP < 1 || ROLLOUT_N < 2 )); then
    echo "NDEVICES_PER_NODE, FSDP_SIZE, GEN_TP must be positive and ROLLOUT_N must be at least 2." >&2
    exit 1
fi

if (( (TRAIN_BATCH_SIZE * ROLLOUT_N) % PPO_MINI_BATCH_SIZE != 0 )); then
    echo "PPO_MINI_BATCH_SIZE must divide TRAIN_BATCH_SIZE * ROLLOUT_N." >&2
    exit 1
fi

export HCCL_CONNECT_TIMEOUT=${HCCL_CONNECT_TIMEOUT:-1500}
export HCCL_HOST_SOCKET_PORT_RANGE=${HCCL_HOST_SOCKET_PORT_RANGE:-60000-60050}
export HCCL_NPU_SOCKET_PORT_RANGE=${HCCL_NPU_SOCKET_PORT_RANGE:-61000-61050}
export HCCL_EXEC_TIMEOUT=${HCCL_EXEC_TIMEOUT:-3600}
export RAY_EXPERIMENTAL_NOSET_ASCEND_RT_VISIBLE_DEVICES=1
export RAY_TMPDIR

mkdir -p "${CHECKPOINT_DIR}" "${LOG_DIR}" "${RAY_TMPDIR}"

timestamp=$(date +%Y%m%d_%H%M%S)
log_file="${LOG_DIR}/qwen3_6_27b_grpo_smoke_${timestamp}.log"

echo "Starting text-only Qwen3.6-27B GRPO smoke test on ${NDEVICES_PER_NODE} Ascend NPUs."
echo "This run does not validate image or video inputs."

DATA=(
    algorithm.adv_estimator=grpo
    algorithm.use_kl_in_reward=False
    data.train_files="${TRAIN_FILE}"
    data.val_files="${TEST_FILE}"
    data.train_batch_size=${TRAIN_BATCH_SIZE}
    data.max_prompt_length=${MAX_PROMPT_LENGTH}
    data.max_response_length=${MAX_RESPONSE_LENGTH}
    data.filter_overlong_prompts=True
    data.truncation=error
    data.return_multi_modal_inputs=False
    data.shuffle=False
)

MODEL=(
    actor_rollout_ref.model.path="${MODEL_PATH}"
    actor_rollout_ref.model.use_remove_padding=True
    actor_rollout_ref.model.enable_gradient_checkpointing=True
)

ACTOR=(
    actor_rollout_ref.actor.strategy=fsdp2
    actor_rollout_ref.actor.optim.lr=1e-6
    actor_rollout_ref.actor.ppo_mini_batch_size=${PPO_MINI_BATCH_SIZE}
    actor_rollout_ref.actor.ppo_micro_batch_size_per_gpu=1
    actor_rollout_ref.actor.use_dynamic_bsz=False
    actor_rollout_ref.actor.use_kl_loss=True
    actor_rollout_ref.actor.kl_loss_coef=0.01
    actor_rollout_ref.actor.kl_loss_type=low_var_kl
    actor_rollout_ref.actor.entropy_coeff=0
    actor_rollout_ref.actor.use_torch_compile=False
    actor_rollout_ref.actor.fsdp_config.fsdp_size=${FSDP_SIZE}
    actor_rollout_ref.actor.fsdp_config.reshard_after_forward=True
    actor_rollout_ref.actor.fsdp_config.entropy_checkpointing=True
    actor_rollout_ref.actor.entropy_from_logits_with_chunking=True
    actor_rollout_ref.actor.fsdp_config.offload_policy=True
    actor_rollout_ref.actor.fsdp_config.param_offload=True
    actor_rollout_ref.actor.fsdp_config.optimizer_offload=True
)

REF=(
    actor_rollout_ref.ref.strategy=fsdp2
    actor_rollout_ref.ref.log_prob_micro_batch_size_per_gpu=1
    actor_rollout_ref.ref.fsdp_config.reshard_after_forward=True
    actor_rollout_ref.ref.entropy_from_logits_with_chunking=True
    actor_rollout_ref.ref.use_torch_compile=False
    actor_rollout_ref.ref.fsdp_config.offload_policy=True
    actor_rollout_ref.ref.fsdp_config.param_offload=True
)

ROLLOUT=(
    actor_rollout_ref.rollout.name=vllm
    actor_rollout_ref.rollout.prompt_length=${MAX_PROMPT_LENGTH}
    actor_rollout_ref.rollout.response_length=${MAX_RESPONSE_LENGTH}
    actor_rollout_ref.rollout.log_prob_micro_batch_size_per_gpu=1
    actor_rollout_ref.rollout.tensor_model_parallel_size=${GEN_TP}
    actor_rollout_ref.rollout.gpu_memory_utilization=${ROLLOUT_GPU_MEM_UTIL}
    actor_rollout_ref.rollout.n=${ROLLOUT_N}
    actor_rollout_ref.rollout.enable_chunked_prefill=True
    actor_rollout_ref.rollout.max_num_batched_tokens=2048
    actor_rollout_ref.rollout.free_cache_engine=True
    actor_rollout_ref.rollout.enforce_eager=False
    actor_rollout_ref.rollout.enable_prefix_caching=False
)

TRAINER=(
    trainer.device=npu
    trainer.critic_warmup=0
    trainer.logger=['console']
    trainer.project_name="${PROJECT_NAME}"
    trainer.experiment_name="${EXPERIMENT_NAME}"
    trainer.n_gpus_per_node=${NDEVICES_PER_NODE}
    trainer.nnodes=${NNODES}
    trainer.balance_batch=False
    trainer.default_local_dir="${CHECKPOINT_DIR}"
    trainer.resume_mode=disable
    trainer.val_before_train=False
    trainer.save_freq=1
    trainer.test_freq=-1
    trainer.total_epochs=1
    trainer.total_training_steps=${TOTAL_TRAINING_STEPS}
)

python3 -m verl.trainer.main_ppo \
    "${DATA[@]}" \
    "${MODEL[@]}" \
    "${ACTOR[@]}" \
    "${REF[@]}" \
    "${ROLLOUT[@]}" \
    "${TRAINER[@]}" \
    "$@" 2>&1 | tee "${log_file}"
