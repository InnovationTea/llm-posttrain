#!/usr/bin/env bash
set -euo pipefail

# MODEL_PATH defaults to the mounted Qwen3.6-27B checkpoint.
MODEL_PATH=${MODEL_PATH:-/mnt/model/Qwen3.6-27B}
# NDEVICES_PER_NODE defaults to the 16-device Ascend 910C smoke-test node.
NDEVICES_PER_NODE=${NDEVICES_PER_NODE:-16}

# Planned actor setting: actor_rollout_ref.actor.strategy=fsdp2
# The actual data preparation and training configuration will follow.
