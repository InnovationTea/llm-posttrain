# Qwen3.6-27B 在 GSM8K 上进行全参数 SFT

本文面向单台 8 张 Ascend 910C（Atlas A3）服务器。脚本按容器内项目目录
`/workspace`、模型目录 `/mnt/model`、数据目录 `/mnt/data` 编写。
以下命令默认在同一个容器 shell 中依次执行；重新进入容器后需重新导出各路径变量。

为减少手工输入差异，可以把实验变量模板复制到数据盘并固定保存：

```bash
cp frameworks/verl/qwen36_gsm8k/experiment.env.example \
  /mnt/data/qwen36-gsm8k-sft-v1.env
source /mnt/data/qwen36-gsm8k-sft-v1.env
```

模板不会被任何脚本自动读取。复制后应按实际挂载修改，并与训练日志、数据元信息和评测结果一起保留。
原有的逐项 `export` 命令仍然有效。

## 训练方案

- 任务：GSM8K 监督微调（SFT），不是 GRPO/PPO。
- 后端：veRL `sft_trainer` + Hugging Face 模型定义 + FSDP。
- 参数更新：全参数，显式设置 `model.lora_rank=0`。
- 精度：BF16；A3 不使用 FP8 训练。
- 首次运行：`2 × 全局 batch size` 条训练数据、`1 × 全局 batch size` 条验证数据、2 个 optimizer step。
- 正式训练初始值：1 epoch、学习率 `1e-6`。

GSM8K 数据量较小。对 27B 模型直接进行多 epoch 全参数训练容易过拟合并造成通用能力遗忘，
因此不要一开始提高学习率或训练轮数。

## 0. 确认容器和挂载

宿主机启动示例：

```bash
cd /path/to/llm-posttrain
WORK_DIR="$PWD" bash infra/startContainer.sh qwen36-sft
docker exec -it qwen36-sft bash
```

容器内执行：

```bash
cd /workspace
npu-smi info
bash infra/check_ascend_env.sh
ls /mnt/model
ls /mnt/data
```

环境检查会按容器内的可见 NPU 数量启动对应数量的进程，验证每个 rank 的 BF16 前后向以及
HCCL AllReduce。单机 rendezvous 默认绑定 `127.0.0.1:29500`，避免依赖容器 hostname
解析；端口占用时可用 `MASTER_PORT=29501 bash infra/check_ascend_env.sh` 覆盖。
该检查不加载模型权重；通过后再进行模型和数据预检。

`npu-smi` 显示的逻辑 NPU 数量可能不同于物理卡数量。训练脚本默认调用
`torch.npu.device_count()` 自动确定 `torchrun` 进程数。

## 1. 模型和 NPU 元数据预检

设置实际模型路径：

```bash
cd /workspace
export MODEL_PATH=/mnt/model/Qwen3.6-27B

python3 frameworks/verl/qwen36_gsm8k/preflight.py \
  --model-path "$MODEL_PATH"
```

这一阶段不会加载 27B 权重，只验证：

- `torch_npu` 注册和 NPU 可见性；
- torch、torch_npu、Transformers 和 veRL 版本；
- `config.json`、Hugging Face 权重文件能否被发现，模型类型能否被当前 Transformers 识别；
- AutoProcessor/AutoTokenizer 和 chat template 能否工作。

任何一项失败都不要直接开始分布式训练。

## 2. 生成 GSM8K SFT 数据

```bash
export DATA_DIR=/mnt/data/gsm8k_sft

python3 frameworks/verl/qwen36_gsm8k/prepare_gsm8k_sft.py \
  --output-dir "$DATA_DIR"
```

联网时脚本默认下载 `openai/gsm8k`。如果已经准备了本地 Hugging Face 数据集：

```bash
python3 frameworks/verl/qwen36_gsm8k/prepare_gsm8k_sft.py \
  --dataset-path /mnt/data/gsm8k_sft_raw \
  --output-dir "$DATA_DIR"
```

需要严格固定远程数据版本时，传入 Hugging Face commit hash：

```bash
python3 frameworks/verl/qwen36_gsm8k/prepare_gsm8k_sft.py \
  --dataset-revision <commit-hash> \
  --output-dir "$DATA_DIR"
```

输出：

```text
/mnt/data/gsm8k_sft/train.parquet
/mnt/data/gsm8k_sft/validation.parquet
/mnt/data/gsm8k_sft/test.parquet
/mnt/data/gsm8k_sft/metadata.json
```

脚本使用固定 seed，将官方 train 的 10% 留作 validation；官方 test 不传给 trainer，
只用于训练前后的最终生成式评测。修改 `--validation-ratio` 或 `--seed` 会改变训练/验证划分，
同一组对比实验必须保持这两个参数一致。
`metadata.json` 还会记录请求的数据 revision、转换前后各 split 的 Hugging Face fingerprint；
复现实验时应同时核对行数、seed、instruction 和 fingerprint。未显式指定 revision 时，
脚本行为与原流程一致，并记录实际生成数据的 fingerprint。

Parquet 中的每条样本使用 veRL SFT 所需的 `messages` 字段：

```json
{
  "messages": [
    {"role": "user", "content": "题目与回答格式要求"},
    {"role": "assistant", "content": "推理过程与 #### 最终答案"}
  ]
}
```

数据文件不写入 `enable_thinking` 字段；训练脚本显式设置
`data.enable_thinking_default=null`，避免把无效的 thinking 参数传给当前 Qwen3.6 processor。
GSM8K 的逐步推理仍然保存在 assistant 正文中。

不要使用面向强化学习的 `examples/data_preprocess/gsm8k.py` 代替本脚本；RL 数据主要保存
prompt、ground truth 和 reward 元数据，并不是本 SFT 入口要求的训练格式。

## 3. 验收数据和 token 长度

```bash
python3 frameworks/verl/qwen36_gsm8k/preflight.py \
  --model-path "$MODEL_PATH" \
  --data-dir "$DATA_DIR" \
  --max-length 2048
```

该命令默认检查 train/validation/test 全量样本，包括 user/assistant 顺序、空内容、`####` 答案标记，
并通过 veRL `MultiTurnSFTDataset` 验证逐轮 token 拼接、整段 input IDs 一致性和 assistant
loss mask，同时确认实际 SFT input IDs 以评测所用的非 thinking prompt 开头。报告会给出三个
split 的 token 长度分布和最长样本行号。默认训练上限是 2048；
如果检查失败，先同步调高 `--max-length`、`MAX_LENGTH` 和 `MAX_TOKEN_LEN_PER_GPU`，不要使用静默截断。

只想抽样检查时可以设置 `--sample-size`；`-1` 表示检查全部样本：

```bash
python3 frameworks/verl/qwen36_gsm8k/preflight.py \
  --model-path "$MODEL_PATH" \
  --data-dir "$DATA_DIR" \
  --sample-size 1000 \
  --max-length 2048
```

## 4. 记录训练前基线

使用 vLLM-Ascend 对完整 test split 做确定性生成：

```bash
export EVAL_DIR=/mnt/data/evals/qwen36_gsm8k
mkdir -p "$EVAL_DIR"

python3 frameworks/verl/qwen36_gsm8k/evaluate_gsm8k.py \
  --model-path "$MODEL_PATH" \
  --tokenizer-path "$MODEL_PATH" \
  --data-file "$DATA_DIR/test.parquet" \
  --output-file "$EVAL_DIR/before.jsonl" \
  --tensor-parallel-size 8 \
  --no-enable-thinking
```

Qwen3.6-27B 有 24 个 attention heads，tensor parallel size 必须是 24 的因数，因此不能在
16 个逻辑 NPU 上设置 TP=16。本示例使用 TP=8，采用 greedy decoding，最多生成 1024 tokens。
训练阶段使用的是 FSDP，不是 vLLM tensor parallel，因此可以使用全部 16 个逻辑 NPU；
评测阶段 TP=8 时，其余 8 个逻辑 NPU 空闲是预期行为。
训练的 `MAX_LENGTH=2048` 限制单条 SFT 样本；评测的 `max_model_len=4096` 限制
prompt 与 completion 的总长度，`max_new_tokens=1024` 只限制 completion。评测脚本会在加载
模型权重前检查实际最长 prompt 加 1024 是否超过 4096。
需要先验证评测链路时可增加 `--limit 32`；正式对比必须去掉该参数，使用完整 test。
评测默认关闭模型的内部 thinking 模式，但仍保留 GSM8K assistant 正文中的逐步推理。开启 thinking
时可显式传入 `--enable-thinking`，且训练前后必须使用相同设置。
评测脚本会在未显式设置时使用 `OMP_NUM_THREADS=1`，避免 vLLM 多进程初始化期间动态修改
PyTorch OpenMP 线程池；同时使用 `VLLM_WORKER_MULTIPROC_METHOD=spawn`，避免 NPU worker
继承父进程已初始化的运行时状态。已有的用户配置不会被覆盖。
每次评测会保存逐题 JSONL 和同名 `.summary.json`，其中：

- `accuracy`：优先提取 `####` 后的数字，没有标记时回退到最后一个数字；
- `strict_accuracy`：答案正确并且输出包含有效的 `####`；
- `format_valid_rate`：有效 `####` 格式比例；
- `average_completion_tokens`：平均生成长度；
- `max_prompt_tokens`：本次评测中最长的渲染后 prompt 长度；
- `truncation_rate`：由于达到 `max_new_tokens` 而停止的样本比例。

## 5. 两步全参冒烟训练

```bash
cd /workspace
export SAVE_PATH=/mnt/data/checkpoints/qwen36-27b-gsm8k-sft-dry-run

DRY_RUN=1 DRY_RUN_STEPS=2 \
  bash frameworks/verl/qwen36_gsm8k/run_sft.sh
```

`MODEL_PATH` 和 `DATA_DIR` 沿用前面已经通过预检的值，不要在这里换模型或重新生成数据。
在当前 16 个逻辑 NPU、`SP_SIZE=1` 的默认配置下，脚本应打印：DP=16、global batch=32、
local batch=2、micro batch=1；dry-run 使用 64 条训练数据、32 条验证数据，完成 2 个
optimizer step。

veRL 在最后一步固定保存 checkpoint。dry-run 因此仍会生成 `global_step_2`，但只保存
model 和 extra，不保存 Adam optimizer；该 checkpoint 只用于验证保存链路，不用于正式训练。

冒烟测试必须确认：

- 所有 rank 成功初始化，没有 HCCL 超时；
- Qwen3.6 权重和 processor 成功加载；
- loss、grad norm 为有限数值；
- 两个 step 均完成；
- 没有 NPU OOM 或 tokenizer/chat-template 不一致错误。

如果显存不足，先只为冒烟测试开启 optimizer offload：

```bash
OPTIMIZER_OFFLOAD=true DRY_RUN=1 \
  bash frameworks/verl/qwen36_gsm8k/run_sft.sh
```

如果仍然 OOM，再尝试：

```bash
PARAM_OFFLOAD=true OPTIMIZER_OFFLOAD=true ACTIVATION_OFFLOAD=true DRY_RUN=1 \
  bash frameworks/verl/qwen36_gsm8k/run_sft.sh
```

offload 会显著降低速度，因此不应在尚未观察显存占用前全部开启。

## 6. 正式训练

使用新的正式训练目录，从基座模型开始 1 epoch：

```bash
export SAVE_PATH=/mnt/data/checkpoints/qwen36-27b-gsm8k-sft-v1

DRY_RUN=0 RESUME_MODE=disable TOTAL_EPOCHS=1 LEARNING_RATE=1e-6 \
  bash frameworks/verl/qwen36_gsm8k/run_sft.sh
```

`RESUME_MODE=disable` 是默认值。如果 `SAVE_PATH` 已包含 `global_step_*`，脚本会拒绝启动，
防止把旧实验误当成新实验。已有 checkpoint 需要续训时，保持模型、数据、batch 和
`SAVE_PATH` 不变，确认 tracker 存在后改用：

```bash
test -f "$SAVE_PATH/latest_checkpointed_iteration.txt"

DRY_RUN=0 RESUME_MODE=auto TOTAL_EPOCHS=1 LEARNING_RATE=1e-6 \
  bash frameworks/verl/qwen36_gsm8k/run_sft.sh
```

默认只在每个 epoch 结束时保存；1 epoch 训练若在首次保存前中断，没有 checkpoint 可以续训。
当前 train 有 6725 条数据；默认 global batch=32，veRL 的 distributed sampler 使用
`drop_last=true`，所以每个 epoch 是 210 个 optimizer step（使用 6720 条，丢弃最后 5 条）。
validation 同理使用 736/748 条计算验证 loss；最终 `evaluate_gsm8k.py` 不使用 distributed
sampler，会评测完整 1319 条官方 test。
trainer 只读取 `train.parquet` 和 `validation.parquet`。`test.parquet` 不参与 loss 计算、
调参或 checkpoint 选择。

## 7. 合并正式训练 checkpoint

正式训练保存的是 veRL FSDP 分片。使用 checkpoint tracker 获取最后一个 step，避免把
world size 或目录名写死：

```bash
export MERGED_MODEL=/mnt/model/qwen36-27b-gsm8k-sft-v1-hf

bash frameworks/verl/qwen36_gsm8k/merge_fsdp_checkpoint.sh
```

合并脚本从 `$SAVE_PATH/latest_checkpointed_iteration.txt` 读取最后一个 step，检查
`fsdp_config.json`、模型分片和目标目录，再调用原有的 `verl.model_merger` 命令；完成后自动执行
模型结构预检。已有 `$MERGED_MODEL` 时脚本会拒绝覆盖；如需合并非 tracker 指向的历史 checkpoint，
应直接调用 `python3 -m verl.model_merger merge` 并显式传入对应目录。

`MERGED_MODEL` 必须使用新的目标目录，避免旧权重残留。合并需要足够的主机内存和额外磁盘空间。
`--use_cpu_initialization` 会在 CPU 上读取并重组约 54 GB 的 BF16 模型权重；日志停留在
`Loading shards` 数十分钟并且 NPU 空闲不一定是卡死，应结合进程 CPU、主机内存和磁盘读取量判断。

评测时仍显式使用基座 `$MODEL_PATH` 的 tokenizer，确保 before/after 的 prompt 模板一致。

## 8. 训练后评测与配对比较

```bash
python3 frameworks/verl/qwen36_gsm8k/evaluate_gsm8k.py \
  --model-path "$MERGED_MODEL" \
  --tokenizer-path "$MODEL_PATH" \
  --data-file "$DATA_DIR/test.parquet" \
  --output-file "$EVAL_DIR/after.jsonl" \
  --tensor-parallel-size 8 \
  --no-enable-thinking

python3 frameworks/verl/qwen36_gsm8k/compare_gsm8k.py \
  --before "$EVAL_DIR/before.jsonl" \
  --after "$EVAL_DIR/after.jsonl" \
  --output-file "$EVAL_DIR/comparison.json"
```

`compare_gsm8k.py` 会拒绝比较样本集合、tokenizer 路径、TP、上下文长度、生成长度、
thinking 模式或 seed 不一致的结果，因此不要修改 before/after 任一侧的评测参数。
比较报告包含准确率变化、paired bootstrap 95% 区间、wrong→right、right→wrong、格式成功率
、截断率和平均生成长度。宽松的 `accuracy` 允许从没有 `####` 的输出中回退提取最后一个数字；
因此应以 `strict_accuracy_delta`、对应的 paired bootstrap 区间和 `strict_transitions` 为主要结论。
本基座在完整 test 上已经达到约 96% 的高准确率，收益空间较小；只有 strict 指标稳定提高、
wrong→right 多于 right→wrong、截断率不增加，并且通用能力评测没有明显下降时，才能认为
全参 SFT 带来了真实收益。至少再使用一组固定的通用能力或非 GSM8K 数学基准检查灾难性遗忘。

## 9. 最终交付物

一次完整实验应保留：

- 实验 `.env`：本次使用的模型、数据、checkpoint、batch 和评测参数；
- `$DATA_DIR/metadata.json`：数据来源、划分比例和 seed；
- `$EVAL_DIR/before.jsonl` 与 `before.summary.json`：完整 1319 题基线；
- `$SAVE_PATH/latest_checkpointed_iteration.txt` 与对应 `global_step_*`：可恢复的 FSDP checkpoint；
- `$MERGED_MODEL`：可由 Hugging Face/vLLM 加载的合并模型；
- `$EVAL_DIR/after.jsonl` 与 `after.summary.json`：相同配置下的训练后结果；
- `$EVAL_DIR/comparison.json`：配对统计结论；
- `$LOG_DIR` 下的训练日志：启动参数、逐步指标和保存记录。

## 10. 训练参数与磁盘空间

常用环境变量：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `MODEL_PATH` | `/mnt/model/Qwen3.6-27B` | Hugging Face 模型目录 |
| `DATA_DIR` | `/mnt/data/gsm8k_sft` | SFT parquet 目录 |
| `SAVE_PATH` | 按运行模式选择 | dry-run 与正式训练使用独立 checkpoint 目录 |
| `NPROC_PER_NODE` | 自动检测 | 逻辑 NPU/torchrun 进程数 |
| `MASTER_ADDR` | `127.0.0.1` | 单机 torchrun rendezvous 地址 |
| `MASTER_PORT` | `29500` | 单机 torchrun rendezvous 端口 |
| `TRAIN_BATCH_SIZE` | `2 × NPROC_PER_NODE` | 全局 batch size |
| `MICRO_BATCH_SIZE_PER_GPU` | `1` | 单 NPU micro batch |
| `MAX_LENGTH` | `2048` | 单样本最大长度 |
| `MAX_TOKEN_LEN_PER_GPU` | `2048` | 动态 micro batch 的单 NPU token 上限 |
| `LEARNING_RATE` | `1e-6` | 全参 SFT 学习率 |
| `DRY_RUN_STEPS` | `2` | 冒烟训练 optimizer step 数，仅 dry-run 使用 |
| `SP_SIZE` | `1` | Ulysses sequence parallel size |
| `MAX_CKPT_TO_KEEP` | `2` | 正式训练最多保留的 checkpoint 数量 |
| `RESUME_MODE` | `disable` | 正式训练从头开始；中断续训时设为 `auto` |
| `LOGGER` | `console` | 设置为 `wandb` 可启用 W&B |

训练 checkpoint 很大。正式训练前应检查 `/mnt/data` 剩余空间：

```bash
df -h /mnt/data
```

全参训练需要保存 FP32 模型、优化器分片及额外状态，单个完整 checkpoint 可能超过 300 GB；
合并后的 Hugging Face 模型还需要独立空间。默认最多保留 2 个，正式训练前应按保存数量预留空间。
日志中的
`Total time for train steps: 0.00s` 和最后显示 50% 属于当前 veRL 计时/进度条显示问题，
应以逐步指标、`global_step`、checkpoint tracker 和脚本首尾时间为准。

## 故障处理原则

1. 元数据预检失败：解决 Transformers、processor 或模型文件问题。
2. 权重初始化失败：确认 Qwen3.6 是否被当前 veRL/FSDP 模型定义支持。
3. HCCL 初始化失败：先独立检查驱动、固件、NPU 数量和卡间通信。
4. 第一个 forward OOM：保持 micro batch 为 1，再逐项启用 optimizer、activation、parameter offload。
5. loss 为 NaN：保持 BF16，降低学习率，并检查 assistant 标签和 token 长度。

## 代码更新后的轻量回归

以下检查不加载模型权重，也不需要 NPU：

```bash
python3 -m unittest discover \
  -s frameworks/verl/qwen36_gsm8k/tests \
  -p 'test_*.py'

python3 -m py_compile frameworks/verl/qwen36_gsm8k/*.py
bash -n frameworks/verl/qwen36_gsm8k/run_sft.sh
bash -n frameworks/verl/qwen36_gsm8k/merge_fsdp_checkpoint.sh
```

这些检查只保护数据转换、答案提取、配对统计和 shell 语法；依赖版本、NPU、HCCL、模型加载和
显存仍必须依次通过环境检查、`preflight.py` 和两步分布式冒烟测试。
