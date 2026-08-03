# Qwen3.6-27B GSM8K

本目录按训练范式拆分为两个相互独立的入口：

| 目录 | 内容 |
| --- | --- |
| [`sft/`](sft/) | 全参数 SFT 数据准备、训练、checkpoint 合并和前后评测 |
| [`rl/`](rl/) | 基于 veRL 与 vLLM-Ascend 的全参数 GRPO 训练入口 |

两套流程共享模型和 GSM8K 任务背景，但使用不同的数据格式、训练入口和实验结论，运行时不要混用 Parquet 文件。

SFT 和 GRPO 训练脚本均会启动公共
[`dashboard/run_tensorboard.sh`](../dashboard/run_tensorboard.sh)，随后将训练放到后台运行。
公共 Dashboard 的独立启动方法和端口复用规则见 [`dashboard/README.md`](../dashboard/README.md)。
