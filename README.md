# LLM Post-Training

Ascend 910 上进行 LLM SFT 与 RL 实验的训练仓库。当前以 `verl` 为首个训练框架。

## 已验证实验

- [Qwen3.6-27B GSM8K SFT 完整流程](docs/qwen36_gsm8k_sft.md)
- [Qwen3.6-27B GSM8K GRPO 训练脚本](frameworks/verl/qwen36_gsm8k/rl/run_grpo.sh)
- [Qwen3.6-27B GRPO 21-step 验证报告](docs/qwen36_gsm8k_grpo_validation.md)

## CreateMyCard

- [业务总览](frameworks/verl/create_my_card/README.md)
- [Design Compact 数据生产与转换流程](frameworks/verl/create_my_card/data_pipeline/README.md)
- [veRL SFT 数据构建与训练](frameworks/verl/create_my_card/sft/README.md)
- [数据合同与质检文档](docs/create_my_card/data-quality-spec.md)

全部主题入口见 [docs/README.md](docs/README.md)。

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

进入容器后先执行 Ascend 环境检查。脚本会自动使用全部可见 NPU，验证 BF16 前后向和
HCCL AllReduce：

```bash
cd /workspace
bash infra/check_ascend_env.sh
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

## 离线拉取镜像

[`infra/docker_pull.sh`](infra/docker_pull.sh) 是一个独立实现的 Docker Registry HTTP API v2 拉取工具，
参考了 [NotGlop/docker-drag](https://github.com/NotGlop/docker-drag) 的使用场景，但不包含其代码。
它将镜像保存为 OCI image layout tar；Docker 20.10 及以上版本可通过 `docker load` 导入。

运行环境需要 `bash`、`curl`、`jq` 和 GNU userland（包括 `sha256sum`、`tar`、`stat`、`date`、
`awk`、`sed`、`tr`）。下载完成后，脚本会校验每个 blob 的大小和 SHA-256 digest。

```bash
# 默认在当前目录创建 OCI archive
bash infra/docker_pull.sh quay.io/ascend/verl:verl-8.5.0-a3-ubuntu22.04-py3.11-v0.7.1

# 指定 archive 的保存路径，再导入 Docker
DOCKER_PULL_OUTPUT=/mnt/model/verl.oci.tar \
  bash infra/docker_pull.sh quay.io/ascend/verl:verl-8.5.0-a3-ubuntu22.04-py3.11-v0.7.1
docker load -i /mnt/model/verl.oci.tar
```

每个 layer 下载时会显示已下载大小、总大小、百分比和从该 layer 开始下载起计算的平均速度，例如：

```text
9f3a12bc4567: [============            ]  50% 2.0 GiB / 4.0 GiB 83.7 MiB/s
```

默认平台由当前机器架构推断为 `linux/amd64` 或 `linux/arm64`。拉取 multi-arch 镜像的其他平台时，
可显式指定 `DOCKER_PULL_PLATFORM`：

```bash
DOCKER_PULL_PLATFORM=linux/arm64 \
  bash infra/docker_pull.sh quay.io/namespace/image:tag
```

速度与进度辅助函数的离线测试可用以下命令执行：

```bash
bash infra/tests/docker_pull_test.sh
```
