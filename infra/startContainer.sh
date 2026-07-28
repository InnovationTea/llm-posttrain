#!/bin/bash

WORK_DIR=/root/workspace
CONTAINER_WORK_DIR=/workspace

# 默认镜像（A3）
DEFAULT_IMAGE=quay.io/ascend/verl:verl-8.5.0-a3-ubuntu22.04-py3.11-v0.7.1

CONTAINER_NAME="$1"
DEVICE_IDS="$2"
IMAGE="${3:-$DEFAULT_IMAGE}"

if [ -z "${CONTAINER_NAME}" ]; then
  echo "Usage: $0 <container_name> [device_ids] [image]"
  echo ""
  echo "Examples:"
  echo "  $0 train1"
  echo "      使用全部 NPU，默认镜像"
  echo ""
  echo "  $0 train2 0,1"
  echo "      使用 NPU 0、1，默认镜像"
  echo ""
  echo "  $0 train3 '' swr.xxx.com/xxx:tag"
  echo "      使用全部 NPU，自定义镜像"
  exit 1
fi

cd "${WORK_DIR}" || {
  echo "Error: WORK_DIR does not exist: ${WORK_DIR}"
  exit 1
}

# ===== 构造 NPU device 参数 =====
DEVICE_ARGS=()
VISIBLE_DEVICE_IDS=()

if [ -n "${DEVICE_IDS}" ]; then
  # 指定 NPU，例如 0,1
  for id in $(echo "${DEVICE_IDS}" | tr ',' ' '); do
    dev="/dev/davinci${id}"

    if [ ! -e "${dev}" ]; then
      echo "Error: NPU device does not exist: ${dev}"
      exit 1
    fi

    DEVICE_ARGS+=(--device="${dev}")
    VISIBLE_DEVICE_IDS+=("${id}")
  done
else
  # 未指定 NPU：自动扫描并挂载所有 /dev/davinci<N>
  shopt -s nullglob

  for dev in /dev/davinci[0-9]*; do
    id="${dev#/dev/davinci}"
    DEVICE_ARGS+=(--device="${dev}")
    VISIBLE_DEVICE_IDS+=("${id}")
  done

  shopt -u nullglob

  if [ "${#DEVICE_ARGS[@]}" -eq 0 ]; then
    echo "Error: No NPU devices found, expected /dev/davinci<N>."
    exit 1
  fi
fi

# 例如：0,1,2,3
ASCEND_DEVICES=$(IFS=,; echo "${VISIBLE_DEVICE_IDS[*]}")

echo "========================================"
echo "Container name: ${CONTAINER_NAME}"
echo "Image:          ${IMAGE}"
echo "NPU devices:    ${ASCEND_DEVICES}"
echo "========================================"

# ===== 启动容器 =====
docker run -itd \
  --cap-add=SYS_PTRACE \
  --net=host \
  "${DEVICE_ARGS[@]}" \
  --device=/dev/davinci_manager \
  --device=/dev/devmm_svm \
  --device=/dev/hisi_hdc \
  --shm-size=64g \
  -e ASCEND_VISIBLE_DEVICES="${ASCEND_DEVICES}" \
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