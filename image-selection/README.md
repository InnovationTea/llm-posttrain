# Ascend 910C veRL 镜像选型验证流程

本文档用于在同一台 Ascend 910C 服务器上，对不同 veRL Docker 镜像进行标准化验证，并分别选择适合 SFT 和 GRPO 的镜像。

## 1. 设计原则

benchmark 必须从宿主机发起。用户只提供 Docker image，宿主机脚本负责：

```text
生成唯一 Benchmark ID
  -> 拉取并启动唯一临时容器
  -> Ascend/BF16/HCCL 检查
  -> 模型和数据预检
  -> SFT 和/或 GRPO 固定负载测试
  -> 解析日志并生成 summary
  -> 停止并删除临时容器
```

同一个 image 可以被多次或被多个容器测试。结果不使用 image 名称作为唯一键，而使用每次运行独立的 `BENCHMARK_ID`。image ref、不可变 image ID/digest 和 container name 作为元数据记录。

## 2. 准备条件

在 Ascend 910C 宿主机准备：

```text
/mnt/model/Qwen3.6-27B       # 基础模型
/mnt/data/gsm8k_sft         # SFT train/validation/test 数据
/mnt/data/gsm8k             # GRPO train/test 数据
```

仓库可以位于任意宿主机目录，但必须通过该仓库中的宿主机入口启动测试。Docker、Ascend 驱动设备和 `npu-smi` 必须在宿主机可用。

所有待比较镜像必须使用相同的服务器、模型、数据、NPU 数量、batch、序列长度、训练步数和 warmup 步数。

## 3. 一条命令运行

进入宿主机仓库目录，不要进入容器：

```bash
cd /path/to/llm-posttrain
```

只测试 SFT：

```bash
bash image-selection/benchmark/run_image_benchmark.sh \
  quay.io/ascend/verl:<image-tag> \
  sft
```

只测试 GRPO：

```bash
bash image-selection/benchmark/run_image_benchmark.sh \
  quay.io/ascend/verl:<image-tag> \
  grpo
```

依次测试 SFT 和 GRPO：

```bash
bash image-selection/benchmark/run_image_benchmark.sh \
  quay.io/ascend/verl:<image-tag> \
  all
```

脚本会自动拉取本地不存在的 image。默认使用宿主机全部 `/dev/davinci*` 设备。当前 GRPO workload 固定需要 16 个逻辑 NPU。

SFT 可以在第三个参数指定设备，例如：

```bash
bash image-selection/benchmark/run_image_benchmark.sh \
  quay.io/ascend/verl:<image-tag> \
  sft \
  0,1,2,3
```

## 4. 自定义参数

默认参数：

```text
RESULT_ROOT=/mnt/data/image-benchmark
MODEL_PATH=/mnt/model/Qwen3.6-27B
SFT_DATA_DIR=/mnt/data/gsm8k_sft
GRPO_DATA_DIR=/mnt/data/gsm8k
BENCHMARK_STEPS=20
WARMUP_STEPS=5
KEEP_CONTAINER=0
```

覆盖示例：

```bash
MODEL_PATH=/mnt/model/Qwen3.6-27B \
SFT_DATA_DIR=/mnt/data/gsm8k_sft \
GRPO_DATA_DIR=/mnt/data/gsm8k \
BENCHMARK_STEPS=20 \
WARMUP_STEPS=5 \
bash image-selection/benchmark/run_image_benchmark.sh \
  quay.io/ascend/verl:<image-tag> \
  all
```

正常情况下不要手工设置 `BENCHMARK_ID` 和 `CONTAINER_NAME`。脚本自动组合 UTC 时间、宿主机进程 ID 和随机数，因此同一 image 的多次测试不会覆盖。

故障排查时需要保留临时容器：

```bash
KEEP_CONTAINER=1 \
bash image-selection/benchmark/run_image_benchmark.sh \
  quay.io/ascend/verl:<image-tag> \
  sft
```

脚本会打印实际 container name。排查结束后在宿主机显式删除：

```bash
docker rm -f <container-name>
```

## 5. 自动执行的门禁

### 5.1 Ascend 环境检查

自动执行：

```bash
bash infra/check_ascend_env.sh
```

检查 NPU 可见性、BF16 前后向、有限值和 HCCL AllReduce。任何 rank 失败时，preflight 和训练测试均不执行。

### 5.2 模型和数据预检

SFT 或 `all` 模式检查模型、tokenizer、chat template 和完整 SFT 数据。GRPO-only 模式只检查模型元数据和 tokenizer，不要求 SFT 数据存在。

### 5.3 训练负载

门禁通过后执行固定 20 step，默认忽略前 5 step 的初始化和编译开销：

- SFT：BF16 全参数 FSDP 训练；
- GRPO：vLLM rollout、log probability、reward/advantage、actor 更新和权重同步。

## 6. 唯一结果目录

每次宿主机运行生成：

```text
/mnt/data/image-benchmark/<BENCHMARK_ID>/
├── run.env                    # image、digest、container 和参数
├── status                     # 整次 image benchmark 的 PASS/FAIL
├── exit_code                  # 成功为 0，失败为 1
├── checks/
│   ├── ascend.log
│   ├── ascend.status
│   ├── preflight.log
│   └── preflight.status
├── sft/                       # 运行 SFT 时生成
│   ├── benchmark.env
│   ├── environment.txt
│   ├── train.log
│   ├── summary.json
│   ├── summary.txt
│   ├── checkpoint/
│   ├── exit_code
│   └── status
└── grpo/                      # 运行 GRPO 时生成
    ├── benchmark.env
    ├── environment.txt
    ├── verl_grpo.log
    ├── summary.json
    ├── summary.txt
    ├── exit_code
    └── status
```

`run.env` 用于区分“相同 image 的不同容器和不同运行”，例如：

```text
benchmark_id=benchmark-20260803T021500Z-12345-28761
image_ref=quay.io/ascend/verl:some-tag
image_id=sha256:...
image_repo_digests=quay.io/ascend/verl@sha256:...
container_name=verl-bench-20260803T021500Z-12345-28761
```

## 7. 查看结果

宿主机运行结束后，脚本会打印结果目录。先查看总状态：

```bash
cat /mnt/data/image-benchmark/<BENCHMARK_ID>/status
cat /mnt/data/image-benchmark/<BENCHMARK_ID>/exit_code
```

查看 SFT 摘要：

```bash
cat /mnt/data/image-benchmark/<BENCHMARK_ID>/sft/summary.txt
```

主要指标：

- 是否完成预期 step；
- warmup 后 step time 的平均值和 P95；
- `samples/s` 和 `samples/s/NPU`；
- 日志提供有效 token 数时的 `tokens/s`；
- loss、grad norm、OOM、HCCL 和 NaN/Inf。

查看 GRPO 摘要：

```bash
cat /mnt/data/image-benchmark/<BENCHMARK_ID>/grpo/summary.txt
```

主要指标：

- 完整 step、rollout、actor update、log probability 和权重同步耗时；
- rollout output `tokens/s` 和 `tokens/s/NPU`；
- response length、reward、显存和异常。

GRPO 固定配置每 step 生成 `8 × 4 = 32` 个 response：

```text
rollout output tokens/s
  = 所有统计 step 的 (response_length/mean × 32) 总和
    / 所有统计 step 的 timing_s/gen 总和
```

如果训练在解析器执行前失败，可能只有大日志而没有 `summary.*`。此时先查看对应 workload 的 `status` 和日志末尾 traceback。

## 8. 多个 image 的批量测试

对多个 image 使用循环。每个调用都会创建自己的容器和唯一结果目录：

```bash
while IFS= read -r image; do
  [[ -z "${image}" || "${image}" == \#* ]] && continue
  bash image-selection/benchmark/run_image_benchmark.sh "${image}" all
done < images.txt
```

`images.txt` 示例：

```text
quay.io/ascend/verl:image-a
quay.io/ascend/verl:image-b
quay.io/ascend/verl:image-c
```

同一台服务器使用全部 NPU 时必须顺序执行，不能并行运行多个训练容器。只有明确划分互不重叠的 NPU，并且 workload 支持该 NPU 数量时才能并行。

## 9. 选择规则

1. Ascend、preflight 或对应训练 workload 失败的 image 不进入该 workload 的性能排名。
2. SFT 优先比较有效 `tokens/s`；日志不提供 token 数时比较 `samples/s`、step time 和显存。
3. GRPO 优先比较端到端 step time、rollout output `tokens/s` 和显存。
4. SFT 和 GRPO 可以选择不同 image。
5. 性能更快但出现准确性回退、NaN、OOM、HCCL 中断或设备异常的 image 不能入选。

## 10. 内部脚本

以下脚本由宿主机编排器在临时容器中调用，通常不应手工执行：

```text
image-selection/benchmark/run_sft_benchmark.sh
image-selection/benchmark/run_grpo_benchmark.sh
image-selection/benchmark/parse_sft_metrics.py
image-selection/benchmark/parse_grpo_metrics.py
```

当前尚未自动提供 TTFT、TPOT、ITL、在线请求吞吐、跨镜像排名以及长时间资源趋势报告。
