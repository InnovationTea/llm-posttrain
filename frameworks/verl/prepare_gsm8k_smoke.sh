#!/usr/bin/env bash
set -euo pipefail

VERL_HOME=${VERL_HOME:-/workspace/verl}
DATA_DIR=${DATA_DIR:-/mnt/data/verl-smoke/gsm8k}
PREPROCESSOR="${VERL_HOME}/examples/data_preprocess/gsm8k.py"

if [[ ! -f "${PREPROCESSOR}" ]]; then
    echo "GSM8K preprocessor not found: ${PREPROCESSOR}" >&2
    echo "Set VERL_HOME to the root of the verl checkout in the container." >&2
    exit 1
fi

if [[ -f "${DATA_DIR}/train.parquet" && -f "${DATA_DIR}/test.parquet" ]]; then
    echo "Reusing existing GSM8K parquet files in ${DATA_DIR}"
    exit 0
fi

mkdir -p "${DATA_DIR}"
python3 "${PREPROCESSOR}" --local_save_dir "${DATA_DIR}"

if [[ ! -f "${DATA_DIR}/train.parquet" || ! -f "${DATA_DIR}/test.parquet" ]]; then
    echo "GSM8K preprocessing did not produce train.parquet and test.parquet in ${DATA_DIR}" >&2
    exit 1
fi
