# Qwen3.6-27B GSM8K GRPO

本目录提供单机 16 个逻辑 Ascend NPU 上验证通过的全参数 GRPO 训练入口：

```bash
cd /workspace
bash frameworks/verl/qwen36_gsm8k/rl/run_grpo.sh
```

脚本固定使用 FSDP2/offload、TP=8 的 vLLM rollout、`n=4`，关闭 thinking，并启用
`console` 与 `tensorboard` logger。TensorBoard 和训练都会在后台启动；命令返回时会打印训练 PID、
持久日志路径和 Dashboard 地址。

训练日志默认写入 `/mnt/data/logs/qwen36-27b-gsm8k-grpo/train-*.log`，不会持续输出到启动终端。
使用命令打印的完整日志路径查看实时进度：

```bash
tail -f /mnt/data/logs/qwen36-27b-gsm8k-grpo/train-<timestamp>-<pid>.log
```

此处按 `Ctrl+C` 只停止 `tail`，不会停止后台训练。后台进程结构、直接后台启动方式和停止语义见
[`dashboard/README.md`](../../dashboard/README.md)。

默认事件目录为 `/mnt/data/logs/verl_gsm8k_grpo_1`，可在命令行指定其他目录；末尾参数会继续透传给 Hydra：

```bash
TENSORBOARD_DIR=/mnt/data/logs/my_grpo_run \
  bash frameworks/verl/qwen36_gsm8k/rl/run_grpo.sh \
  trainer.total_epochs=2
```

公共 Dashboard 也可以独立启动：

```bash
bash frameworks/verl/dashboard/run_tensorboard.sh
```

停止整机上所有匹配的 VERL 训练和 TensorBoard：

```bash
bash frameworks/verl/kill.sh
```

该停止命令也会影响机器上其他 VERL 实验和 TensorBoard 实例。

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
bash -n frameworks/verl/dashboard/run_tensorboard.sh
bash -n frameworks/verl/kill.sh
```
