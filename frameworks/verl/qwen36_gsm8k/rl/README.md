# Qwen3.6-27B GSM8K GRPO

本目录提供单机 16 个逻辑 Ascend NPU 上验证通过的全参数 GRPO 训练入口：

```bash
cd /workspace
bash frameworks/verl/qwen36_gsm8k/rl/run_grpo.sh
```

脚本固定使用 FSDP2/offload、TP=8 的 vLLM rollout、`n=4`，关闭 thinking，并将控制台日志写入当前目录的 `verl_grpo.log`。

开始前应确认以下 RL 数据文件存在：

```text
/mnt/data/gsm8k/train.parquet
/mnt/data/gsm8k/test.parquet
```

这些是包含 prompt、ground truth 和 reward 元数据的 veRL RL 数据，不是 `sft/prepare_gsm8k_sft.py` 生成的 chat-style SFT 数据。

21-step 验证结果、指标定义和结论边界见
[`docs/qwen36_gsm8k_grpo_validation.md`](../../../../docs/qwen36_gsm8k_grpo_validation.md)。

轻量语法检查：

```bash
bash -n frameworks/verl/qwen36_gsm8k/rl/run_grpo.sh
```
