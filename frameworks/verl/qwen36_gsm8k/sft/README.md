# Qwen3.6-27B GSM8K 全参数 SFT

本目录提供一套已经在单机 16 个逻辑 Ascend 910C NPU 上跑通的完整 SFT 流程：

```text
环境检查 → 数据转换与预检 → 训练前评测 → 两步冒烟 → 正式训练
        → FSDP 合并 → 训练后评测 → 配对比较
```

完整命令、参数含义和故障处理见
[`docs/qwen36_gsm8k_sft.md`](../../../../docs/qwen36_gsm8k_sft.md)。

## 入口

| 文件 | 职责 |
| --- | --- |
| `experiment.env.example` | 可复制的实验路径与关键参数模板 |
| `prepare_gsm8k_sft.py` | 生成 train/validation/test Parquet 和数据元信息 |
| `preflight.py` | 检查模型、数据、veRL token 和评测 prompt 对齐 |
| `run_sft.sh` | 后台启动两步冒烟或正式全参数 FSDP SFT，并自动启动 TensorBoard |
| `merge_fsdp_checkpoint.sh` | 从 tracker 定位并安全合并最后一个 FSDP checkpoint |
| `evaluate_gsm8k.py` | 使用 vLLM-Ascend 做确定性生成评测 |
| `compare_gsm8k.py` | 对 before/after 做逐题配对比较 |
| `tests/test_workflow.py` | 不依赖 NPU 的数据、答案提取和统计回归测试 |

所有原有脚本路径、命令行参数和默认训练/评测配置保持不变。环境变量模板不会被脚本自动读取；
需要使用时复制到实验目录并显式 `source`，避免仓库更新覆盖实验配置。

## 快速检查

代码更新后先运行轻量检查：

```bash
python3 -m unittest discover \
  -s frameworks/verl/qwen36_gsm8k/sft/tests \
  -p 'test_*.py'

bash -n frameworks/verl/qwen36_gsm8k/sft/run_sft.sh
bash -n frameworks/verl/qwen36_gsm8k/sft/merge_fsdp_checkpoint.sh
bash -n frameworks/verl/dashboard/run_tensorboard.sh
bash -n frameworks/verl/kill.sh
```

环境和数据预检通过后的两步冒烟：

```bash
cd /workspace
export MODEL_PATH=/mnt/model/Qwen3.6-27B
export DATA_DIR=/mnt/data/gsm8k_sft
export SAVE_PATH=/mnt/data/checkpoints/qwen36-27b-gsm8k-sft-dry-run

DRY_RUN=1 DRY_RUN_STEPS=2 \
  bash frameworks/verl/qwen36_gsm8k/sft/run_sft.sh
```

脚本默认启用 `console` 与 `tensorboard` logger，TensorBoard 事件目录为
`/mnt/data/logs/verl_gsm8k_sft_1`。可以在命令行覆盖：

```bash
TENSORBOARD_DIR=/mnt/data/logs/my_sft_run \
DRY_RUN=0 \
  bash frameworks/verl/qwen36_gsm8k/sft/run_sft.sh
```

命令返回时会打印后台训练 PID、持久日志路径和 Dashboard 地址。

训练日志默认写入 `/mnt/data/logs/qwen36-27b-gsm8k-sft/<mode>-*.log`，不会持续输出到启动终端。
使用命令打印的完整日志路径查看实时进度：

```bash
tail -f /mnt/data/logs/qwen36-27b-gsm8k-sft/<mode>-<timestamp>-<pid>.log
```

此处按 `Ctrl+C` 只停止 `tail`，不会停止后台训练。后台进程结构、直接后台启动方式和停止语义见
[`dashboard/README.md`](../../dashboard/README.md)。

公共 Dashboard 也可以独立启动：

```bash
bash frameworks/verl/dashboard/run_tensorboard.sh
```

停止整机上所有匹配的 VERL 训练和 TensorBoard：

```bash
bash frameworks/verl/kill.sh
```

该停止命令也会影响机器上其他 VERL 实验和 TensorBoard 实例。

正式训练、断点续训、模型合并和完整评测按完整文档依次执行。
