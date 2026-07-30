#!/bin/bash

WORK_DIR=${WORK_DIR:-/root/workspace}
CONTAINER_WORK_DIR=${CONTAINER_WORK_DIR:-/workspace}

# 默认镜像：Atlas A3 / CANN 9.0.0 / veRL 0.8.0 / vLLM 0.18.0
DEFAULT_IMAGE=quay.io/ascend/verl:v0.8.0-cann9.0.0-torch_npu2.9.0post2-a3-ubuntu22.04-py3.11-vllm

CONTAINER_NAME="$1"
DEVICE_IDS="$2"
IMAGE="${3:-$DEFAULT_IMAGE}"

if [ -z "$CONTAINER_NAME" ]; then
  echo "Usage: $0 <container_name> [device_ids] [image]"
  echo "Example:"
  echo "  $0 train1                     # 使用全部 NPU，默认镜像"
  echo "  $0 train2 0,1                 # 使用 NPU 0、1"
  echo "  $0 train3 '' myimage:latest   # 使用全部 NPU，自定义镜像"
  exit 1
fi

cd "${WORK_DIR}" || exit 1

# ===== 构造 device 参数 =====
DEVICE_ARGS=()
VISIBLE_DEVICE_IDS=()

if [ -n "$DEVICE_IDS" ]; then
  # 指定 NPU，例如：0,1
  # 按数字顺序排序，避免输入 0,10,2 时顺序异常
  while IFS= read -r id; do
    dev="/dev/davinci${id}"

    if [ ! -e "$dev" ]; then
      echo "Error: NPU device does not exist: $dev"
      exit 1
    fi

    DEVICE_ARGS+=(--device="$dev")
    VISIBLE_DEVICE_IDS+=("$id")
  done < <(echo "$DEVICE_IDS" | tr ',' '\n' | sort -n)

else
  # 未指定 NPU：自动挂载全部 /dev/davinci<N>
  # 注意：glob 默认按字典序排序，会出现 0,1,10,11,2...
  # sort -V 可保证自然数字顺序：0,1,2,...,10,11...
  shopt -s nullglob

  while IFS= read -r dev; do
    id="${dev#/dev/davinci}"
    DEVICE_ARGS+=(--device="$dev")
    VISIBLE_DEVICE_IDS+=("$id")
  done < <(printf '%s\n' /dev/davinci[0-9]* | sort -V)

  shopt -u nullglob

  if [ "${#DEVICE_ARGS[@]}" -eq 0 ]; then
    echo "Error: No /dev/davinci<N> NPU devices found."
    exit 1
  fi
fi

ASCEND_DEVICES=$(IFS=,; echo "${VISIBLE_DEVICE_IDS[*]}")

echo "Starting container: ${CONTAINER_NAME}"
echo "Visible NPU devices: ${ASCEND_DEVICES}"

# ===== 启动容器 =====
docker run -itd \
  --privileged \
  --cap-add=SYS_PTRACE \
  --net=host \
  "${DEVICE_ARGS[@]}" \
  --device=/dev/davinci_manager \
  --device=/dev/devmm_svm \
  --device=/dev/hisi_hdc \
  --shm-size=64g \
  -e ASCEND_VISIBLE_DEVICES="${ASCEND_DEVICES}" \
  -e ASCEND_RT_VISIBLE_DEVICES="${ASCEND_DEVICES}" \
  -v /usr/local/sbin/npu-smi:/usr/local/sbin/npu-smi \
  -v /usr/local/dcmi:/usr/local/dcmi \
  -v /etc/ascend_install.info:/etc/ascend_install.info \
  -v /sys/fs/cgroup:/sys/fs/cgroup:ro \
  -v /usr/local/Ascend/driver:/usr/local/Ascend/driver \
  -v /var/log/npu/:/usr/slog \
  -v /mnt/model:/mnt/model \
  -v /mnt/data:/mnt/data \
  -v "${WORK_DIR}:${CONTAINER_WORK_DIR}" \
  --name "${CONTAINER_NAME}" \
  "${IMAGE}" \
  /bin/bash
