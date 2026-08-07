# CreateMyCard 数据生产与转换流程

本目录负责把数据生产方交付的 TaskSpec 与最终 A2UI 转换为可训练的 Design Compact DSL，并通过正向 roundtrip 保证语义无损。

## 工作流

```text
TaskSpec + final A2UI
→ A2UI 协议与组件树解析
→ 逆向生成规范化 Compact DSL
→ Compact 校验
→ 正向生成 roundtrip A2UI
→ 结构化差异比较
→ 写入 ../sft/data/source/
```

转换器只执行协议内的确定性规范化，不重做布局，也不会静默丢弃未知字段。动态值使用 `path` 或冻结的结构化 `expression` binding。

## 单条转换

```powershell
python frameworks/verl/create_my_card/data_pipeline/converters/reverse_and_verify.py `
  --source-a2ui case/card.genui.jsonl `
  --task-spec case/task-spec.json `
  --compact-out case/design-compact.card.genui.jsonl `
  --roundtrip-out case/roundtrip.card.genui.jsonl `
  --report-out case/report.json
```

TaskSpec 没有内嵌 CardSpec 时，它仍可提供尺寸，但不会执行完整的 TaskSpec + CardSpec 能力上下文校验。完整参数和退出码见[转换器说明](converters/README.md)。

## 冻结合同

- [数据生产交接说明](../../../../docs/create_my_card/data-production-handoff.md)
- [数据质检规范](../../../../docs/create_my_card/data-quality-spec.md)
- [Expression Profile v1](../../../../docs/create_my_card/expression-profile-v1.md)

通过 roundtrip 的 TaskSpec 与 Compact DSL 使用稳定唯一 ID 写入 [`../sft/data/source/`](../sft/data/source/)，再由 SFT 构建器做配对、切分和 Parquet 生成。
