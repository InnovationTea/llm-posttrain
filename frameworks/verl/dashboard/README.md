# VERL TensorBoard Dashboard

公共 TensorBoard 后台启动入口。默认读取 `/mnt/data/logs/verl`：

```bash
cd /workspace
bash frameworks/verl/dashboard/run_tensorboard.sh
```

可以在命令行指定事件目录、监听地址和端口：

```bash
TENSORBOARD_DIR=/mnt/data/logs/verl_gsm8k_grpo_1 \
TENSORBOARD_HOST=0.0.0.0 \
TENSORBOARD_PORT=6006 \
  bash frameworks/verl/dashboard/run_tensorboard.sh
```

脚本使用 `nohup tensorboard --logdir ...` 后台启动并打印 PID、URL 和服务日志路径。
脚本不依赖 `ss` 或 `lsof`。如果能从进程列表识别到同端口的 TensorBoard，脚本直接复用；
已有服务仍使用它启动时的 `--logdir`。其他情况会直接尝试启动 TensorBoard；如果端口冲突或
启动失败，脚本报错并给出 `${TENSORBOARD_DIR}/tensorboard.log` 日志路径。

## 后台进程与日志

执行 `run_sft.sh` 或 `run_grpo.sh` 时，启动脚本会创建两个相互独立的后台任务：

```text
启动脚本
├── TensorBoard 后台进程
└── VERL 训练后台进程
    └── torchrun、Ray、vLLM 或 NPU worker 子进程
```

两个训练脚本直接使用 `nohup torchrun ... &`（SFT）或 `nohup python3 ... &`（GRPO）启动
训练，不会创建后台 Bash worker。启动时打印的训练 PID 就是 `torchrun` 或 Python 主训练进程的 PID。

启动脚本只在终端打印训练 PID、训练日志路径和 Dashboard 地址，训练过程不再持续输出到启动终端。
TensorBoard 控制台日志写入 `${TENSORBOARD_DIR}/tensorboard.log`；训练日志目录由具体训练脚本说明。
可以使用启动时打印的路径实时查看训练日志：

```bash
tail -f /path/from/Training-log
```

在 `tail -f` 中按 `Ctrl+C` 只会退出日志查看，不会停止训练。启动脚本已经返回后，在原终端
按 `Ctrl+C` 同样不会停止训练，因为训练已经通过 `nohup ... &` 与终端分离。

停止整机上所有匹配的 VERL 训练和 TensorBoard：

```bash
bash frameworks/verl/kill.sh
```

该停止命令会同时影响机器上其他 VERL 实验和 TensorBoard 实例。
