# CreateMyCard veRL SFT 数据构建

该目录把一份 system prompt、全量 TaskSpec JSON 和全量 Design Compact DSL JSONL 组装为 veRL SFT 使用的 Parquet。

## 目录

```text
sft/
├── analyze_tokens.py
├── build_parquet.py
├── run_sft.sh
├── training.env.example
├── requirements.txt
├── data/
│   ├── source/
│   │   ├── system_prompt.md
│   │   ├── taskspec.json
│   │   └── design_compact_dsl.jsonl
│   └── parquet/
```

`data/source/` 中的三个文件是唯一生产输入。`data/parquet/` 是生成目录。

上游 A2UI → Design Compact 转换规则见[数据生产与转换流程](../data_pipeline/README.md)；跨批次的数据合同统一见 [`docs/create_my_card/`](../../../../docs/create_my_card/)。

## 输入合同

### system_prompt.md

保存统一 system prompt。文件为空或只有空白时，构建出的 `messages` 不包含空 system 消息；以后填入内容后，每条样本都会使用同一份 system prompt。

### taskspec.json

根节点必须是数组，每条记录包含稳定且唯一的 `id` 和完整 `taskSpec`：

```json
[
  {
    "id": "q001",
    "taskSpec": {
      "size": "2x4",
      "userQuery": "示例"
    }
  }
]
```

`taskSpec` 会以紧凑 JSON 字符串写入 `user.content`，不会把 `id` 写入模型输入。

### design_compact_dsl.jsonl

每行是一条 JSON 记录，通过 `id` 与 TaskSpec 配对：

```json
{"id":"q001","designCompactDsl":"<Design Compact DSL 原文>"}
```

DSL 包含多行时，使用合法 JSON 字符串中的 `\n`。标签必须是原始 DSL，不允许 Markdown 代码围栏或 `<think>`。

构建器按 `id` 配对，不依赖两个文件的记录顺序；重复、缺失或多余的 `id` 都会直接报错。

## 输出格式

每条 Parquet 记录为：

```json
{
  "id": "q001",
  "messages": [
    {"role": "user", "content": "<完整 TaskSpec JSON 字符串>"},
    {"role": "assistant", "content": "<Design Compact DSL 原文>"}
  ],
  "enable_thinking": false
}
```

输出包括：

- `train.parquet`
- `validation.parquet`
- `manifest.json`：输入哈希、切分参数、样本 ID 和输出哈希

## 使用

在 veRL 训练环境安装依赖：

```bash
python -m pip install -r requirements.txt
```

填入源数据后执行：

```bash
cd /workspace/frameworks/verl/create_my_card/sft
python build_parquet.py
```

自定义构建参数示例：

```bash
python build_parquet.py \
  --validation-ratio 0.05 \
  --seed 42 \
  --output-dir /data/create_card_sft
```

当前源数据包含 192 条唯一配对记录：`cmc-v16-*` 99 条、`card84-v18-*` 93 条。`taskspec.json` 与 `design_compact_dsl.jsonl` 已通过本构建器的加载、唯一 ID 和双向缺失检查；`system_prompt.md` 保存与该批标签闭集对齐的 Qwen3.6-27B Compact DSL 生成约束，构建后作为每条样本统一的 system 消息。

## 训练

训练入口默认先用 Qwen3.6 自带 chat template 对全部数据重新分词，分别统计：

- prompt token：system（如有）+ TaskSpec + assistant 生成前缀
- assistant token：Design Compact DSL + assistant 结束标记
- total token：veRL SFT 实际处理的完整序列

随后生成 `token_stats.json`。`MAX_LENGTH=auto` 使用“全量最大 total token 向上对齐”的值，不使用 P99 截断；任何超长样本都会在训练前报错。

```bash
cp training.env.example /path/to/experiment.env
source /path/to/experiment.env

# 默认 DRY_RUN=1，只使用最长样本构造的 OOM probe 跑两步
bash run_sft.sh

# 冒烟通过后再正式训练
DRY_RUN=0 bash run_sft.sh
```

默认训练模式为全参数 SFT：

```text
LORA_RANK=0
LEARNING_RATE=1e-6
```

只有人工显式设置 `LORA_RANK>0` 才会切换为 LoRA；脚本不会在 OOM 后自动改变训练目标。Qwen3.6-27B 全参数 AdamW 的模型、梯度和优化器状态显存占用很高，正式训练前必须先让最长样本 dry-run 通过。

### 两个长度参数的区别

`MAX_LENGTH` 是单条 SFT 样本的总长度上限：

```text
prompt token + assistant token <= MAX_LENGTH
```

`MAX_TOKEN_LEN_PER_GPU` 是动态 micro-batch 在单个设备上的 token 预算。启用 Ulysses sequence parallel 后，veRL 的完整 micro-batch 预算为：

```text
MAX_TOKEN_LEN_PER_GPU × SP_SIZE
```

因此脚本默认按以下方式计算，而不是简单令两个值相等：

```text
MAX_TOKEN_LEN_PER_GPU = ceil(MAX_LENGTH / SP_SIZE)，再向上对齐
```

这保证最长样本可以放入一个 micro-batch，同时避免 SP>1 时无意中把激活预算扩大数倍。

### OOM 处理顺序

训练默认已经开启 BF16、FSDP、梯度检查点、去 padding、动态 token batch，并将每设备 micro batch 设为 1。如果最长样本 dry-run 仍然 OOM，按以下顺序处理：

1. 增大 `SP_SIZE`，例如 `1 → 2 → 4`，且必须整除设备数。
2. 保持 `MICRO_BATCH_SIZE_PER_GPU=1`，不要靠截断 DSL 降显存。
3. 开启 `ACTIVATION_OFFLOAD=true`。
4. 再开启 `OPTIMIZER_OFFLOAD=true`，必要时开启 `PARAM_OFFLOAD=true`。
5. 若仍然 OOM，降低业务 token 硬上限并回到数据侧处理超长样本，或增加设备，不能静默截断。

`data.truncation=error` 和 `data.ignore_input_ids_mismatch=false` 被固定为硬检查。训练脚本不会捕获 OOM 后偷偷降低长度重试，也不会自动改为 LoRA，因为这两种做法都会改变既定训练目标。

训练和推理必须使用相同 Qwen3.6 tokenizer、chat template、system prompt 与 `enable_thinking=false` 设置。
