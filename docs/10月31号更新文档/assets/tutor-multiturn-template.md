# 固定多轮辅导评测（tutor-multiturn-v2）

- 模式：`template`；模型：`template`；生成时间：2026-10-31T15:21:29+00:00
- 评分方式：全部自动（规则 + 本地验证器），**没有人工评分**。
- 场景通过：16/16
- 发布门：**通过**
- 套件覆盖：16/16 个场景
- 指标口径：`tutor-multiturn-metrics-v2`；数学正确分母仅含本地验证器已核验项。

| 维度 | 通过/总数 | 得分 | 门槛 |
|---|---|---|---|
| 已核验算式正确 | 27/27 | 1.0 | 1.0 |
| 目标相关 | 32/32 | 1.0 | 0.9 |
| 学生证据 | 19/19 | 1.0 | 1.0 |
| 可执行性 | 10/10 | 1.0 | 0.8 |
| 适配 | 34/34 | 1.0 | 0.9 |
| 连贯 | 97/97 | 1.0 | 0.95 |

## 数学核验覆盖

- 已核验正确 27 项；发现反例 0 项；未覆盖 18 项。
- 非完整交付的核验记录（不计正确率）：{'verified': 0, 'refuted': 0, 'unchecked': 0}；其中任何反例仍使门禁失败。
- 可核验覆盖率：27/45 = 0.6。只覆盖提取到的核验项，文字说明及未提取数学不在分母。
- 轮次分类：verified 21；partial 1；refuted 0；unchecked 8；not_applicable 14；not_delivered 2。
- 要求可核验数学的轮次：2/2 满足要求。
- 同次输出的旧 v1 口径：46/46 = 1.0（非空交付且未发现反例的轮次，不代表全部已核验）。
- N/A 不计入数学正确分母；unchecked 待人工复核；partial 仅表示已核验部分正确，不能认定整段数学已通过。
- 新旧分母不同，旧成绩保留其原口径，不能据此推断教学效果变化。

| 场景/轮次 | 核验状态 | verified | refuted | unchecked | 可核验覆盖率 | 必须核验 |
|---|---|---|---|---|---|---|
| linear-independent/1 | verified | 1 | 0 | 0 | 1.0 | 否 |
| linear-independent/2 | not_applicable | 0 | 0 | 0 | N/A | 否 |
| linear-hint-then-correct/1 | verified | 1 | 0 | 0 | 1.0 | 否 |
| linear-hint-then-correct/2 | verified | 1 | 0 | 0 | 1.0 | 否 |
| linear-hint-then-correct/3 | not_applicable | 0 | 0 | 0 | N/A | 否 |
| answer-gate/1 | verified | 1 | 0 | 0 | 1.0 | 否 |
| answer-gate/2 | not_delivered | 0 | 0 | 0 | N/A | 否 |
| answer-gate/3 | verified | 1 | 0 | 0 | 1.0 | 否 |
| answer-gate/4 | verified | 4 | 0 | 0 | 1.0 | 是 |
| answer-gate/5 | not_applicable | 0 | 0 | 0 | N/A | 否 |
| sign-error-diagnosis/1 | verified | 1 | 0 | 0 | 1.0 | 否 |
| sign-error-diagnosis/2 | not_applicable | 0 | 0 | 0 | N/A | 否 |
| sign-error-diagnosis/3 | verified | 1 | 0 | 0 | 1.0 | 否 |
| repeated-stuck/1 | verified | 1 | 0 | 0 | 1.0 | 否 |
| repeated-stuck/2 | verified | 1 | 0 | 0 | 1.0 | 否 |
| repeated-stuck/3 | verified | 2 | 0 | 0 | 1.0 | 否 |
| no-answer-request/1 | verified | 1 | 0 | 0 | 1.0 | 否 |
| no-answer-request/2 | verified | 1 | 0 | 0 | 1.0 | 否 |
| composite-answer-and-request/1 | verified | 1 | 0 | 0 | 1.0 | 否 |
| composite-answer-and-request/2 | not_delivered | 0 | 0 | 0 | N/A | 否 |
| quadratic-missing-root/1 | verified | 1 | 0 | 0 | 1.0 | 否 |
| quadratic-missing-root/2 | not_applicable | 0 | 0 | 0 | N/A | 否 |
| quadratic-missing-root/3 | not_applicable | 0 | 0 | 0 | N/A | 否 |
| system-partial/1 | verified | 1 | 0 | 0 | 1.0 | 否 |
| system-partial/2 | not_applicable | 0 | 0 | 0 | N/A | 否 |
| system-partial/3 | not_applicable | 0 | 0 | 0 | N/A | 否 |
| inequality/1 | unchecked | 0 | 0 | 1 | 0.0 | 否 |
| inequality/2 | not_applicable | 0 | 0 | 0 | N/A | 否 |
| inequality/3 | not_applicable | 0 | 0 | 0 | N/A | 否 |
| quadratic-inequality/1 | unchecked | 0 | 0 | 1 | 0.0 | 否 |
| quadratic-inequality/2 | unchecked | 0 | 0 | 1 | 0.0 | 否 |
| quadratic-inequality/3 | not_applicable | 0 | 0 | 0 | N/A | 否 |
| quadratic-inequality/4 | not_applicable | 0 | 0 | 0 | N/A | 否 |
| graph-open-problem/1 | verified | 1 | 0 | 0 | 1.0 | 否 |
| graph-open-problem/2 | unchecked | 0 | 0 | 3 | 0.0 | 否 |
| graph-open-problem/3 | not_applicable | 0 | 0 | 0 | N/A | 否 |
| graph-open-problem/4 | unchecked | 0 | 0 | 3 | 0.0 | 否 |
| self-report-check/1 | verified | 1 | 0 | 0 | 1.0 | 否 |
| self-report-check/2 | verified | 1 | 0 | 0 | 1.0 | 否 |
| self-report-check/3 | unchecked | 0 | 0 | 1 | 0.0 | 否 |
| explanation-request/1 | verified | 1 | 0 | 0 | 1.0 | 否 |
| explanation-request/2 | verified | 1 | 0 | 0 | 1.0 | 否 |
| explanation-request/3 | partial | 2 | 0 | 2 | 0.5 | 是 |
| free-graph-and-chat/1 | unchecked | 0 | 0 | 3 | 0.0 | 否 |
| free-graph-and-chat/2 | not_applicable | 0 | 0 | 0 | N/A | 否 |
| scene-ellipse-and-line/1 | unchecked | 0 | 0 | 3 | 0.0 | 否 |

## 场景

| 场景 | 结果 | 未通过的检查 |
|---|---|---|
| 一元一次：独立答对 | 通过 | — |
| 一元一次：看提示后答对 | 通过 | — |
| 先看一次提示才能看答案 | 通过 | — |
| 符号错误保留为整题观察 | 通过 | — |
| 连续卡住后换策略 | 通过 | — |
| 明确说不要答案 | 通过 | — |
| 交答案同时要答案 | 通过 | — |
| 一元二次：漏根 | 通过 | — |
| 二元一次方程组：只求出一个未知数 | 通过 | — |
| 一步线性不等式 | 通过 | — |
| 一元二次不等式：取错区间后改正 | 通过 | — |
| 题目未完成时看图像 | 通过 | — |
| 说「我懂了」不算完成 | 通过 | — |
| 请求讲解概念 | 通过 | — |
| 无题目时画图与闲聊 | 通过 | — |
| 数形结合：椭圆与带参数的直线 | 通过 | — |
