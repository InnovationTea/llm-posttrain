# Design Compact / A2UI 正逆向转换交接包

本目录把冻结版正向转换器和逆向/回转校验入口放在一起：

- `compact_dsl_a2ui_converter.py`：从 [CreateMyCard `dev` 分支](https://github.com/linfachen-lff/CreateMyCard/blob/dev/widget_service/cloud/services/compact_dsl_a2ui_converter.py) 冻结的 Compact DSL → A2UI 转换器。
- `reverse_and_verify.py`：A2UI → Compact DSL 逆向转换、正向回转和结构化差异报告。

基础来源：CreateMyCard commit `6b0f5e3c9327963ae467e178da2ec5b279368a45`，上游文件 SHA-256 为 `382D6703B3F87AC2510CF542B013EFFF2EA49496872C6B94C2D28FDEE7204F20`。本地配套版按 2026-08-07 数据闭集要求做了四项变更：`createSurface` 不再输出 `width/height`，Image 保留 `fillColor`，`layoutWeight` 同时支持数值字面量和动态 path binding，结构化 `expression` binding 支持动态拼接、条件判断和公式计算；当前正向文件 SHA-256 为 `1BC4F919922C58CAD851213D15CB7D4D003737FBCB651156AA13CD7382615FB1`。

## Python API

```python
from frameworks.verl.create_my_card.data_pipeline.converters import (
    convert_a2ui_to_compact_dsl,
    convert_compact_dsl_to_a2ui,
    reverse_and_verify,
)

compact = convert_a2ui_to_compact_dsl(source_a2ui, size="2x2")

result = reverse_and_verify(source_a2ui, size="2x2")
assert result.report["roundtrip"] == "pass"
print(result.compact_dsl)
print(result.roundtrip_a2ui)
```

逆向默认执行以下规范化：

- 恢复 `{{ ${/path} }}` 为 `{"path":"/path"}`。
- 恢复 `{{ ${/path} + '%' }}` 等复合动态值为 `{"expression":"${/path} + '%'"}`，正向转换时重新生成标准 A2UI 表达式。
- 按组件树前序输出 Compact 元组行，并用根 data 行无损保留完整 DataModel。
- 完整匹配冻结样式表时收敛为 `design`。
- 严格匹配正向展开结构时收敛为 `ActionUnit`；普通 `Button` 或 `Stack + Image` 不会被宽松误判。
- 删除正向转换器必然重新生成的 root/Text 默认字段。
- 遇到协议外或无法回转的有效字段直接报错，不静默丢弃。

Hex → 颜色 Token 默认关闭；可通过 `collapse_color_tokens=True` 开启。相同 Hex 对应多个 Token 时，按冻结正向表中的定义顺序选择第一个别名。

`expression` binding 只允许数据路径、字符串/数字、算术、比较、逻辑、括号和三元运算；函数调用、`$item`、`$__dataModel` 及任意代码仍会被拒绝。表达式中的每个数据路径都会参加 DataModel 和上下文校验。

## CLI

```powershell
python frameworks/verl/create_my_card/data_pipeline/converters/reverse_and_verify.py `
  --source-a2ui case/final.card.genui.jsonl `
  --size 2x2 `
  --compact-out case/design-compact.card.genui.jsonl `
  --roundtrip-out case/roundtrip.card.genui.jsonl `
  --report-out case/report.json
```

如需上下文校验，同时提供 TaskSpec 和 CardSpec：

```powershell
python frameworks/verl/create_my_card/data_pipeline/converters/reverse_and_verify.py `
  --source-a2ui case/final.card.genui.jsonl `
  --task-spec case/task-spec.json `
  --card-spec case/card-spec.json `
  --compact-out case/design-compact.card.genui.jsonl `
  --roundtrip-out case/roundtrip.card.genui.jsonl `
  --report-out case/report.json
```

如果 TaskSpec 内嵌 `cardSpec`，可以省略 `--card-spec`。尺寸会依次从 `--size`、CardSpec/TaskSpec 的 `suggestSize` 或 `size` 获取；只有兼容旧式、显式携带宽高的 Surface 才能从 Surface 推断。当前配套正向器不再输出 Surface 宽高，因此调用逆向器时应显式传入尺寸或提供 Spec。

退出码：`0` 表示 roundtrip 通过，`1` 表示转换成功但对比不一致，`2` 表示输入、逆向、协议或上下文校验失败。

## 不可逆信息

冻结正向转换器会展开 `design` 和颜色 Token、丢弃 `Progress.threshold`，并覆盖部分 root/Text 默认样式，因此无法恢复原始 Compact DSL 的逐字节写法。逆向输出的是确定性的规范化 Compact DSL；验收目标是最终 A2UI 的组件、语义、绑定、DataModel、事件和有效样式 roundtrip 等效。

## 相关规范

- [数据生产交接说明](../../../../../docs/create_my_card/data-production-handoff.md)
- [数据质检规范](../../../../../docs/create_my_card/data-quality-spec.md)
- [Expression Profile v1](../../../../../docs/create_my_card/expression-profile-v1.md)

代码修改后至少执行语法编译，并使用目标闭集重新执行严格逆向和正向 roundtrip：

```powershell
python -m compileall -q frameworks/verl/create_my_card/data_pipeline/converters
```
