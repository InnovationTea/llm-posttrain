#!/usr/bin/env bash
set -euo pipefail

# Validated on one A3 server exposing 16 logical Ascend NPU devices.

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
VERL_DIR=$(cd -- "${SCRIPT_DIR}/../.." && pwd)

LOG_DIR=${LOG_DIR:-/mnt/data/logs/qwen36-27b-gsm8k-grpo}
LOG_FILE=${LOG_FILE:-}
TENSORBOARD_DIR=${TENSORBOARD_DIR:-/mnt/data/logs/verl_gsm8k_grpo_1}
TENSORBOARD_HOST=${TENSORBOARD_HOST:-0.0.0.0}
TENSORBOARD_PORT=${TENSORBOARD_PORT:-6006}

if [[ -z "${LOG_FILE}" ]]; then
  LOG_FILE="${LOG_DIR}/train-$(date +%Y%m%d-%H%M%S)-$$.log"
fi
mkdir -p -- "$(dirname -- "${LOG_FILE}")"

TENSORBOARD_DIR="${TENSORBOARD_DIR}" \
  TENSORBOARD_HOST="${TENSORBOARD_HOST}" \
  TENSORBOARD_PORT="${TENSORBOARD_PORT}" \
  bash "${VERL_DIR}/dashboard/run_tensorboard.sh"

export PYTHONUNBUFFERED=1
export HYDRA_FULL_ERROR=1
export ASCEND_RT_VISIBLE_DEVICES=0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15

# 避免与 vLLM Ascend CaMem 冲突。
unset PYTORCH_NPU_ALLOC_CONF || true

nohup python3 -m verl.trainer.main_ppo \
  data.train_files=/mnt/data/gsm8k/train.parquet \
  data.val_files=/mnt/data/gsm8k/test.parquet \
  data.train_batch_size=8 \
  data.max_prompt_length=512 \
  data.max_response_length=1024 \
  data.dataloader_num_workers=0 \
  +data.apply_chat_template_kwargs.enable_thinking=False \
  actor_rollout_ref.model.path=/mnt/model/Qwen3.6-27B \
  actor_rollout_ref.model.enable_gradient_checkpointing=True \
  actor_rollout_ref.model.enable_activation_offload=True \
  actor_rollout_ref.actor.strategy=fsdp2 \
  actor_rollout_ref.actor.fsdp_config.param_offload=True \
  actor_rollout_ref.actor.fsdp_config.optimizer_offload=True \
  actor_rollout_ref.actor.optim.lr=5e-7 \
  actor_rollout_ref.actor.ppo_mini_batch_size=8 \
  actor_rollout_ref.actor.ppo_micro_batch_size_per_gpu=1 \
  actor_rollout_ref.actor.use_kl_loss=True \
  actor_rollout_ref.actor.kl_loss_coef=0.001 \
  actor_rollout_ref.actor.kl_loss_type=low_var_kl \
  actor_rollout_ref.ref.strategy=fsdp2 \
  actor_rollout_ref.ref.fsdp_config.param_offload=True \
  actor_rollout_ref.ref.log_prob_micro_batch_size_per_gpu=1 \
  actor_rollout_ref.rollout.name=vllm \
  actor_rollout_ref.rollout.tensor_model_parallel_size=8 \
  actor_rollout_ref.rollout.n=4 \
  actor_rollout_ref.rollout.max_model_len=1536 \
  actor_rollout_ref.rollout.max_num_batched_tokens=2048 \
  actor_rollout_ref.rollout.max_num_seqs=4 \
  actor_rollout_ref.rollout.gpu_memory_utilization=0.15 \
  actor_rollout_ref.rollout.log_prob_micro_batch_size_per_gpu=1 \
  actor_rollout_ref.rollout.enforce_eager=True \
  actor_rollout_ref.rollout.free_cache_engine=True \
  algorithm.adv_estimator=grpo \
  algorithm.use_kl_in_reward=False \
  trainer.device=npu \
  'trainer.logger=["console","tensorboard"]' \
  trainer.n_gpus_per_node=16 \
  trainer.nnodes=1 \
  trainer.val_before_train=False \
  trainer.total_epochs=1 \
  trainer.save_freq=900 \
  trainer.max_actor_ckpt_to_keep=1 \
  trainer.test_freq=-1 \
  trainer.critic_warmup=0 \
  "$@" \
  >"${LOG_FILE}" 2>&1 &
training_pid=$!

echo "GRPO training started in the background."
echo "PID:          ${training_pid}"
echo "Training log: ${LOG_FILE}"
echo "TensorBoard:  http://${TENSORBOARD_HOST}:${TENSORBOARD_PORT}"
