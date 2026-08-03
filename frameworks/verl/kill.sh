#!/usr/bin/env bash
set -euo pipefail

KILL_GRACE_SECONDS=${KILL_GRACE_SECONDS:-10}
if ! [[ "${KILL_GRACE_SECONDS}" =~ ^[0-9]+$ ]]; then
  echo "Error: KILL_GRACE_SECONDS must be a non-negative integer." >&2
  exit 1
fi
if ! command -v pgrep >/dev/null 2>&1; then
  echo "Error: pgrep is required." >&2
  exit 1
fi

patterns=(
  '[v]erl\.trainer\.sft_trainer'
  '[v]erl\.trainer\.main_ppo'
  '[t]ensorboard(\.main)?([[:space:]]|$)'
)

mapfile -t root_pids < <(
  for pattern in "${patterns[@]}"; do
    pgrep -f -- "${pattern}" || true
  done | sort -un
)

if ((${#root_pids[@]} == 0)); then
  echo "No VERL training or TensorBoard processes found."
  exit 0
fi

collect_descendants() {
  local parent_pid=$1
  local child_pid

  while read -r child_pid; do
    [[ -n "${child_pid}" ]] || continue
    collect_descendants "${child_pid}"
    printf '%s\n' "${child_pid}"
  done < <(pgrep -P "${parent_pid}" || true)
}

mapfile -t pids < <(
  for root_pid in "${root_pids[@]}"; do
    collect_descendants "${root_pid}"
    printf '%s\n' "${root_pid}"
  done | awk '!seen[$0]++'
)

echo "Warning: stopping all matching VERL training and TensorBoard processes on this host:"
ps -o pid=,ppid=,stat=,args= -p "$(IFS=,; echo "${pids[*]}")" || true

kill -TERM "${pids[@]}" 2>/dev/null || true

for ((second = 0; second < KILL_GRACE_SECONDS; second++)); do
  alive=()
  for pid in "${pids[@]}"; do
    if kill -0 "${pid}" 2>/dev/null; then
      alive+=("${pid}")
    fi
  done
  if ((${#alive[@]} == 0)); then
    echo "All matching processes stopped."
    exit 0
  fi
  sleep 1
done

alive=()
for pid in "${pids[@]}"; do
  if kill -0 "${pid}" 2>/dev/null; then
    alive+=("${pid}")
  fi
done
if ((${#alive[@]} > 0)); then
  echo "Force stopping remaining PIDs: ${alive[*]}"
  kill -KILL "${alive[@]}" 2>/dev/null || true
fi

echo "All matching processes stopped."
