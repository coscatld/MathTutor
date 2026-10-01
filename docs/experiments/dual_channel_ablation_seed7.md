# 双通道门控对照实验（2026-10-01）

- 门控策略版本：`mt-dual-channel-gate-v1`；随机种子：7；题目：60 道（一次方程 30、二次方程 15、二元一次方程组 15）
- 教材例题勘误比例（模拟资料自身有错）：12 / 60
- 方法：故障注入。模型输出按已知真值程序化生成，全部经过真实的知识库、引用凭证、解析/求解/验证器、披露投影与输出守卫。
  结果是各配置“放行了什么”的精确比例，不代表真实大模型犯各类错误的频率。
- 总结支持检查器在本实验中恒为“支持”（语料中的总结都引用了真实原文），E1 只隔离合流规则的作用。

## E1 声明门控：四种配置

| 配置 | 错误数学结论无警示展示率 ↓ | 虚假引用展示率 ↓ | 正确内容保留率 ↑ | 原文-数学冲突提示率 ↑ | 勘误原文保留率 |
|---|---|---|---|---|---|
| A 无门控 | 100.0% | 100.0% | 100.0% | 0.0% | 100.0% |
| B 仅来源核验 | 100.0% | 0.0% | 100.0% | 0.0% | 100.0% |
| C 仅数学核验 | 0.0% | 100.0% | 100.0% | 0.0% | 0.0% |
| D 双通道门控（本发明） | 0.0% | 0.0% | 100.0% | 100.0% | 100.0% |

样本数：clean 168，forged_citation 180，model_math_error 120，source_ok_math_wrong 12

### 通道状态分布（真值标签 × 来源状态 × 数学状态）

| 标签 | 来源 | 数学 | 数量 |
|---|---|---|---|
| clean | none | correct | 60 |
| clean | quote_ok | correct | 48 |
| clean | summary_ok | correct | 60 |
| forged_citation | rejected | correct | 180 |
| model_math_error | none | incorrect | 60 |
| model_math_error | summary_ok | incorrect | 60 |
| source_ok_math_wrong | quote_ok | incorrect | 12 |

## E2 答案披露：投影 + 输出守卫

| 等级 | 基线（完整解答放入上下文）答案在上下文中 | 投影后答案在上下文中 |
|---|---|---|
| L1 | 100.0% | 0.0% |
| L2 | 100.0% | 0.0% |
| L3 | 100.0% | 0.0% |
| L4 | 100.0% | 0.0% |

### 开发集（第一轮修复守卫时可见的表述）

| 注入的泄露形式 | 样本 | 守卫拦截率 |
|---|---|---|
| linear:assignment | 120 | 100.0% |
| linear:bare_value | 120 | 100.0% |
| linear:equivalent_root_eq | 120 | 100.0% |
| linear:spaced | 120 | 100.0% |
| linear:unreduced | 120 | 100.0% |
| quadratic:assignment | 60 | 100.0% |
| quadratic:bare_values | 60 | 100.0% |
| quadratic:factored | 60 | 100.0% |
| quadratic:indexed | 60 | 100.0% |
| system:assignment | 60 | 100.0% |
| system:partial_assignment | 60 | 100.0% |
| system:reversed | 60 | 100.0% |
| **合计** | 1020 | **100.0%** |

| 正常提示（不应拦截） | 样本 | 误拦截率 |
|---|---|---|
| linear:concept | 120 | 0.0% |
| linear:divide_coefficient | 120 | 0.0% |
| linear:move_constant | 120 | 0.0% |
| quadratic:concept | 60 | 0.0% |
| quadratic:discriminant | 60 | 0.0% |
| quadratic:factor_hint | 60 | 0.0% |
| system:concept | 60 | 0.0% |
| system:eliminate | 60 | 0.0% |
| **合计** | 660 | **0.0%** |

### 留出集 1（第一轮修复后新写；第二轮通用修复时可见）

| 注入的泄露形式 | 样本 | 守卫拦截率 |
|---|---|---|
| linear:answer_colon | 120 | 90.0% |
| linear:decimal | 120 | 90.0% |
| linear:fullwidth_equals | 120 | 100.0% |
| linear:substitute_claim | 120 | 100.0% |
| quadratic:shared_variable | 60 | 100.0% |
| quadratic:solution_set | 60 | 60.0% |
| quadratic:subscript | 60 | 100.0% |
| system:chinese_is | 60 | 73.3% |
| system:tuple | 60 | 73.3% |
| **合计** | 780 | **89.7%** |

| 正常提示（不应拦截） | 样本 | 误拦截率 |
|---|---|---|
| linear:add_both_sides | 120 | 0.0% |
| linear:check_wrong_value | 120 | 0.0% |
| linear:coefficient | 120 | 0.0% |
| quadratic:check_wrong_value | 60 | 0.0% |
| quadratic:vieta_hint | 60 | 0.0% |
| system:check_wrong_value | 60 | 0.0% |
| system:substitute_hint | 60 | 0.0% |
| **合计** | 600 | **0.0%** |

### 留出集 2（第二轮修复前写好，从未用于调整守卫）

| 注入的泄露形式 | 样本 | 守卫拦截率 |
|---|---|---|
| linear:approx | 120 | 100.0% |
| linear:fill_in | 120 | 90.0% |
| linear:value_is_x | 120 | 90.0% |
| quadratic:enumeration_comma | 60 | 60.0% |
| quadratic:equals_or | 60 | 60.0% |
| quadratic:roots_and | 60 | 100.0% |
| system:fullwidth_semicolon | 60 | 100.0% |
| system:respectively | 60 | 73.3% |
| **合计** | 660 | **86.7%** |

| 正常提示（不应拦截） | 样本 | 误拦截率 |
|---|---|---|
| linear:coefficient_first | 120 | 0.0% |
| linear:rhs_constant | 120 | 0.0% |
| quadratic:constant_term | 60 | 0.0% |
| system:subtract_hint | 60 | 0.0% |
| **合计** | 360 | **0.0%** |
