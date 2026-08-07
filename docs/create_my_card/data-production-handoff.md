# Design Compact 数据生产交接说明

## 1. 交付目标

数据生产方继续按现有方式生成最终 A2UI DSL，不手工编写 Design Compact 极简 DSL，也不在最终 A2UI 中添加 `design`、颜色 Token 或其它中间态字段。

完整链路为：

```text
TaskSpec
→ 数据生产方生成最终 A2UI DSL
→ 逆向工具生成 Design Compact 极简 DSL
→ 官方正向转换器重新生成最终 A2UI DSL
→ roundtrip 校验
→ 通过后形成 TaskSpec → Design Compact 极简 DSL 的 SFT 样本
```

生产方的目标不是“手工造 Token”，而是让最终 A2UI 的组件、结构和有效样式落在可逆闭集内。

## 2. 版本与权威来源

同一批数据必须冻结同一个 Git 提交或工具文件哈希，不得直接依赖持续变化的 `dev` 分支。当前可执行基线是仓库内的[正逆向转换器冻结包](../../frameworks/verl/create_my_card/data_pipeline/converters/README.md)；来源提交、上游哈希和本地扩展后哈希只在该说明中维护，本文不复制第二份版本号。

上游语义来源：

1. 极简 DSL 生成参考：
   `widget_service/cloud/data/protocol_profiles/design-compact-dsl/PROMPT.md`
2. 可执行协议、Token 展开和最终 A2UI 转换语义：
   `widget_service/cloud/services/compact_dsl_a2ui_converter.py`

使用原则：

- 批量转换和验收使用仓库内冻结包，不在运行时从上游 `dev` 分支下载转换器。
- PROMPT 是面向在线生成的参考提示词，不是数据生产的布局白名单；其中的固定 Variant、容量和布局建议不作为逆向转换或数据验收门槛。
- 数据生产可以合理扩展布局，只要最终 A2UI 合法、极简组件与属性能够表达、正向转换器能够稳定还原，逆向工具就应保留原结构，不得强行改造成 PROMPT 示例布局。
- 转换器是可执行协议和 Design Token 的权威来源，决定 Token 支持闭集、展开值，以及 `ActionUnit` 如何生成最终组件。
- 可用于训练标签的 Token 以冻结版本转换器实际支持为准，不要求同时出现在当前 PROMPT 中。
- Design Token 支持表以转换器 `_COMPONENT_DESIGNS` 为准，颜色 Token 支持表以 `_COLOR_TOKENS` 为准；`ActionUnit.state` 按转换器校验和展开逻辑执行。
- PROMPT 未列举某个 Token，不构成拒收理由；不在转换器支持表、只能依赖猜测或自造名称的值才是非法 Token。
- 每个数据包的 manifest 必须记录正向转换器、逆向工具和校验器的提交或 SHA-256；若生产或训练实际使用了 PROMPT，再记录其版本作为来源信息。

如果 Design Token 有调整，应先更新并冻结正向转换器和逆向匹配表，再开始批量生产；PROMPT 可以同步推荐用法，但不作为 Token 生效的前置条件。不得在批次中途变更转换器 Token 表。

## 3. 每条样本的最小交付

每条样本只需交付：

```text
<case-id>/
  task-spec.json
  final.card.genui.jsonl
```

其中：

- `task-spec.json` 包含 `userQuery`、`size`、`dataModelSchema`，以及可选的 `assetCandidates`、`eventCandidates`。
- `final.card.genui.jsonl` 是数据生产方生成的最终 A2UI DSL。
- Query 已包含在 `TaskSpec.userQuery` 时，不再重复交付单独 Query 文件。
- PNG、逐组件样式快照、人工摘录的 design-token.json 和能力清单副本不属于最小交付。

卡片尺寸以 TaskSpec 和冻结转换器实际支持为准。可以在批次 manifest 中限定尺寸范围，但不能仅因当前 PROMPT 只示范 `2x2` 而拒绝转换器可表达的其它合法尺寸。

## 4. 最终 A2UI 生产约束

### 4.1 结构

以下是数据质量建议，不是逆向转换的布局白名单。合理扩展的布局只要组件和属性可被转换器处理，就应按原树机械逆向；逆向阶段不做 Variant 选择或布局重排。当前需要特殊匹配的核心只有“显式样式是否收敛为哪个 `design` Token”。

- 纵向内容流优先使用 `Column`。
- 横向内容流优先使用 `Row`。
- `Stack` 只用于真实叠加、覆盖或独立定位。
- 不使用仅含一个子组件、只为模拟坐标的 Stack 包装层。
- 不生成空容器、孤儿组件、未定义 children 或同一组件被多个父节点引用。
- 组件树应父先子后、ID 唯一，并能从 root 完整到达。
- 不添加协议外字段。
- 不添加不影响渲染和业务映射的解释字段，例如 `accessibility`。

### 4.2 数据绑定

- 可变业务事实必须绑定 `dataModelSchema` 中存在的 path。
- 单一路径引用使用结构化 `{"path":"/data/..."}`；拼接、运算或条件判断使用结构化 `{"expression":"..."}`，并由正向转换器统一生成最终 A2UI 绑定字符串。
- 表达式只能使用冻结闭集；当前语法、目标属性和类型约束见 [Expression Profile v1](expression-profile-v1.md)。
- `sampleValue` 只用于预览数据，不得抄成静态业务文案。
- 使用到的 path 必须存在对应 DataModel 数据；未使用的候选字段无需强行上屏。
- 不从 Query、事件参数或素材路径中编造动态事实。
- 事件 `args`、`params` 不得进入可见文案。

### 4.3 素材与事件候选

- 候选是白名单，不是全量使用清单。
- 只使用与 Query 和最终核心信息闭环的事件；行动数量和落点以业务语义、最终协议和转换器可表达能力为准，不套用当前 PROMPT 的固定 Variant 数量。
- `call` 和 `args` 必须整体来自同一个候选，不能拼接或改写。
- Image 只选择语义匹配的候选素材；即使提供素材，也允许不生成 Image。
- 为训练候选筛选能力，允许 TaskSpec 中存在合理但未使用的数据、事件和素材候选。
- 未使用候选的位置应打散，不固定放在列表末尾。

### 4.4 样式必须可逆

最终 A2UI 中不写 `design`。生产模型应使用正向转换器中目标 Token 展开后的有效样式值，使逆向工具能够识别。

例如，目标中间态为：

```json
["title","Text",{"content":"内存清理","design":"card-title","fontColor":"font_primary"}]
```

生产方应生成与其展开结果一致的最终样式：

```json
{
  "id": "title",
  "component": "Text",
  "content": "内存清理",
  "styles": {
    "fontSize": 14,
    "fontWeight": 700,
    "fontColor": "#E5000000"
  }
}
```

规则：

- Token 展开值从固定版本转换器抽取，不在本文重复维护第二份数值表。
- 一个目标 Token 定义的属性必须完整匹配；不要只改字号、圆角、宽高或 padding 中的一项。
- 可添加 Token 未覆盖、但协议允许且确有渲染作用的显式属性。
- 若样式无法匹配任何允许的 Token，逆向工具保留协议白名单内的显式属性；不得为了命中 Token 修改语义或编造新 Token。
- 协议无法表达且确实影响目标效果的属性应报错并回到生产侧调整，不能静默丢弃。
- 最终 A2UI 使用有效 Hex。逆向时颜色可以保留为合法 Hex，也可以按固定规则收敛为转换器支持的颜色 Token；颜色 Token 化不是通过条件。

### 4.5 ActionUnit 的特殊处理

`ActionUnit` 是极简 DSL 的高级组件，不是数据生产方应直接输出的最终 A2UI 组件。

- 极简 DSL 的 `state:"capsule"` 正向展开为最终 `Button`。
- 极简 DSL 的 `state:"icon-round"` 正向展开为可点击 `Stack` 和内部 Image。
- 生产方应生成与固定转换器展开结果同构的最终组件树和样式。
- 逆向工具负责把满足该结构的最终组件重新收敛为 `ActionUnit`。
- 不允许用任意 Button 或任意 Stack+Image 冒充 ActionUnit；结构、事件、资源和样式必须同时匹配。

## 5. 逆向转换规则

除 Design Token 收敛外，组件树、布局属性、绑定、素材和事件均应按协议机械映射，不根据 PROMPT 重新设计卡片。

逆向工具按下列顺序处理：

1. 解析最终 A2UI 三段消息，恢复组件树、DataModel 和 Surface 信息。
2. 删除明确登记的无渲染、无语义字段；不能按未知字段一律删除。
3. 将标准 A2UI 组件转换为极简 DSL 元组行。
4. 可选地将显式 Hex 反查为转换器支持的语义颜色 Token；若启用，同值别名必须使用固定优先级。也允许保留合法 Hex。
5. 仅当组件有效样式完整匹配允许的 Token 时，收敛为 `design`。
6. 识别满足严格结构的 ActionUnit capsule/icon-round。
7. 不能收敛的协议内样式保留为显式属性。
8. 输出使用到的 path 对应 data 行。
9. 对极简 DSL 执行转换器协议校验和 TaskSpec 上下文校验；不以当前 PROMPT 的固定布局和 Variant 作为失败条件。

逆向转换必须确定性：相同输入、相同版本应逐字节生成相同中间态。

## 6. Roundtrip 验收

每条样本必须执行：

```text
source final A2UI
→ reverse
→ Design Compact 极简 DSL
→ official forward converter
→ roundtrip final A2UI
```

必须一致：

- 组件类型、ID、父子关系和可达树。
- 可见文案和动态绑定 path。
- DataModel 预览值。
- Image `src`。
- `onClick.call` 和完整 `args`。
- 最终有效样式，包括字号、字重、尺寸、间距、颜色、圆角、进度和勾选样式。

允许差异：

- JSON 对象 key 顺序。
- 不影响树和消息语义的序列化空白。
- 经双方明确登记的默认值或无渲染字段归一化。

不允许差异：

- 绑定变静态值或静态值变绑定。
- 素材、事件、文案或数据被替换。
- 因强行匹配 Token 导致有效样式变化。
- 依赖转换器修复、猜测、默认文案或静默降级才能通过。

每条样本输出机器可读报告：

```json
{
  "caseId": "q001",
  "reverse": "pass",
  "compactValidation": "pass",
  "forward": "pass",
  "roundtrip": "pass",
  "differences": []
}
```

整批数据只有在所有样本 roundtrip 通过后才能进入 SFT 数据集。

## 7. 生产方与接入方职责

数据生产方负责：

- 生成 TaskSpec 和最终 A2UI DSL。
- 保证最终 DSL 可解析、可渲染、结构合理、绑定正确、候选经过筛选。
- 使用固定版本转换器的目标样式展开值，使结果可逆。
- 根据 roundtrip 差异修正最终 DSL。

接入方负责：

- 冻结并交付正向转换器版本；若生产侧需要生成参考，可同时提供 PROMPT，但它不限制合理布局扩展。
- 提供最终 A2UI→极简 DSL 的逆向工具。
- 提供一键 roundtrip 校验入口和差异报告。
- 从冻结转换器维护 Token 支持快照、颜色反查优先级和允许归一化字段。
- 生成最终 SFT 标签，生产方不手工编辑中间态。

## 8. 最小交接包

建议只交接以下内容：

```text
frameworks/verl/create_my_card/data_pipeline/converters/
  README.md                         # 转换器版本、API、CLI 与规范化规则
  compact_dsl_a2ui_converter.py     # 同版本正向转换器
  reverse_and_verify.py             # 逆向转换 + roundtrip 校验统一入口

docs/create_my_card/
  data-production-handoff.md        # 数据生产合同
  data-quality-spec.md              # 验收规范
  expression-profile-v1.md          # 复合动态表达式闭集
```

不需要交接：

- 99 条或 45 条历史审计材料。
- PNG 和逐组件 style/design 快照。
- 历史迁移脚本和兼容适配器。
- 完整云侧方案文档。
- 与当前 TaskSpec 已提供候选无关的能力清单副本。

## 9. 当前工具状态

正向转换器与 `reverse_and_verify.py` 已统一放在 `frameworks/verl/create_my_card/data_pipeline/converters/`。逆向入口会依次执行 A2UI 解析、Compact 生成与校验、正向回转和结构化差异比较；遇到协议外或不可逆字段时直接失败，不静默丢弃。

当前冻结扩展包括：Surface 不输出 `width/height`、Image 保留 `fillColor`、`layoutWeight` 支持动态 path binding，以及结构化 `expression` binding。表达式生成范围以 [Expression Profile v1](expression-profile-v1.md) 为准。

单条调用方式和退出码见[转换器说明](../../frameworks/verl/create_my_card/data_pipeline/converters/README.md)。批量生产必须固定转换器提交或文件哈希，并对整个批次执行 roundtrip。
