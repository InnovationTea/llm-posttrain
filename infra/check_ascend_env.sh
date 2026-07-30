#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

MASTER_ADDR=${MASTER_ADDR:-127.0.0.1}
MASTER_PORT=${MASTER_PORT:-29500}
NPROC_PER_NODE=${NPROC_PER_NODE:-$(python3 -c '
import torch
import torch_npu  # noqa: F401
print(torch.npu.device_count())
')}

if ! [[ "${NPROC_PER_NODE}" =~ ^[1-9][0-9]*$ ]]; then
  echo "Error: NPROC_PER_NODE must be positive, got: ${NPROC_PER_NODE}" >&2
  exit 1
fi

exec torchrun \
  --nnodes=1 \
  --node_rank=0 \
  --nproc_per_node="${NPROC_PER_NODE}" \
  --master_addr="${MASTER_ADDR}" \
  --master_port="${MASTER_PORT}" \
  "${SCRIPT_DIR}/check_ascend_env.py"
