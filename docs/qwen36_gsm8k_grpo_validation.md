# Qwen3.6-27B GRPO 训练验证报告

- 源日志：`verl_grpo.log`（外部训练产物，未纳入仓库）
- 训练脚本：[`frameworks/verl/qwen36_gsm8k/rl/run_grpo.sh`](../frameworks/verl/qwen36_gsm8k/rl/run_grpo.sh)
- 统计范围：Global Step 1～21
- 训练任务：GSM8K 规则奖励 GRPO
- 验证性质：训练链路与资源适配冒烟测试

## 1. 结论摘要

本次验证成功跑通 Qwen3.6-27B 在 16 个逻辑 NPU 上的完整 GRPO 流程，包括：

- vLLM rollout 生成；
- GSM8K 奖励计算；
- GRPO advantage 计算；
- Reference KL 计算；
- Actor 全参数反向更新；
- FSDP2 参数、优化器和激活 offload；
- Actor 权重同步至 rollout 引擎。

前 21 步未出现 NPU OOM、NaN、通信中断或训练崩溃，工程验证通过。

但 GSM8K 对当前模型明显偏简单，至少 12/21 个 step 没有 GRPO 策略梯度。继续完整训练 934 step 的有效计算比例较低，不建议将当前数据配置直接作为正式训练方案。

## 2. 训练配置

| 配置项 | 当前值 |
|---|---:|
| 模型 | Qwen3.6-27B，27.36B 参数 |
| 设备 | 16 个逻辑 NPU |
| 单 NPU 显存 | 61.27GB |
| Actor 并行 | FSDP2，16 卡 |
| Rollout 并行 | 2 组 TP=8 vLLM 实例 |
| Prompt batch | 8 |
| 每个 Prompt 采样数 | 4 |
| 每步 rollout 数量 | 32 |
| 最大 Prompt 长度 | 512 tokens |
| 最大 Response 长度 | 1024 tokens |
| 最大序列长度 | 1536 tokens |
| Thinking | 关闭 |
| 学习率 | `5e-7` |
| KL loss 系数 | `0.001` |
| 总训练步数 | 934 |
| Checkpoint 间隔 | 900 step |
| 验证间隔 | 关闭 |

## 3. 核心训练指标

21 个 step 共生成：

```text
21 × 8 × 4 = 672 个回答
```

根据二元 GSM8K 奖励统计，其中约 620 个回答获得正确奖励，52 个回答未获得奖励。

| 指标 | 统计结果 |
|---|---:|
| 平均训练奖励 | 0.9226 |
| 最低单步平均奖励 | 0.71875 |
| 最高单步平均奖励 | 1.0 |
| 有明显策略梯度的 step | 9/21 |
| Advantage 全零的 step | 12/21，57.1% |
| 全部回答正确的 step | 9/21 |
| 平均 KL loss | 0.001273 |
| 最大 KL loss | 0.003810 |
| 初始 entropy | 0.0809 |
| step 21 entropy | 0.0488 |

KL 保持在较低水平，没有出现 KL 爆炸。`pg_clipfrac=0`，结合较小学习率，表明当前参数更新幅度较为保守。

Entropy 有下降迹象，但只有 21 个观测点，暂不能判断发生了熵坍缩。

## 4. GRPO 有效性分析

训练已经产生过正常的 GRPO 更新。例如 step 1：

```text
rewards/min: 0
rewards/max: 1
advantages/min: -0.499999
advantages/max: 1.499997
pg_loss: 0.016817
grad_norm: 0.472261
```

说明同一 prompt 的不同 rollout 出现对错差异，GRPO 能计算相对优势并更新策略。

以下 step 的 advantage 全零：

```text
4, 5, 6, 8, 10, 12, 13, 15, 17, 19, 20, 21
```

其中部分 step 全部回答正确：

```text
rewards/min = rewards/max = 1
```

还有部分 step 总体同时存在 0 和 1 奖励，但 advantage 仍为零。这意味着不同 prompt 的难度不同，但同一个 prompt 的 4 个 rollout 要么全对、要么全错，组内仍没有可比较信号。

因此，57.1% 是“整个 step 都没有策略优势”的比例；如果统计每个 prompt group，实际零方差组比例可能更高。

这是标准 GRPO 的零方差问题：[veRL](https://github.com/volcengine/verl) 对相同奖励组会产生零策略梯度。相关论文：[HybridFlow: A Flexible and Efficient RLHF Framework](https://arxiv.org/abs/2409.19256)。

## 5. 生成长度分析

| 指标 | 结果 |
|---|---:|
| 平均 Response 长度 | 346.3 tokens |
| 最大 Response 长度 | 1024 tokens |
| 出现截断的 step | 7/21 |
| 平均截断比例 | 2.38% |
| 最大单步截断比例 | 15.625% |
| Aborted ratio | 0 |

相比之前所有回答都在 256 token 截断，当前配置已经明显修复：

```text
旧配置 clip_ratio = 100%
当前平均 clip_ratio = 2.38%
```

长度 1024 基本合理，暂时不需要扩大。个别长回答导致 step 耗时显著增加，但总体截断率尚可接受。

## 6. 资源使用情况

| 指标 | 最大值 |
|---|---:|
| Actor NPU allocated | 35.23GB |
| Actor NPU reserved | 46.51GB |
| 单 NPU 总显存 | 61.27GB |
| Reserved 占比 | 75.9% |
| 按 reserved 计算的余量 | 约 14.76GB |
| CPU memory used 指标 | 1144.81GB |

NPU 显存配置当前稳定，仍有一定余量，但不适合大幅增加 batch、rollout 并发和响应长度。

CPU 内存指标较高，主要与参数、优化器和激活 offload 有关。其在前期快速上升后基本稳定，当前日志没有明确显示持续泄漏，但正式长时间训练仍需监控：

```bash
free -h
cat /sys/fs/cgroup/memory.events
```

## 7. 性能分析

| 阶段 | 平均耗时 | 占比 |
|---|---:|---:|
| Rollout 生成 | 209.70 秒 | 79.2% |
| Actor 更新 | 29.77 秒 | 11.2% |
| Old log probability | 11.30 秒 | 4.3% |
| Reference log probability | 4.28 秒 | 1.6% |
| 权重同步 | 9.87 秒 | 3.7% |
| 单步总耗时 | 264.92 秒 | 100% |

当前性能瓶颈是 rollout，而不是反向训练。

按照前 21 步平均速度，完成 934 step 预计需要：

```text
264.92 × 934 ÷ 3600 ≈ 68.7 小时
```

约 2.9 天，不含启动和 checkpoint 保存时间。

由于至少 57.1% step 没有策略优势，当前有效训练时间利用率偏低。

## 8. 风险与限制

本次验证不能证明模型能力已经提高，原因包括：

- 只运行了 21/934 step；
- `trainer.test_freq=-1`，没有验证集指标；
- 基线奖励已经达到约 92.3%，提升空间有限；
- 大量 prompt group 奖励零方差；
- 尚未保存 checkpoint；
- 单一随机种子和少量 step 无法判断长期稳定性。

日志中的 MFU 为 0，是因为当前 veRL 未支持 Qwen3_5 架构的 MFU 统计，不表示 NPU 没有计算。

## 9. 后续建议

1. 将本次实验作为 GRPO 工程链路验证，不继续完整训练当前 GSM8K 配置。
2. 正式训练改用更难且成功率处于约 10%～90% 区间的数据，如 MATH 高难度子集、AIME/AMC 或自有困难数学数据。
3. 记录每个 prompt group 的 reward 标准差或零方差比例，过滤或降低全对、全错 group 的采样权重。
4. 正式实验必须加入固定验证集，至少记录训练前、训练中和训练后的准确率。
5. 若优化吞吐，优先提升 rollout 并发或控制超长回答；不要先扩大训练 micro batch。
6. 持续监控 CPU 内存和 cgroup OOM 事件。

## 10. 最终判断

| 验证项 | 结论 |
|---|---|
| GRPO 链路 | 通过 |
| 16 NPU 分布式训练 | 通过 |
| FSDP2/offload 显存适配 | 通过 |
| 1024-token 生成配置 | 通过 |
| 奖励函数工作状态 | 通过 |
| 策略梯度有效性 | 部分通过 |
| GSM8K 数据难度 | 不适合正式训练 |
| 性能效率 | Rollout 瓶颈明显 |
| 能力提升结论 | 尚不能得出 |

本次实验可定义为：

> Qwen3.6-27B 在 A3 服务器上完成 veRL GRPO 全参数训练链路验证，资源配置稳定，奖励和梯度计算正确；但 GSM8K 难度低于模型当前能力，导致大量零方差 rollout，后续应使用更困难且成功率分布更合理的数据集进行正式训练。

## 附录 A：实验参数声明

### A.1 参数来源与适用范围

本报告中的实验参数以 `verl_grpo.log` 启动阶段打印的 Hydra 最终配置和 vLLM 实际启动参数为准，而不是仅依据启动脚本推测。统计结果仅覆盖日志中完整记录的 Global Step 1～21。

未在启动命令中显式覆盖的参数沿用当前 veRL、Transformers、vLLM Ascend 和模型目录中的默认值。由于软件默认值可能随版本变化，本报告中的结论不应无条件外推到其他镜像、框架版本或硬件环境。

### A.2 硬件与并行参数

| 参数 | 实验值 | 说明 |
|---|---:|---|
| 服务器 | A3，8 张物理卡、双芯 | 系统暴露为 16 个逻辑 NPU |
| 逻辑 NPU 数量 | 16 | `ASCEND_RT_VISIBLE_DEVICES=0,...,15` |
| 单逻辑 NPU 显存 | 61.27GB | 取自运行日志 |
| 总可见显存 | 约 980.32GB | `61.27 × 16`，通常按约 1TB 描述 |
| Actor 并行策略 | FSDP2 | 16 个逻辑 NPU 参与参数分片 |
| Rollout TP | 8 | 每个 vLLM 实例占用 8 个逻辑 NPU |
| Rollout 实例数 | 2 | 由 16 个逻辑 NPU 和 TP=8 推断，日志亦显示两个服务地址 |
| Rollout 最大并发序列 | 每实例 4 | `max_num_seqs=4` |
| vLLM 显存利用率参数 | 0.15 | 用于控制 rollout 引擎显存池，不等于整卡实时利用率 |
| 强制 Eager 模式 | 开启 | 提高 Ascend 兼容性，但关闭部分编译和图优化 |

### A.3 数据与采样参数

| 参数 | 实验值 |
|---|---:|
| 训练集 | `/mnt/data/gsm8k/train.parquet` |
| 验证集 | `/mnt/data/gsm8k/test.parquet` |
| Prompt batch size | 8 |
| 每个 Prompt 的 rollout 数量 | 4 |
| 每个 Global Step 的回答数 | 32 |
| 最大 Prompt 长度 | 512 tokens |
| 最大 Response 长度 | 1024 tokens |
| 最大单序列长度 | 1536 tokens |
| vLLM batched-token 上限 | 2048 |
| Thinking 模式 | 关闭，`enable_thinking=False` |
| Rollout seed | 0 |
| 数据加载 worker | 0 |

其中：

```text
每步回答数 = train_batch_size × rollout_n = 8 × 4 = 32
```

`max_num_batched_tokens=2048` 是 vLLM 调度预算，不代表单条序列可生成 2048 tokens。单条序列仍受 `max_model_len=1536` 和 `max_response_length=1024` 限制。

### A.4 优化与显存参数

| 参数 | 实验值 |
|---|---:|
| 优化对象 | Actor 全参数 |
| Actor 学习率 | `5e-7` |
| PPO mini batch size | 8 |
| 每 NPU micro batch size | 1 |
| PPO epoch | 1 |
| Advantage estimator | GRPO |
| KL 使用方式 | 加入 Actor loss |
| KL loss 系数 | `0.001` |
| KL 类型 | `low_var_kl` |
| KL reward penalty | 关闭 |
| Gradient checkpointing | 开启 |
| Activation offload | 开启 |
| Actor parameter offload | 开启 |
| Actor optimizer offload | 开启 |
| Reference parameter offload | 开启 |
| 总训练 epoch | 1 |
| 总 Global Step | 934 |
| Checkpoint 保存频率 | 900 step |
| Actor checkpoint 最多保留数 | 1 |
| 训练中验证 | 关闭，`test_freq=-1` |

## 附录 B：指标口径声明

### B.1 奖励与 GRPO 指标

| 日志指标 | 本报告采用的含义 |
|---|---|
| `critic/score/*` | 奖励函数输出的原始分数。本实验中与最终 reward 一致 |
| `critic/rewards/*` | 用于计算 GRPO advantage 的最终奖励 |
| `critic/advantages/*` | 同一 Prompt 的多个 rollout 经组内比较后得到的相对优势 |
| `critic/returns/*` | 当前无 critic 的 GRPO 配置下，与用于策略更新的回报量对应 |
| `actor/pg_loss` | 奖励优势产生的策略梯度损失 |
| `actor/kl_loss` | 当前 Actor 与 Reference 模型的 KL 约束项 |
| `actor/loss` | 策略损失与加权 KL 等项组合后的总 Actor loss |
| `actor/grad_norm` | Actor 更新前后的梯度范数监控值 |
| `actor/entropy` | 采样策略的 token 分布熵，用于观察随机性和潜在坍缩 |
| `actor/pg_clipfrac` | 触发 PPO ratio clipping 的 token 比例 |

本实验奖励值表现为 0 或 1，因此报告将其解释为 GSM8K 回答未通过或通过规则校验。若后续修改奖励函数并引入格式奖励、部分奖励或长度奖励，则不能继续把平均 reward 直接解释为准确率。

### B.2 “有效策略梯度”的判定

本报告将满足以下条件的 step 视为存在明显 GRPO 策略信号：

```text
advantages/min 与 advantages/max 不同时为 0
且 actor/pg_loss 不为 0
```

当：

```text
advantages/min = advantages/max = 0
actor/pg_loss = 0
```

该 step 不产生由奖励差异驱动的策略梯度。但如果 `actor/kl_loss` 不为 0，`actor/grad_norm` 仍可能出现约 `1e-3` 的小值，这属于 KL 约束带来的更新，不能解释为 GRPO 奖励学习信号。

本报告统计出 12/21 个 step 的 advantage 全零。这是 step 级统计下界，并非精确的 prompt-group 零方差比例：其余 9 个 step 内也可能同时包含若干零方差 group，但当前日志没有逐 group 输出，无法精确计算。

### B.3 回答长度指标

| 日志指标 | 含义 |
|---|---|
| `response_length/mean` | 当前 step 32 个回答的平均 token 数 |
| `response_length/max` | 当前 step 最长回答的 token 数 |
| `response_length/min` | 当前 step 最短回答的 token 数 |
| `response_length/clip_ratio` | 达到 `max_response_length` 上限的回答比例 |
| `response/aborted_ratio` | 因异常或调度原因被中止的回答比例 |

例如 step 3 的 `clip_ratio=0.15625`，对应：

```text
0.15625 × 32 = 5 个回答达到 1024-token 上限
```

### B.4 时间指标

| 日志指标 | 含义 |
|---|---|
| `timing_s/gen` | 当前 step 的 rollout 生成耗时 |
| `timing_s/old_log_prob` | 计算采样策略旧 log probability 的耗时 |
| `timing_s/ref` | Reference 模型 log probability 计算耗时 |
| `timing_s/update_actor` | Actor 反向传播和优化器更新耗时 |
| `timing_s/update_weights` | 将更新后的 Actor 权重同步至 rollout 引擎的耗时 |
| `timing_s/step` | 当前 Global Step 的端到端耗时 |

所有平均时间均为 step 1～21 的算术平均。总训练耗时估算采用：

```text
平均 step 时间 × 934
```

该估算不包含模型初始化、checkpoint 保存、验证、异常重试和最终退出清理时间，因此只能作为线性外推参考。

### B.5 显存与内存指标

| 日志指标 | 含义与限制 |
|---|---|
| `max_memory_allocated_gb` | PyTorch NPU allocator 已分配给有效 tensor 的峰值 |
| `max_memory_reserved_gb` | PyTorch NPU allocator 已保留的峰值，包括未被有效 tensor 占用的缓存 |
| `cpu_memory_used_gb` | veRL 记录的主机内存使用指标，可能包含节点其他进程和系统缓存，不等同于当前 Python 主进程 RSS |

`reserved` 小于单 NPU 总显存只能说明当前已记录阶段存在一定 allocator 余量，不能保证后续长序列、checkpoint 保存或其他并发任务不会 OOM。

### B.6 MFU 与吞吐指标

日志提示当前 veRL 的 MFU 计算不支持 `qwen3_5` 架构，因此：

```text
perf/mfu/actor = 0
```

仅代表 MFU 统计不可用，不代表 NPU 实际利用率为 0。

`perf/throughput` 为框架内部吞吐指标。由于当前日志未同时声明该字段的完整单位和归一化口径，本报告不将其用于与 GPU、其他模型或其他框架做横向性能比较。

## 附录 C：统计方法与结论边界

### C.1 统计公式

本报告使用以下计算：

```text
总 rollout 数 = 21 × 8 × 4 = 672
推断通过数 = Σ(step_reward_mean × 32) = 620
推断未通过数 = 672 - 620 = 52
平均 reward = Σ(step_reward_mean) ÷ 21 = 0.9226
零 advantage step 比例 = 12 ÷ 21 = 57.1%
平均 step 时间 = Σ(timing_s/step) ÷ 21 = 264.92 秒
线性训练时长估计 = 264.92 × 934 ÷ 3600 = 68.7 小时
```

由于每个 step 都包含 32 个 rollout，对 step mean 求算术平均与对全部 672 个 rollout 求总体平均等价。

### C.2 事实与推断的区分

以下属于日志直接事实：

- 配置参数已经生效；
- 前 21 步无 NPU OOM、NaN 和训练中断；
- reward、advantage、loss、长度、时间和内存的具体数值；
- 12 个 step 的 advantage 全零；
- 总计划训练步数为 934。

以下属于基于指标的合理推断：

- GSM8K 对当前模型偏简单；
- 大量 rollout 计算未转化为 GRPO 策略梯度；
- rollout 生成是当前主要性能瓶颈；
- 使用更困难的数据可能提高有效训练比例。

### C.3 不可由本实验得出的结论

本次 21-step 验证不能支持以下结论：

- 不能证明 GRPO 后模型准确率高于训练前基线；
- 不能证明模型在 GSM8K 测试集或其他数学任务上获得泛化提升；
- 不能证明 934 step 全程不会 OOM 或出现训练坍缩；
- 不能比较不同随机种子下的稳定性；
- 不能据此确定最佳学习率、group size、KL 系数或响应长度；
- 不能将训练 reward 直接当作独立测试集准确率。

正式能力结论需要至少补充：训练前固定基线、训练后同口径验证、独立测试集、固定采样参数，以及条件允许时的多随机种子实验。
