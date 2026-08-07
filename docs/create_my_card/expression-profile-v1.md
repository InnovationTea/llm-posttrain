# Design Compact Expression Profile v1

状态：冻结
版本：1.0
冻结日期：2026-08-07

## 1. 目标与表示

本规范定义 Design Compact DSL 中动态绑定和复合表达式的生成闭集。数据生产侧不得生成本文未列出的表达式能力。

属性值完全来自一个 DataModel 路径时使用：

```json
{"path":"/data/weather/temperature"}
```

需要拼接、判断或计算时使用：

```json
{"expression":"${/data/weather/temperature} + '°'"}
```

正向转换器分别生成：

```text
{{ ${/data/weather/temperature} }}
{{ ${/data/weather/temperature} + '°' }}
```

`path` 或 `expression` 对象只能包含对应的单个字段。表达式主体不得携带外层 `{{ }}`，不得有首尾空白，并且必须至少引用一个合法、实际存在的 DataModel JSON Pointer。

## 2. 支持的值与运算符

| 类型 | 支持格式 | 示例 |
| --- | --- | --- |
| DataModel 路径 | `${/json/pointer}` | `${/data/value}` |
| 字符串 | 单引号或双引号 | `'已连接'`、`"已连接"` |
| 数字 | 十进制整数或小数 | `0`、`-1`、`1.5`、`.5` |
| 布尔值 | 小写关键字 | `true`、`false` |
| 空值 | 小写关键字 | `null` |

不支持科学计数法，例如 `1e3`。

| 分类 | 运算符 |
| --- | --- |
| 算术 | `+`、`-`、`*`、`/`、`%` |
| 相等比较 | `==`、`!=`、`===`、`!==` |
| 大小比较 | `>`、`>=`、`<`、`<=` |
| 逻辑 | `&&`、`||`、`!` |
| 条件 | `condition ? value1 : value2` |
| 分组 | `(expression)` |

生成侧应遵循以下语法：

```text
expression     := conditional
conditional    := logical_or [ "?" expression ":" expression ]
logical_or     := logical_and { "||" logical_and }
logical_and    := equality { "&&" equality }
equality       := comparison { ("==" | "!=" | "===" | "!==") comparison }
comparison     := additive { (">" | ">=" | "<" | "<=") additive }
additive       := multiplicative { ("+" | "-") multiplicative }
multiplicative := unary { ("*" | "/" | "%") unary }
unary          := ["!" | "+" | "-"] primary
primary        := path | string | number | true | false | null | "(" expression ")"
```

## 3. 冻结的属性范围

| 属性 | 最终类型 | 状态 |
| --- | --- | --- |
| `Text.content` | 字符串 | 已验证 |
| `backgroundColor` 等颜色属性 | ARGB 颜色字符串 | 已验证 `backgroundColor` |
| `Progress.value` | 数值 | 已验证 |
| `Progress.total` | 数值 | 转换器支持 |
| `layoutWeight` | 数值 | path 与 expression 均支持 |
| `Button.enabled`、`ActionUnit.enabled` | 布尔值 | 转换器支持 |
| `Checkbox.select` | 布尔值 | 转换器支持 |
| `Checkbox.label`、`Checkbox.value` | 字符串 | 转换器支持 |

除非同步扩展转换器、测试和本规范，不得在其他属性中生成复合表达式。

## 4. 类型要求

- 文本属性必须返回字符串。
- 颜色属性必须返回渲染侧支持的 ARGB 字符串，例如 `#FF64BB5C`。
- 数值属性必须返回有限数值，不得返回 `NaN` 或无穷值。
- 布尔属性必须返回 `true` 或 `false`。
- 三元表达式两个结果分支应返回相同类型。
- 除文本格式化外，不应依赖字符串与数字之间的隐式转换。

转换器校验结构、语法闭集和路径存在性，但不推断运行时返回类型；返回类型由数据生产侧负责。

## 5. 禁止范围

不得生成：

- 函数调用，例如 `format(...)`、`Math.round(...)`。
- 标识符或成员访问，例如 `value.length`。
- 数组、对象、正则表达式或反引号模板字符串。
- 可选链 `?.`、空值合并 `??`、位运算、赋值、自增或自减。
- `typeof`、`instanceof`、`in`、`new` 等关键字。
- `$item`、`$__dataModel` 或嵌套 `{{ ... }}`。
- 不引用 DataModel 路径的常量表达式。
- 仅包含 `${/path}` 的 expression；这种情况必须改用 `{"path":"/path"}`。

## 6. 标准示例

```json
{"expression":"${/data/weather/feelsLikeC} + '°'"}
```

```json
{"expression":"'清醒 ' + ${/data/sleep/awakeCount} + ' 次'"}
```

```json
{"expression":"${/data/device/isConnected} ? '已连接' : '未连接'"}
```

```json
{"expression":"${/data/device/isConnected} ? '#FF64BB5C' : '#99FFFFFF'"}
```

```json
{"expression":"${/data/goal} == 0 ? 0 : ${/data/current} * 100 / ${/data/goal}"}
```

## 7. 变更规则

v1 语义冻结。增加运算符、字面量、变量来源或目标属性时，必须同时更新正向校验、逆向恢复、合法/非法回归测试和本规范，并对完整闭集重新执行严格逆向与正向 roundtrip。新增能力通过新 Profile 版本发布，不直接改变 v1 语义。
