# CreateMyCard 后训练

本目录集中维护 CreateMyCard 的 Design Compact 数据生产链路和 veRL SFT 数据构建入口。

```text
create_my_card/
├── data_pipeline/
│   ├── README.md
│   └── converters/          # Compact DSL ↔ A2UI 正逆向转换
└── sft/
    ├── data/source/         # TaskSpec、Compact DSL、system prompt
    ├── build_parquet.py
    ├── analyze_tokens.py
    └── run_sft.sh
```

## 数据链路

```text
TaskSpec + 最终 A2UI
→ 逆向生成 Design Compact DSL
→ 正向 roundtrip 验证
→ TaskSpec 与 Compact DSL 按唯一 ID 配对
→ veRL SFT Parquet
→ 训练前全量 token/OOM 检查
```

## 入口

- [数据生产与转换流程](data_pipeline/README.md)
- [正逆向转换器](data_pipeline/converters/README.md)
- [SFT 数据构建与训练](sft/README.md)
- [数据生产交接说明](../../../docs/create_my_card/data-production-handoff.md)
- [数据质检规范](../../../docs/create_my_card/data-quality-spec.md)
- [Expression Profile v1](../../../docs/create_my_card/expression-profile-v1.md)

详细数据合同统一由 `docs/create_my_card/` 维护；模块 README 只说明当前代码、输入和运行方式，避免复制两份规范后产生漂移。
