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

## GitHub Release 离线镜像

[`infra/images/images.json`](infra/images/images.json) 是 Release 镜像清单。每个条目
使用稳定的 `id`、带 tag 或 digest 的公开 Registry `reference`，以及需要生成的
`platforms`。发布工作流通过手动 `workflow_dispatch` 触发：更新清单并提交到要发布
的分支后，在 GitHub Actions 中运行 `Release Image Assets`，选择该分支，并输入一个
此前未发布的 `release_tag`，例如 `v0.1.0`。

工作流会在所选分支的 HEAD 创建并推送 annotated Git tag，创建同名 Draft Release，
通过 GitHub 的自动生成功能写入 Release notes，然后为清单中的每个镜像和平台生成
离线 OCI archive。所有资产上传成功后，Draft Release 才会发布。镜像 archive 通常
大于 GitHub 单附件 2 GiB 上限，因此发布的是 1.9 GiB 以下的分卷，而不是完整 tar。
工作流失败时 tag 和 Draft Release 会保留；使用同一分支提交和同一 `release_tag`
重试可继续完成。已发布的 Release 不会被工作流覆盖。

Release 附件包括各平台的 `.oci.tar.part-000` 分卷、`SHA256SUMS.parts`、
`SHA256SUMS.archives`、`release-images.json` 和 `load-image.sh`。只下载训练机
架构对应的所有分卷及这几个公共文件。例如，导入 `ascend-verl` 的 amd64 版本：

```bash
# 下载 ascend-verl--linux-amd64 的所有 part 文件和上述校验、脚本文件后执行。
bash load-image.sh ascend-verl linux/amd64 .
```

脚本会先校验分卷，重建 archive，再校验 archive 并执行 `docker load`。如需手动
执行同样的过程：

```bash
grep 'ascend-verl--linux-amd64.oci.tar.part-' SHA256SUMS.parts | sha256sum -c -
cat ascend-verl--linux-amd64.oci.tar.part-* > ascend-verl--linux-amd64.oci.tar
grep 'ascend-verl--linux-amd64.oci.tar$' SHA256SUMS.archives | sha256sum -c -
docker load -i ascend-verl--linux-amd64.oci.tar
```
