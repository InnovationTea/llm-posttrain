# Design Compact 数据质检规范

## 1. 质检目标

本规范用于验收以下数据链路：

```text
TaskSpec
→ 生产方最终 A2UI DSL
→ 逆向生成 Design Compact 极简 DSL
→ 正向转换为 roundtrip A2UI DSL
→ 构造 TaskSpec → 极简 DSL 的 SFT 样本
```

质检需要同时回答四个问题：

1. 输入 TaskSpec 是否完整、内部一致、可用于生成。
2. 生产方最终 A2UI 是否可解析、可渲染、语义正确且可逆。
3. 逆向得到的极简 DSL 是否符合冻结转换器的可执行协议，并完整保留合理布局。
4. 极简 DSL 正向转换后是否与生产方最终 A2UI 等效。

本规范不重新判断外部数据、事件和素材能力是否真实存在；其合法性由上游保证。质检只检查最终 DSL 是否严格使用 TaskSpec 提供的 schema、事件和素材候选。

## 2. 版本门禁

开始质检前必须冻结并记录：

```text
forwardConverterCommit / forwardConverterSha256
reverseToolCommit / reverseToolSha256
validatorCommit / validatorSha256
rendererVersion
promptCommit / promptSha256             # 仅在实际使用该提示词时记录
```

同一批数据必须使用同一组可执行工具版本。正向转换器、逆向工具、校验器或渲染器变化后，历史通过结果自动失效，必须重新执行协议校验和 roundtrip。仅修改 PROMPT 的推荐布局，不会使已经通过转换器 roundtrip 的数据自动失效。

Token 支持闭集以冻结版本正向转换器为准：Design Token 从 `_COMPONENT_DESIGNS` 抽取，`ActionUnit.state` 按转换器校验与展开逻辑抽取。Token 不要求同时出现在 PROMPT 中；PROMPT 未列举只表示没有重点推荐，不构成质检失败。颜色可以保留为合法 Hex，颜色 Token 化只作为可选压缩，不作为验收门槛。

当前工具版本、API 和文件哈希以[正逆向转换器说明](../../frameworks/verl/create_my_card/data_pipeline/converters/README.md)为准。

## 3. 问题等级

| 等级 | 含义 | 处理 |
| --- | --- | --- |
| P0 | 标签错误、协议非法、语义改变、无法转换或无法 roundtrip | 样本拒收；整批存在系统性 P0 时暂停生产 |
| P1 | 可渲染但布局、候选筛选、样式收敛或泛化性明显较差 | 修正后复检；不能用自动修复掩盖 |
| P2 | 不影响正确性的低风险一致性、命名或格式问题 | 可进入整改队列，但必须记录 |

整批准入要求：

- P0 为 0。
- 每条样本的逆向、极简协议校验、正向转换和 roundtrip 全部通过。
- P1 必须完成处理，或由负责人逐项书面接受。
- 所有报告、文件哈希和样本计数一致。

## 4. 单样本质检流程

固定执行顺序：

```text
文件完整性
→ TaskSpec
→ 最终 A2UI 语法和协议
→ 语义、绑定、候选引用
→ 结构和布局
→ 样式可逆性
→ 逆向极简 DSL
→ 极简协议与上下文
→ 正向转换
→ roundtrip 比较
→ 渲染检查
→ SFT 记录检查
```

任一步出现 P0，即停止该样本后续打包，但仍应尽可能输出完整诊断信息。

## 5. 文件与包完整性

每条样本最低要求：

```text
<case-id>/task-spec.json
<case-id>/final.card.genui.jsonl
```

检查项：

- case ID 唯一，文件名和 manifest 一致。
- JSON/NDJSON 使用 UTF-8，无 BOM、截断行和额外说明文字。
- manifest 中的文件数、样本数、相对路径、字节数和 SHA-256 与实物一致。
- 不混入临时文件、历史版本、人工备份和未声明附件。
- 同一文件不以多个路径重复交付。

以下情况为 P0：缺文件、重复 case ID、manifest 哈希错误、JSON 无法解析、标签与 case 错配。

## 6. TaskSpec 检查

### 6.1 基本结构

- `userQuery` 为非空字符串，能描述单张卡片用途。
- `size` 能被冻结转换器处理，并与最终 Surface 尺寸一致；批次可在 manifest 中另行限定尺寸范围。
- `dataModelSchema` 可递归解析，叶子类型和 `sampleValue` 类型一致。
- `assetCandidates` 和 `eventCandidates` 缺省时按空列表处理，不补造候选。
- 候选对象不存在重复、截断或字段类型错误。

### 6.2 候选质量

- 候选是可选白名单，不是要求全部使用的清单。
- 可以包含合理的未使用候选，用于训练筛选能力。
- 未使用候选不能全部固定在列表末尾。
- 不以大量明显无关噪声制造虚假筛选难度。
- 不要求每条样本都存在事件或素材。

### 6.3 内部一致性

- `userQuery`、schema、候选素材和候选事件描述的是相容场景。
- schema 中用于定位的名称、地点等字段不应挤掉 Query 明确要求的核心状态。
- 事件参数只用于执行，不作为可见数据源。
- 素材路径只作为候选资源，不作为业务事实。

## 7. 最终 A2UI DSL 检查

### 7.1 语法与消息

- 每一行均为完整合法 JSON。
- 消息类型、Surface、组件更新和 DataModel 更新符合最终 A2UI 协议。
- 不包含 Markdown 围栏、解释文字或极简 DSL 元组。
- 最终 A2UI 中不出现 `design`、颜色 Token 名或 `ActionUnit` 等中间态字段/组件。
- 组件属性必须位于协议规定位置，不能写到对象或消息外层。

### 7.2 组件树

- root 唯一，尺寸与 TaskSpec 一致。
- 组件 ID 唯一。
- children 引用全部有定义。
- 除 root 外，每个组件恰有一个父节点。
- 所有组件从 root 可达，无孤儿节点和循环。
- 容器与叶子组件的 children 使用合法。
- 组件顺序满足解析和渲染要求。

### 7.3 数据绑定

- 每个动态绑定 path 都能在 `dataModelSchema` 中解析到兼容类型的叶子。
- 单一路径使用结构化 `path` binding，复合计算使用结构化 `expression` binding；表达式必须符合 [Expression Profile v1](expression-profile-v1.md) 的冻结闭集。
- 每个实际绑定 path 有对应预览数据。
- 可变业务事实没有被 `sampleValue` 静态写死。
- 静态标题、单位和解释标签不是伪造的动态事实。
- 不使用 Query、事件参数或素材路径冒充数据绑定。
- 未使用 schema 字段不需要输出预览数据。

以下情况为 P0：不存在的 path、类型不匹配、动态值静态泄漏、绑定和预览值指向不同事实。

### 7.4 事件与素材

- 最终 `onClick.call + args` 与某一个 `eventCandidates` 完整一致。
- 不从两个候选拼接事件，不改写参数，不把参数显示为文案。
- action 数量和落点符合业务语义、最终协议及转换器能力；无闭环事件时允许没有 action，不按当前 PROMPT 的固定 Variant 强制数量。
- 最终 Image `src` 必须来自 `assetCandidates`。
- 即使存在素材候选，也允许因语义或容量原因不生成 Image。
- 图标角色明确：内容图标不能因为路径相同就冒充动作图标。

## 8. 结构与布局检查

布局质检用于发现溢出、冗余包装和视觉问题，不用于要求数据命中 PROMPT 的固定 Variant，也不影响合法布局的逆向资格。逆向工具不得重新规划布局；需要专门判定的压缩点主要是 Design Token 匹配。

### 8.1 自动检查

- root 尺寸与 TaskSpec 及转换器尺寸规则一致；padding、圆角和裁剪按实际设计及有效渲染结果检查，不套用 PROMPT 示例常量。
- 纵向内容流主要使用 Column，横向内容流主要使用 Row。
- Stack 只用于真实叠加、覆盖或独立定位。
- 单子节点 Stack 必须能证明存在叠加或定位需求，否则记为 P1。
- 不存在空容器、零尺寸可见组件、超出画布的核心内容或组件相互遮挡。
- 文字行数、组件数量和 action 位置在实际画布内合理，不要求命中当前 PROMPT 的固定布局合同。
- 合理扩展的 Row、Column、Stack 或其它转换器支持结构应原样保留；质检不得为了命中示例 Variant 改写组件树。
- 不通过 `clip`、透明度或极端负边距掩盖溢出。

### 8.2 人工视觉检查

首批或 Token/布局规则变更后的批次应全量人工检查；流程稳定后可按风险分层抽检，但所有自动告警样本必须人工检查。

人工检查至少确认：

- 一眼能识别卡片用途和主信息。
- 没有折行异常、截断核心信息、重叠和视觉越界。
- 标题、主读数、辅助信息和 action 层级清楚。
- 素材与场景相符，不使用无关图标填空。
- 色彩、对比度和按钮状态没有明显渲染问题。
- 逆向前后截图无肉眼可见差异。

## 9. 样式与 Token 可逆性

质检工具应从冻结版本转换器生成 Token 展开快照，不人工维护第二份样式表。

对每个组件记录：

```text
designCapable
matchedDesign
matchedColorTokens
explicitRemainingProps
unmatchedRenderProps
ambiguousMatches
```

检查规则：

- 只有完整匹配冻结转换器所支持 Token 的属性组才能收敛为 `design`。
- 同一属性组命中多个 Token 时，必须有固定、版本化的优先级。
- 不允许仅修改一个字号、圆角、尺寸或 padding 后仍强行套用原 Token。
- Token 未覆盖但协议允许的渲染属性可以显式保留。
- 协议无法表达的有效样式必须报错，不能静默删除。
- 无渲染字段只有进入明确 ignore list 后才能归一化删除。
- 若启用颜色 Hex→Token 压缩，同值别名必须按固定优先级生成唯一结果；也允许直接保留合法 Hex。
- 未知颜色字符串不得原样进入极简 DSL；只能是已登记颜色 Token或合法 Hex。

Token 命中率用于观察，不作为“越高越好”的单一指标。禁止为了提高命中率修改业务语义、删除有效样式或编造 Token。

## 10. 极简 DSL 检查

### 10.1 输出形态

- 极简 DSL 原始产物仅包含组件元组行和 data 行。
- SFT assistant 是否增加单个 `genui` 围栏由数据集包装约定统一决定，不因当前 PROMPT 的展示格式限制合理布局。
- 每行可独立解析为 JSON 数组。
- 第一条组件为 root，父先子后。
- 不包含最终 A2UI 三段消息、解释、计划和审计信息。

### 10.2 协议闭集

- 组件、属性、事件、绑定形式、`design` 和 `ActionUnit.state` 符合冻结转换器的可执行协议；不以当前 PROMPT 的布局枚举作为白名单。
- 不添加 `accessibility` 或其它协议外解释字段。
- 不使用转换器支持表之外的自造或遗留 Token；Token 未被 PROMPT 列举本身不构成问题。
- 不依赖默认 Button 文案、自动补事件、尾逗号修复、绑定修复或其它容错逻辑。
- `ActionUnit` 的 state、label、icon 和 onClick 组合合法。
- 显式属性不能与 `design` 形成不允许的半覆盖。

### 10.3 上下文

- path、素材和事件均可追溯到同一条 TaskSpec。
- 未使用候选不会被偷偷加入中间态。
- 每个绑定 path 有且只有必要的 data 预览行。
- 静态文案与 Query 和所绑定字段语义一致。

## 11. Roundtrip 比较

比较前对 source A2UI 和 roundtrip A2UI 做相同的规范化；规范化规则必须版本化并写入报告。

### 11.1 必须等效

- Surface 尺寸和根壳。
- 组件类型、ID、父子关系和树可达性。
- 可见内容、绑定路径和预览数据。
- Image `src`。
- `onClick.call`、`args` 和启用状态。
- 所有有效渲染样式：尺寸、间距、字号、字重、颜色、圆角、渐变、Progress、Divider 和 Checkbox 样式。

### 11.2 允许归一化

- JSON key 顺序和无意义空白。
- 经双方登记的消息/组件安全排序。
- 明确登记且不影响渲染或语义的默认字段。
- 等价的数值序列化形式，例如规则明确允许时的 `1` 与 `1.0`。

### 11.3 禁止归一化

- 删除未知字段后宣称通过。
- 把动态绑定替换为当前 sampleValue。
- 改写文案、素材、事件或 path。
- 用渲染截图相近掩盖结构、事件或数据不一致。
- 用自动补默认值掩盖生产数据缺失。

Roundtrip 应同时输出结构化差异和可读摘要，不能只返回布尔值。

## 12. SFT 样本检查

每条训练记录至少包含：

```json
{
  "messages": [
    {"role": "system", "content": "<冻结的系统提示词或约定空值>"},
    {"role": "user", "content": "<完整 TaskSpec JSON>"},
    {"role": "assistant", "content": "<Design Compact 极简 DSL>"}
  ]
}
```

检查项：

- user 只包含该 case 的完整 TaskSpec，不串入答案或其它 case。
- assistant 是逆向并通过 roundtrip 的极简 DSL，不是生产方最终 A2UI。
- system 内容在整批内遵循同一约定。
- JSONL 每行是一条完整训练记录。
- 不包含本地绝对路径、审计备注、审批状态和工具日志。
- TaskSpec 与 assistant 中使用的 path、素材、事件逐项一致。
- 相同 TaskSpec 不对应多个冲突标签。

## 13. 批次级统计与泛化检查

逐条通过不代表整批分布健康。批次报告至少统计：

### 13.1 数据与候选

- 样本数、schema 叶子数、绑定叶子数和静态值泄漏数。
- 有/无事件候选、有/无最终 action 的样本数。
- 事件候选总数、使用数、未使用数和使用率分布。
- 素材候选总数、使用数、未使用数和使用率分布。
- 候选全部使用、部分使用、全部舍弃三类样本分布。
- 未使用候选在列表中的位置分布。

若整批事件或素材候选再次接近“提供即全部使用”，记为数据集级 P1，要求补充筛选样本。

### 13.2 结构

- Column、Row、Stack 和各叶子组件使用次数。
- 单子节点 Stack 数量及人工确认结果。
- 空容器、孤儿组件、最大树深和最大组件数。
- 各布局配置和 action 形态的覆盖情况。

### 13.3 样式

- 每个允许 Design Token 的命中次数。
- 显式样式组件数和无法收敛的属性分布。
- 颜色 Token 与显式 Hex 使用分布。
- Token 歧义、半匹配和未知颜色数量。
- 不同完整显式样式对象的数量，监测逐实例样式爆炸。

### 13.4 重复与污染

- 完全重复 TaskSpec、完全重复标签和近重复样本。
- Query、sampleValue 或最终文案跨 case 异常复制。
- 示例模板中的占位事件、素材路径和示例文案泄漏。
- 本地路径、用户名、审批备注和工具日志污染。

分布项默认用于发现异常，不凭空设置通过比例。批次目标比例应由正式造数方案另行冻结，并写入 manifest。

## 14. 报告格式

### 14.1 单样本报告

`reverse_and_verify.py` 当前输出以下结构；工具版本哈希由批次 manifest 统一记录：

```json
{
  "caseId": "q001",
  "size": "2x2",
  "reverse": "pass",
  "compactValidation": "pass",
  "contextValidation": "pass",
  "forward": "pass",
  "roundtrip": "pass",
  "differences": [],
  "warnings": [],
  "sourceSha256": "<sha256>",
  "compactSha256": "<sha256>",
  "roundtripSha256": "<sha256>"
}
```

### 14.2 Roundtrip difference 结构

```json
{
  "path": "$.components.title.styles.fontSize",
  "kind": "changed",
  "source": 14,
  "roundtrip": 16
}
```

`kind` 为 `added`、`removed` 或 `changed`。质量问题等级、人工处理结论和下面的 Issue 代码属于批次审计层，不由单条转换器自动推断。

建议代码前缀：

```text
PKG   文件与 manifest
TS    TaskSpec
A2UI  最终协议
SEM   语义与候选
BIND  数据绑定
LAY   结构与布局
STYLE 样式与 Token
CDSL  极简协议
RT    roundtrip
RENDER 渲染
SFT   训练记录
DIST  批次分布
```

### 14.3 批次报告

整批输出：

```text
reports/
  cases/<case-id>.json
  batch-summary.json
  batch-summary.md
  FILE_MANIFEST.sha256
```

批次摘要必须列出样本总数、通过数、各等级问题数、失败 case、Token/候选/结构分布和版本哈希。

## 15. 自动修复边界

质检默认只报告，不修改源数据。

允许的机械规范化：

- JSON key 排序和空白格式化。
- 已登记的安全消息排序。
- 同义数值序列化归一化。

禁止自动修复：

- 编造、替换或删除业务文案。
- 修改 path、sampleValue、素材和事件。
- 给 Button 或 ActionUnit 补默认文案、事件或图标。
- 为命中 Token 修改样式。
- 删除未知字段后继续通过。
- 把静态值猜测成绑定，或把绑定固化为 sampleValue。

发生禁止项时必须返回 P0/P1，并由生产方修改源 DSL 后重新走完整流程。

## 16. 质检入口

当前单样本逆向与 roundtrip 校验入口为：

```text
python frameworks/verl/create_my_card/data_pipeline/converters/reverse_and_verify.py \
  --task-spec <case>/task-spec.json \
  --source-a2ui <case>/final.card.genui.jsonl \
  --compact-out <case>/design-compact.card.genui.jsonl \
  --roundtrip-out <case>/roundtrip.card.genui.jsonl \
  --report-out reports/cases/<case-id>.json
```

完整 TaskSpec 用于校验 path、事件和素材候选；若只有 schema，可改用 `--card-spec <case>/card-spec.json`，但上下文校验范围会相应缩小。仓库暂未提供独立的批次审计脚本；批量生产流程应逐条调用该入口，并在外层聚合退出码和 JSON 报告。命令、退出码和报告 schema 变更时应同步更新本文及回归数据。

## 17. 最终放行清单

发布数据集前逐项确认：

- [ ] 正向转换器、逆向工具、校验器和渲染器版本已冻结；若实际使用 PROMPT，其版本也已记录。
- [ ] manifest 与全部文件哈希一致。
- [ ] 每条 TaskSpec、最终 A2UI 和 SFT 记录一一对应。
- [ ] 所有样本 P0 为 0。
- [ ] 所有样本逆向、极简校验、正向转换和 roundtrip 通过。
- [ ] 动态值静态泄漏为 0。
- [ ] 协议外字段和未知 Token 为 0。
- [ ] 素材、事件和 path 均来自对应 TaskSpec。
- [ ] 单子节点定位 Stack 已清理或有明确叠加证明。
- [ ] 候选使用分布不存在“提供即全用”的系统性模式。
- [ ] 首批或规则变更批次已完成全量人工视觉检查。
- [ ] SFT assistant 标签为极简 DSL，不是最终 A2UI。
- [ ] 单样本报告、批次摘要和文件哈希均已归档。
