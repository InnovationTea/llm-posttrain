# Ascend 910C veRL 镜像选型验证流程

本文档用于在同一台 Ascend 910C 服务器上，对不同 veRL 镜像进行标准化验证，并分别选择适合 SFT 和 RL/GRPO 的镜像。

核心原则：所有镜像必须使用相同的硬件、模型、数据、NPU 数量和训练参数。每次只运行一个待测镜像，测试结果写入独立目录。

`image-selection/benchmark/run_sft_benchmark.sh` 和 `run_grpo_benchmark.sh` 是统一的 benchmark 包装入口。它们负责检查参数、创建独立结果目录、记录环境信息，并调用 `frameworks/verl` 下已验证的训练脚本。

## 1. 准备测试对象

假设需要比较以下两个镜像：

```bash
IMAGE_A=quay.io/ascend/verl:image-a
IMAGE_B=quay.io/ascend/verl:image-b
```

宿主机准备固定的模型和数据：

```text
/mnt/model/Qwen3.6-27B       # 基础模型
/mnt/data/gsm8k_sft         # SFT 数据
/mnt/data/gsm8k             # GRPO 数据
```

确认所有镜像均使用上述同一份文件，不要在镜像之间重新生成或修改数据。

## 2. 启动待测镜像

在宿主机仓库目录执行。将 `/path/to/llm-posttrain` 替换为仓库实际路径：

```bash
cd /path/to/llm-posttrain

WORK_DIR="$PWD" bash infra/startContainer.sh \
  verl-image-a \
  '' \
  quay.io/ascend/verl:image-a
```

进入容器：

```bash
docker exec -it verl-image-a bash
cd /workspace
```

## 3. 基础兼容性检查

### 3.1 Ascend、BF16 和 HCCL 检查

```bash
bash infra/check_ascend_env.sh
```

通过标准：

- 识别全部预期 NPU；
- 所有 rank 均显示 `PASS`；
- BF16 前向和反向成功；
- HCCL AllReduce 成功；
- 没有报错或卡死。

### 3.2 模型、Tokenizer 和数据检查

```bash
python3 frameworks/verl/qwen36_gsm8k/sft/preflight.py \
  --model-path /mnt/model/Qwen3.6-27B \
  --data-dir /mnt/data/gsm8k_sft \
  --max-length 2048
```

任意一项检查失败时，先记录错误并停止该镜像的后续性能测试。

## 4. SFT 性能测试

在容器内的 `/workspace` 目录执行：

```bash
cd /workspace

IMAGE_ID=image-a \
bash image-selection/benchmark/run_sft_benchmark.sh
```

默认行为：

- 使用 `/mnt/model/Qwen3.6-27B`；
- 使用 `/mnt/data/gsm8k_sft`；
- 执行 20 个真实的 SFT optimizer step；
- 自动使用容器内全部可见 NPU；
- 将日志、环境信息、checkpoint 和状态写入独立目录。

需要指定路径或步数时使用：

```bash
IMAGE_ID=image-a \
MODEL_PATH=/mnt/model/Qwen3.6-27B \
DATA_DIR=/mnt/data/gsm8k_sft \
RESULT_ROOT=/mnt/data/image-benchmark \
BENCHMARK_STEPS=20 \
WARMUP_STEPS=5 \
RUN_ID=run-01 \
bash image-selection/benchmark/run_sft_benchmark.sh
```

其中 `IMAGE_ID` 是必填的镜像结果标签，只能包含字母、数字、点、下划线和连字符。`RUN_ID` 可省略，默认使用当前时间。`WARMUP_STEPS` 默认是 5，必须小于 `BENCHMARK_STEPS`。脚本拒绝覆盖已有结果目录。

输出目录格式：

```text
/mnt/data/image-benchmark/<IMAGE_ID>/sft/<RUN_ID>/
├── benchmark.env    # 本次 benchmark 参数
├── environment.txt  # 软件版本、CANN 和 npu-smi 信息
├── train.log        # 完整训练日志
├── summary.json     # 结构化指标，供自动汇总使用
├── summary.txt      # 可直接查看的简短指标摘要
├── checkpoint/      # dry-run checkpoint
├── exit_code        # 进程退出码；成功为 0
└── status           # PASS 或 FAIL
```

检查以下内容：

- 20 个 step 是否全部完成；
- 是否发生 NPU OOM、HCCL 或算子错误；
- loss 和 grad norm 是否为有限值；
- 每个 step 的耗时；
- 峰值 NPU 和 CPU 内存。

前几个 step 通常包含初始化和编译开销。解析器默认忽略前 5 个 step，使用第 6 至 20 个 step 计算平均耗时。运行结束后不需要打开完整日志，直接查看：

```bash
cat /mnt/data/image-benchmark/image-a/sft/run-01/summary.txt
```

示例输出：

```text
status: PASS
completed steps: 20 / 20
measured steps: 15 (warmup=5)
mean step time: 8.200 s
p95 step time: 8.700 s
samples/s: 3.902
samples/s/NPU: 0.244
effective tokens/s: unavailable
effective tokens/s/NPU: unavailable
severe errors: 0
non-finite loss/grad_norm: 0
```

`summary.json` 还包含 observed steps、loss、grad norm、日志中的显存峰值和无法计算指标的原因。解析器会检查：

- 是否观察到预期的最后一个 step；
- 是否出现 RuntimeError、OOM、HCCL timeout 等严重错误；
- loss 或 grad norm 是否出现 NaN/Inf；
- warmup 后的平均、P50/P95、最小和最大 step time；
- global batch 和 NPU 数量可用时的 `samples/s` 与 `samples/s/NPU`。

如果镜像日志没有输出 step time 或有效 token 数，对应字段会显示 `unavailable`，不会使用理论最大长度估算。

```text
SFT samples/s = global batch size / 平均 step 秒数
```

例如 global batch size 为 32，平均 step 时间为 8 秒：

```text
32 / 8 = 4 samples/s
```

对于包装脚本产生的旧日志，也可以单独运行解析器：

```bash
python3 image-selection/benchmark/parse_sft_metrics.py \
  --log-file /mnt/data/image-benchmark/image-a/sft/run-01/train.log \
  --output-file /mnt/data/image-benchmark/image-a/sft/run-01/summary.json \
  --text-output /mnt/data/image-benchmark/image-a/sft/run-01/summary.txt \
  --expected-steps 20 \
  --warmup-steps 5
```

## 5. GRPO 性能测试

当前 GRPO 脚本固定使用 16 个逻辑 NPU、TP=8、`n=4`，模型和数据路径分别为 `/mnt/model/Qwen3.6-27B` 和 `/mnt/data/gsm8k`。

```bash
cd /workspace

IMAGE_ID=image-a \
bash image-selection/benchmark/run_grpo_benchmark.sh
```

默认运行 20 个 GRPO step，并关闭 benchmark 期间的 checkpoint 和 validation。需要覆盖路径、步数或运行标签时使用：

```bash
IMAGE_ID=image-a \
MODEL_PATH=/mnt/model/Qwen3.6-27B \
DATA_DIR=/mnt/data/gsm8k \
RESULT_ROOT=/mnt/data/image-benchmark \
BENCHMARK_STEPS=20 \
WARMUP_STEPS=5 \
RUN_ID=run-01 \
bash image-selection/benchmark/run_grpo_benchmark.sh
```

输出目录格式：

```text
/mnt/data/image-benchmark/<IMAGE_ID>/grpo/<RUN_ID>/
├── benchmark.env
├── environment.txt
├── verl_grpo.log
├── summary.json
├── summary.txt
├── exit_code
└── status
```

GRPO 包装器会把模型、数据和总步数作为 Hydra 参数传入已验证的 `run_grpo.sh`。其他高级 Hydra 参数可以附加在命令末尾，例如：

```bash
IMAGE_ID=image-a \
bash image-selection/benchmark/run_grpo_benchmark.sh \
  actor_rollout_ref.rollout.gpu_memory_utilization=0.2
```

训练完成后直接查看摘要，不需要打开完整的 `verl_grpo.log`：

```bash
cat /mnt/data/image-benchmark/image-a/grpo/run-01/summary.txt
```

示例输出：

```text
status: PASS
completed steps: 20 / 20
measured steps: 15 (warmup=5)
mean step time: 264.920 s
p95 step time: 280.100 s
mean rollout time: 209.700 s
mean actor update time: 29.770 s
rollout output tokens/s: 52.844
rollout output tokens/s/NPU: 3.303
mean response length: 346.300
mean reward: 0.923
severe errors: 0
non-finite metrics: 0
```

解析器会汇总 warmup 后的以下指标：

- `timing_s/gen`、`old_log_prob`、`ref`、`update_actor`、`update_weights` 和 `step` 的平均值、P50/P95、最小值和最大值；
- `response_length/mean`、reward 和日志中的显存峰值；
- rollout output `tokens/s` 和 `tokens/s/NPU`；
- OOM、HCCL timeout、RuntimeError，以及 loss、grad norm、reward、advantage 的 NaN/Inf。

当前固定配置每个 step 生成 `8 × 4 = 32` 个 response，因此：

```text
每步 rollout output tokens = response_length/mean × 32
rollout output tokens/s = 所有统计 step 的 output tokens 总和 / timing_s/gen 总和
```

如果使用命令末尾的 Hydra 参数修改 `data.train_batch_size` 或 `actor_rollout_ref.rollout.n`，当前包装器摘要仍按固定的 8 和 4 计算，不能直接用于横向比较。标准镜像测试不要修改这两个参数。

对于已有 GRPO 日志，可以单独生成摘要：

```bash
python3 image-selection/benchmark/parse_grpo_metrics.py \
  --log-file /mnt/data/image-benchmark/image-a/grpo/run-01/verl_grpo.log \
  --output-file /mnt/data/image-benchmark/image-a/grpo/run-01/summary.json \
  --text-output /mnt/data/image-benchmark/image-a/grpo/run-01/summary.txt \
  --expected-steps 20 \
  --warmup-steps 5 \
  --prompt-batch-size 8 \
  --rollout-n 4 \
  --npu-count 16
```

建议至少采集 20 个完整 step，并忽略前 5 个 warmup step。重点比较日志中的以下指标：

```text
timing_s/gen
timing_s/old_log_prob
timing_s/ref
timing_s/update_actor
timing_s/update_weights
timing_s/step
```

指标含义：

- `timing_s/step`：完整 GRPO step 耗时，越低越好；
- `timing_s/gen`：rollout 生成耗时，越低越好；
- `timing_s/update_actor`：Actor 反向传播及更新耗时；
- `timing_s/update_weights`：Actor 权重同步至 rollout 引擎的耗时。

同时记录峰值显存，并检查是否出现 OOM、NaN、HCCL 错误或训练中断。

## 6. 离线推理与质量测试

以下测试用于获得生成质量和粗略的离线整批吞吐：

```bash
time python3 \
  /workspace/frameworks/verl/qwen36_gsm8k/sft/evaluate_gsm8k.py \
  --model-path /mnt/model/Qwen3.6-27B \
  --tokenizer-path /mnt/model/Qwen3.6-27B \
  --data-file /mnt/data/gsm8k_sft/test.parquet \
  --output-file /mnt/data/image-benchmark/image-a/eval.jsonl \
  --tensor-parallel-size 8 \
  --limit 128 \
  --no-enable-thinking
```

输出文件：

```text
/mnt/data/image-benchmark/image-a/eval.jsonl
/mnt/data/image-benchmark/image-a/eval.summary.json
```

粗略离线生成吞吐可按以下公式计算：

```text
生成吞吐 = 所有 completion_tokens 总数 / 命令总耗时
```

该结果是离线整批吞吐，不是首 token 延迟（TTFT）。准确测量 TTFT 需要启动 vLLM OpenAI-compatible 服务，并通过 streaming 客户端记录第一个非空 token chunk 的到达时间。

## 7. 测试下一个镜像

退出并停止第一个容器：

```bash
exit
docker stop verl-image-a
```

启动第二个镜像：

```bash
cd /path/to/llm-posttrain

WORK_DIR="$PWD" bash infra/startContainer.sh \
  verl-image-b \
  '' \
  quay.io/ascend/verl:image-b
```

完整重复第 3 至第 6 节。运行包装器时将 `IMAGE_ID` 改为：

```bash
IMAGE_ID=image-b \
bash image-selection/benchmark/run_sft_benchmark.sh

IMAGE_ID=image-b \
bash image-selection/benchmark/run_grpo_benchmark.sh
```

镜像之间不得修改以下条件：

- 模型和 tokenizer；
- 训练及评测数据；
- NPU 数量；
- global batch、micro batch；
- prompt、response 和 sequence 长度；
- TP、rollout 数量及其他并行参数；
- 随机种子和评测样本；
- warmup 和统计 step 范围。

## 8. 记录和比较结果

为每个镜像填写以下表格：

| 指标 | image-a | image-b |
| --- | ---: | ---: |
| 环境检查 | PASS/FAIL | PASS/FAIL |
| SFT 20 step | PASS/FAIL | PASS/FAIL |
| SFT 第 6-20 step 平均时间 | 秒 | 秒 |
| SFT samples/s | 数值 | 数值 |
| GRPO 20 step | PASS/FAIL | PASS/FAIL |
| GRPO 第 6-20 step 平均时间 | 秒 | 秒 |
| GRPO 平均 rollout 时间 | 秒 | 秒 |
| 峰值 NPU 显存 | GB | GB |
| GSM8K accuracy | 数值 | 数值 |
| OOM/NaN/HCCL 错误 | 有/无 | 有/无 |

## 9. 镜像选择规则

1. 基础检查、SFT 或 GRPO 失败的镜像直接淘汰。
2. SFT 优先选择 SFT 平均 step 时间最低、吞吐最高且显存稳定的镜像。
3. RL 优先选择 GRPO `timing_s/step` 和 `timing_s/gen` 最低的镜像。
4. SFT 和 RL 可以分别使用不同镜像，不要求强制统一。
5. 性能更快但准确率明显下降，或存在 NaN、OOM、HCCL 中断的镜像不能入选。

## 10. 当前流程的能力边界

当前流程能够比较：

- Ascend、BF16、HCCL 和 veRL 基础兼容性；
- SFT 和 GRPO 是否能稳定运行；
- SFT/GRPO step 耗时及粗略吞吐；
- GRPO 各阶段耗时；
- 离线生成质量和粗略整批吞吐。

当前尚未自动提供：

- 当 veRL 日志未输出每步有效 token 数时的 SFT 有效 `tokens/s` 和 `tokens/s/NPU`；
- TTFT、TPOT、ITL 和在线请求吞吐；
- 跨镜像 JSON/CSV 自动汇总和排名；
- 长时间稳定性和资源趋势报告。

后续可增加统一的 SFT/GRPO 日志解析、在线推理 benchmark、资源监控和镜像结果汇总脚本。
