# Qwen3.6 Ascend Smoke Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add runnable GSM8K preparation and 16-NPU Qwen3.6-27B GRPO smoke-test scripts for the existing verl Docker workflow.

**Architecture:** A preparation script delegates parquet conversion to verl's own GSM8K preprocessor. The launcher is a self-contained Bash wrapper around `verl.trainer.main_ppo`, with conservative FSDP2/vLLM-Ascend defaults and environment-variable overrides. A standard-library Python test checks the shell-level user contract without requiring Ascend hardware.

**Tech Stack:** Bash, Python standard-library unittest, verl, Ray, PyTorch NPU, FSDP2, vLLM-Ascend.

---

### Task 1: Define the script contract

**Files:**
- Create: `tests/test_qwen36_ascend_smoke_scripts.py`
- Create: `frameworks/verl/prepare_gsm8k_smoke.sh`
- Create: `frameworks/verl/run_qwen3_6_27b_grpo_smoke.sh`

- [ ] **Step 1: Write the failing test**

```python
def test_launcher_targets_qwen36_and_16_npu_fsdp2():
    assert "MODEL_PATH=${MODEL_PATH:-/mnt/model/Qwen3.6-27B}" in launcher
    assert "NDEVICES_PER_NODE=${NDEVICES_PER_NODE:-16}" in launcher
    assert "actor_rollout_ref.actor.strategy=fsdp2" in launcher
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_qwen36_ascend_smoke_scripts.py -v`

Expected: FAIL because neither smoke-test script exists.

- [ ] **Step 3: Add the minimal script skeletons**

```bash
#!/usr/bin/env bash
set -euo pipefail
```

Add documented environment-variable defaults, argument forwarding, and no repository-relative data/output paths.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m unittest tests/test_qwen36_ascend_smoke_scripts.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_qwen36_ascend_smoke_scripts.py frameworks/verl
git commit -m "feat: add Qwen3.6 Ascend smoke scripts"
```

### Task 2: Implement deterministic GSM8K preparation

**Files:**
- Modify: `frameworks/verl/prepare_gsm8k_smoke.sh`
- Modify: `tests/test_qwen36_ascend_smoke_scripts.py`

- [ ] **Step 1: Add a failing test for the preparation command**

```python
def test_preparer_delegates_to_verl_gsm8k_preprocessor():
    assert 'examples/data_preprocess/gsm8k.py' in preparer
    assert '--local_save_dir "${DATA_DIR}"' in preparer
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `python -m unittest tests/test_qwen36_ascend_smoke_scripts.py -v`

Expected: FAIL because the skeleton does not prepare parquet files.

- [ ] **Step 3: Add path checks and preprocessing invocation**

```bash
python3 "${VERL_HOME}/examples/data_preprocess/gsm8k.py" \
  --local_save_dir "${DATA_DIR}"
```

Fail clearly when `VERL_HOME` or its preprocessor is absent, create the output directory, and skip download when both parquet files already exist.

- [ ] **Step 4: Run the focused test and shell parser**

Run: `python -m unittest tests/test_qwen36_ascend_smoke_scripts.py -v; bash -n frameworks/verl/prepare_gsm8k_smoke.sh`

Expected: PASS.

### Task 3: Implement the 16-NPU GRPO launcher

**Files:**
- Modify: `frameworks/verl/run_qwen3_6_27b_grpo_smoke.sh`
- Modify: `tests/test_qwen36_ascend_smoke_scripts.py`

- [ ] **Step 1: Add failing tests for safety guards and GRPO controls**

```python
def test_launcher_checks_inputs_and_limits_training():
    assert '[[ -d "${MODEL_PATH}" ]]' in launcher
    assert 'python3 -c "import torch_npu"' in launcher
    assert 'algorithm.adv_estimator=grpo' in launcher
    assert 'trainer.total_training_steps=${TOTAL_TRAINING_STEPS}' in launcher
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `python -m unittest tests/test_qwen36_ascend_smoke_scripts.py -v`

Expected: FAIL because the launcher skeleton lacks those safeguards and configuration values.

- [ ] **Step 3: Add launch arrays and input validation**

Use `python3 -m verl.trainer.main_ppo` with batch size 8, `rollout.n=2`, FSDP2 actor/reference, TP 4 rollout, HCCL settings, `trainer.device=npu`, console logging, local data/output paths, and `"$@"` forwarding.

- [ ] **Step 4: Run all static verification**

Run: `python -m unittest tests/test_qwen36_ascend_smoke_scripts.py -v; bash -n frameworks/verl/prepare_gsm8k_smoke.sh frameworks/verl/run_qwen3_6_27b_grpo_smoke.sh`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frameworks/verl tests/test_qwen36_ascend_smoke_scripts.py docs/superpowers
git commit -m "feat: add Qwen3.6 Ascend GRPO smoke test"
```
