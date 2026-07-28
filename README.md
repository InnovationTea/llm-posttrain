# LLM Post-Training

Ascend 910 上进行 LLM SFT 与 RL 实验的训练仓库。当前以 `verl` 为首个训练框架。

## 容器镜像

默认使用 Ascend 维护的 verl 镜像：

- 镜像仓库：[quay.io/ascend/verl](https://quay.io/repository/ascend/verl)
- 当前默认镜像：`quay.io/ascend/verl:verl-8.5.0-a3-ubuntu22.04-py3.11-v0.7.1`

镜像 tag 由 [`infra/startContainer.sh`](infra/startContainer.sh) 中的
`DEFAULT_IMAGE` 控制。如需使用其他 tag，可作为脚本的第三个参数传入。

## 启动容器

启动脚本会挂载指定的 Ascend NPU、宿主机驱动与 `npu-smi`，并将本仓库挂载到容器内的
`/workspace`。脚本默认使用全部可用 NPU。

```bash
# 使用所有 NPU 和默认 verl 镜像
bash infra/startContainer.sh verl-train

# 只使用 NPU 0 和 1
bash infra/startContainer.sh verl-train-01 0,1

# 使用指定镜像
bash infra/startContainer.sh verl-train '' quay.io/ascend/verl:<tag>
```

脚本中的 `WORK_DIR` 默认为 `/root/workspace`；请在运行前将其改为本仓库在训练机上的绝对路径。

## 宿主机挂载

训练产物不写入 Git 仓库。当前容器将以下宿主机路径直接挂载：

| 宿主机路径 | 容器路径 | 用途 |
| --- | --- | --- |
| `/mnt/model` | `/mnt/model` | 基座模型与 tokenizer |
| `/mnt/data` | `/mnt/data` | SFT/RL 训练数据 |
| 当前仓库的 `WORK_DIR` | `/workspace` | 配置、脚本与代码 |

训练前请确认宿主机执行 `npu-smi info` 能识别到期望的 Ascend 910 卡，并在容器内复查设备可见性。
