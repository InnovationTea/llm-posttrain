#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(cd -- "${SCRIPT_DIR}/../../../.." && pwd)

SAVE_PATH=${SAVE_PATH:-/mnt/data/checkpoints/qwen36-27b-gsm8k-sft-v1}
MERGED_MODEL=${MERGED_MODEL:-}

if [[ -z "${MERGED_MODEL}" ]]; then
  echo "Error: MERGED_MODEL must point to a new output directory." >&2
  exit 1
fi

tracker="${SAVE_PATH}/latest_checkpointed_iteration.txt"
if [[ ! -f "${tracker}" ]]; then
  echo "Error: checkpoint tracker does not exist: ${tracker}" >&2
  exit 1
fi

step=$(tr -d '[:space:]' < "${tracker}")
if ! [[ "${step}" =~ ^[1-9][0-9]*$ ]]; then
  echo "Error: invalid checkpoint step in ${tracker}: ${step}" >&2
  exit 1
fi

ckpt_dir="${SAVE_PATH}/global_step_${step}"
if [[ ! -f "${ckpt_dir}/fsdp_config.json" ]]; then
  echo "Error: invalid FSDP checkpoint directory: ${ckpt_dir}" >&2
  exit 1
fi
if ! compgen -G "${ckpt_dir}/model_world_size_*_rank_*.pt" >/dev/null; then
  echo "Error: no FSDP model shards found in ${ckpt_dir}" >&2
  exit 1
fi
if [[ -e "${MERGED_MODEL}" || -L "${MERGED_MODEL}" ]]; then
  echo "Error: merge target already exists: ${MERGED_MODEL}" >&2
  exit 1
fi

echo "Merging FSDP checkpoint"
echo "  source: ${ckpt_dir}"
echo "  target: ${MERGED_MODEL}"
echo "  started: $(date '+%Y-%m-%d %H:%M:%S %z')"
echo "Loading and rebuilding 27B shards on CPU can remain quiet for tens of minutes."

cd "${PROJECT_ROOT}"
python3 -m verl.model_merger merge \
  --backend fsdp \
  --local_dir "${ckpt_dir}" \
  --target_dir "${MERGED_MODEL}" \
  --trust-remote-code \
  --use_cpu_initialization

python3 frameworks/verl/qwen36_gsm8k/sft/preflight.py \
  --model-path "${MERGED_MODEL}"

echo "Merge completed at $(date '+%Y-%m-%d %H:%M:%S %z')"
