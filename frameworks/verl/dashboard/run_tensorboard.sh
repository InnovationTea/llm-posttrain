#!/usr/bin/env bash
set -euo pipefail

TENSORBOARD_DIR=${TENSORBOARD_DIR:-/mnt/data/logs/verl}
TENSORBOARD_HOST=${TENSORBOARD_HOST:-0.0.0.0}
TENSORBOARD_PORT=${TENSORBOARD_PORT:-6006}
TENSORBOARD_LOG_FILE=${TENSORBOARD_LOG_FILE:-${TENSORBOARD_DIR}/tensorboard.log}
TENSORBOARD_PID_FILE=${TENSORBOARD_PID_FILE:-${TENSORBOARD_DIR}/tensorboard.pid}

if ! [[ "${TENSORBOARD_PORT}" =~ ^[1-9][0-9]*$ ]] || ((TENSORBOARD_PORT > 65535)); then
  echo "Error: TENSORBOARD_PORT must be an integer from 1 to 65535, got: ${TENSORBOARD_PORT}" >&2
  exit 1
fi

port_in_use=false
if command -v ss >/dev/null 2>&1; then
  if ss -ltnH "sport = :${TENSORBOARD_PORT}" 2>/dev/null | grep -q .; then
    port_in_use=true
  fi
elif command -v lsof >/dev/null 2>&1; then
  if lsof -nP -iTCP:"${TENSORBOARD_PORT}" -sTCP:LISTEN 2>/dev/null | grep -q .; then
    port_in_use=true
  fi
else
  echo "Error: either ss or lsof is required to check TENSORBOARD_PORT." >&2
  exit 1
fi

if [[ "${port_in_use}" == "true" ]]; then
  tensorboard_processes=$(pgrep -af '[t]ensorboard' || true)
  if grep -Eq -- "--port([=[:space:]])${TENSORBOARD_PORT}([[:space:]]|$)" <<<"${tensorboard_processes}"; then
    echo "TensorBoard is already running on port ${TENSORBOARD_PORT}. Reusing it."
    echo "The existing process keeps its original --logdir; requested: ${TENSORBOARD_DIR}"
    exit 0
  fi
  echo "Error: port ${TENSORBOARD_PORT} is occupied by a non-TensorBoard process." >&2
  exit 1
fi
if ! command -v tensorboard >/dev/null 2>&1; then
  echo "Error: tensorboard executable was not found in PATH." >&2
  exit 1
fi

mkdir -p -- "${TENSORBOARD_DIR}" "$(dirname -- "${TENSORBOARD_LOG_FILE}")" \
  "$(dirname -- "${TENSORBOARD_PID_FILE}")"

nohup tensorboard \
  --logdir "${TENSORBOARD_DIR}" \
  --host "${TENSORBOARD_HOST}" \
  --port "${TENSORBOARD_PORT}" \
  >"${TENSORBOARD_LOG_FILE}" 2>&1 &
tensorboard_pid=$!
printf '%s\n' "${tensorboard_pid}" >"${TENSORBOARD_PID_FILE}"

sleep 1
if ! kill -0 "${tensorboard_pid}" 2>/dev/null; then
  echo "Error: TensorBoard exited during startup. See ${TENSORBOARD_LOG_FILE}" >&2
  exit 1
fi

echo "TensorBoard started in the background."
echo "PID:    ${tensorboard_pid}"
echo "URL:    http://${TENSORBOARD_HOST}:${TENSORBOARD_PORT}"
echo "Logdir: ${TENSORBOARD_DIR}"
echo "Log:    ${TENSORBOARD_LOG_FILE}"
