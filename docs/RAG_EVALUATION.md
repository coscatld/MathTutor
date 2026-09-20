# RAG EVALUATION

## 2026-09-20：0.4.2 纯离线数学条件与续写修复

**新增真实 Provider 调用0；预算未提高、未重置，仍75/120请求、293690/300000 token保守记账。离线回放通过不代表真实模型质量通过。** 详细映射见 [OFFLINE_MATH_REPAIR_042.md](OFFLINE_MATH_REPAIR_042.md)。

- 原B的`original-B-atomic-review.json`及旧分数保持只读。0.4.1新14篇和退化3篇分别新建审阅文件，79/28个声明，绑定原回答SHA256、请求编号、生成版本0.4.1与审阅版本0.4.2；新两组Faithfulness分数为null，全部AI provisional/人工PENDING。
- 修正版正常资料`math-conditions-corpus/1`独立于历史`hard-corpus/2`，修正两文件共16处a=0漏条件内容，新增参数/等价变形资料；原错误片段另存为来源含错组。证据直接支持不等于数学正确，旧chunk标注/指标不可迁移。
- 现有受限solver/verifier验证7个具体方程候选；常量恒等/矛盾方程、一般参数和分式方程仍UNKNOWN。含零根对的异号断言、同乘0不保等价、分母为0均有具体反例或受限运算依据，不用关键词给全文颁发VERIFIED。
- 保存014/015、072/073、074/075的原段和旧拼接全文；已证明错误句来自生成，句子粘连来自直接拼接。新拼接保留完整两段、显示待核对接缝并保持PARTIAL；产品WebSocket与持久化检查通过。合法句中续写也可能被保守标待核对，不声称自动判断语义衔接正确。
- Tutor新增数学条件提示词，**尚未真实模型复测**；新资料亦无新的检索/模型质量分数。最小人工审阅包在`artifacts/offline-math-042/human-review/index.html`，优先已标错及争议项，不含凭据或隐藏reasoning。

本轮源码版本0.4.2；定向57 passed，最终后端1389 passed / 11 skipped，Web164 passed，Desktop44 passed / 2 skipped；日志、源码摘要见`artifacts/offline-math-042/validation.json`和`source-manifest.json`。旧中断全量轮不计通过。当前状态为**离线修复已验证；真实模型质量未重新测量；人工验收待完成；新包未构建**，不借用0.4.0包外证据。以下0.4.1与更早结果均为保留的历史运行。

## 2026-09-20：0.4.1 交付修复、Knowledge 实测与逐声明复核

本节为最新结果；下面 0.4.0 首轮及 2026-09-19 离线记录均保留。**真实调用已完成；原表达题集交付故障修复有效；语义 AI 初审已完成、仍 provisional；开发质量 FAIL；正式验收 INSUFFICIENT_EVIDENCE。** 不沿用历史 BLOCKED_PROVIDER，不宣称人工通过。

| 分项 | 本轮实际结果 | 边界 |
|---|---|---|
| 真实调用 | 新增 51 次，累计 75/120；DeepSeek / deepseek-flash | 新记录保留服务端 model、终止原因和 usage 元数据；不回填旧记录缺失字段 |
| 表达交付 | 原 14 题修复后 14 NATURAL_STOP，0 模板、0 续写 | 交付完成不等于数学正确；正文有 3 题数学错误 |
| Knowledge | 3 个真实模型用例 + 1 个提示门控用例 | 工具收据与 support_check 记录独立于表达路径 |
| 原 B 语义复核 | 14 篇、57 个独立数学声明；五维记录完整 | 独立 AI 初审，非人工 gold、非正式冻结阈值验收 |
| 新版本工程 | 0.4.1 后端全量 1356 passed / 11 skipped；定向 86 passed；Web 164 passed；Desktop 44 passed / 2 skipped | 定向含全量启动后新增的7个评测守卫；未重建安装包，0.4.0 包外证据不迁移 |

证据目录：`artifacts/delivery-regression-20260920/`。`original-request-causal-map.json` 关联 request-001..024 与产品状态；`original-B-atomic-review.json` 保留完整学生正文、逐声明证据/数学/引用判断；`final-review.json` 汇总新回答及工具路径。原目录全部文件通过原 `evidence-manifest.json` SHA256 检查，无覆盖或删除。

### 六次 response_incomplete 的分层定位

六次最早**可观察**失败均为 Gateway 拒绝空/截断正文，尚未交付 CompletionResult；Runtime 捕获后标 PROVIDER_ERROR，TutorChatResponder 再返回模板。六次均只调用一次，未进入续写；hard 题的 `grace_call_used` 可以由第一次调用的预算预警触发，不代表实际续写。旧错误类别合并了两个分支，未保留原 HTTP，因此不能断言六次服务端原始原因相同。

| 原请求 | 产品题目 | 后续同参数诊断 | 能证明什么 |
|---|---|---|---|
| 013 | easy:formula | 025：length，正文 492 字符，reasoning 244 token | 可复现输出预算竞争，未复现空正文 |
| 018 | easy:cross_topic | 027：length，正文 442 字符，reasoning 241 token | 同上 |
| 020 | hard:Q01 | 028：HTTP 200 / length，正文 0，512 reasoning token | 512 输出额度全部用于 reasoning，Gateway 随后拒绝 |
| 021 | hard:Q02 | 029：length，正文 406 字符，reasoning 271 token | 未复现空正文，不倒推原始返回 |
| 022 | hard:Q03 | 030：length，正文 235 字符，reasoning 371 token | 同上 |
| 024 | hard:Q05 | 031：HTTP 200 / length，正文 0，512 reasoning token | 再次复现同一机制 |

这是请求模式与短输出预算的兼容问题，有原始响应元数据支持，不是仅凭 PROVIDER_ERROR 指责服务商。诊断只增加元数据记录，不保存隐藏 reasoning 正文。Gateway 现在在成功和空正文异常中保留安全诊断字段，且异常包装不丢失它们。

### easy:discriminant 的独立诊断及单变量修复

request-014 和 015 均请求 512、均返回 length；第一次交付长正文，第二次只交付“接”，最终学生看到 `Δ=16-16=接`。两次 usage 为 input 1883 + output 1024；总预算 16384，仍余 **13477**；步骤为 2/2，剩余 0。故不是总 token 用完，而是每次输出上限及续写机会耗尽。旧记录未保存 reasoning 分配，不能把新诊断冒充其原始明细。同一续写输入的诊断 request-026 返回 stop，并观察到 reasoning 249 token，说明旧失败不是每次必现。

先以保存的返回建立回放测试，再仅将 DeepSeek 请求的 `thinking` 显式设为 disabled。**未同时提高 512 上限、改变温度/题目/提示词/续写轮次/检索架构。** 完整原 14 题固定重跑 request-032..045，全部正常交付，每题一次。所有运行均保留，没有重跑挑最好答案。正常停止仅判断交付。

### Knowledge 实际工具路径与顺序修复

首次评测入口 URL 缺少 `/desktop` 导致 404，0 模型调用；记录保留在 `knowledge-fixed/`。纠正评测入口后，`knowledge-live/` 实测发现：应用已登记 seed 区间，模型收到的公共证据却没有 version/start/end，因而猜错范围，被拒后被迫重复 search。K1/K3 又把改写文字标成 quote，严格校验拒绝，support_check 尚未发生；不能记成“已检查”。

分两步修复，每步各自保留测试与实跑：① 将 seed_evidence 已核验的 read_source 参数传入初始提示。`knowledge-ranges/` 证明直接读取成功、无重复 search，但 quote 类型错误仍失败。② 只在既有 Claim Schema 明示 quote 必须 `text == evidence[0].quote`，改写应标 summary，缺失信息放 uncertainties；**不放宽引用验证，也不自动把错引改成可通过的总结**。

最终 `knowledge-final/`：

| 用例 | 实际模型请求 | 实际工具/检查 | 产品结果 |
|---|---|---|---|
| K1_summary | 063–065 | seed → read_source 成功 → summary → 真实 support_check=true；无 search | FINAL_ANSWER |
| K2_quote | 066–067 | seed → read_source 成功 → 逐字引用；无需 support_check | FINAL_ANSWER |
| K3_absent | 068–070 | read_source + search_knowledge；收据含 AGENT_SEARCH / hop_index=2；无作者证据 | FINAL_ANSWER，说明缺口 |
| K4_hint | 0 | 提示门控，无初始检索事件、工具或模型调用 | FINAL_ANSWER，保留提示边界 |

三次模型 Knowledge 回答中仅无答案题补搜，观察比例 1/3；这只是本小组的实际频率，不是总体性能估计。未测保存笔记、资料冲突、多轮追问，不能宣布覆盖全部 Knowledge 契约。总结检查来自实际产品路径，但其 true 也不等于独立人工数学验收。

### 语义评分与退化条件

原 B packet 保持只读，逐声明初审另存：57 个数学声明，DIRECT 与从可见前提局部推导的 DERIVED 计支持；新增数学常识单列 UNSTATED，数学正确性另评；重复转述合并，开放问题与鼓励语不当作事实断言。6 个模板的端到端 Faithfulness 记 0、数学正确性记不可评估，不设空集满分。

**原 14 题 provisional Faithfulness 宏平均 0.520153、最低 0；关键内容覆盖宏平均 0.571429；任务完成 6/14。** 内容覆盖与完成性分开：判别式虽覆盖核心知识，末尾仍截断；a=0 回答虽回应核心问题，错误的一次方程断言仍使任务失败。12 个引用链接已按邻近声明进行 AI 归属复核，均有对应来源；不把整篇新增推导都归于该引用。以上是本轮明确记录的复核准则，**并非事前冻结的人类标准或正式 gold**。

新 14 篇正文逐篇复核：仍有 easy:cross_topic 将“同乘0”说成无意义（实际是失去可逆等价/定义域约束问题）；hard:Q01/Q05 无条件称 a=0 后为一次方程。hard 语料本身含此错误，保持原语料未改；这说明“证据支持”不能代替数学正确。

新增 `degenerate-fixed/` 固定三题 request-071..075：a=0 的 b≠0、b=0/c≠0、b=c=0 分支回答正确；b=0、a≠0 的正/零/负根情形正确，但续写接缝有病句；c=0 的初段算式正确，续写却把根 0 与 -b/a 称为“一正一负（或一零一非零）”，反例 a=b=1,c=0 得 0,-1。末两题还存在未妥善衔接的续写正文。**全部 NATURAL_STOP，仍不能全部判数学或正文质量通过。** 这些失败作为回归证据保留，不用算式子集正确掩盖全文问题。

### 预算与状态

累计 **75/120 请求、293690/300000 token 保守记账**，自动重试 0。原 169364 保守额度不退回；新请求先按 UTF-8+framing+输出上限预留，仅完整 usage 才按实际结算，未知保持预留。新增 51 次完整已知 usage 合计 124326（包括两次空正文失败）；首轮已知 14656，仍有 6 次原始失败 usage 未知，不能给出精确的全程实际总量。剩余保守额度 6310，本轮不再发起真实调用。

开发回归：交付修复有效、工具契约本组通过、语义质量 **FAIL**；正式验收：**INSUFFICIENT_EVIDENCE**（人工校准、正式冻结阈值、独立 holdout 与重复均不足）。版本 **0.4.1**；改动为 Gateway 模式与诊断、Knowledge seed 参数传递及引用 Schema 说明，未重构 RAG。新源码/配置摘要与每阶段请求摘要见 `source-manifest.json`、各阶段 `source-digest.json`，旧 0.4.0 工程门和安装包不作本版本证据。

## 2026-09-20：DeepSeek 真实开发回归

**SEMANTIC_MEASUREMENT=COMPLETE；SEMANTIC_QUALITY=FAIL（开发回归）；正式验收=INSUFFICIENT_EVIDENCE。** 下文 2026-09-19 与 `artifacts/rag-evaluation.json` 属于历史离线运行，保留 schema v2 / corpus / annotation；其中旧 BLOCKED_PROVIDER 不代表本轮。当前机器结果见 `artifacts/live-acceptance-20260920-v4/execution/review-summary.json`。

固定 Provider/Model：DeepSeek / `deepseek-flash`。模型标识证据是请求/配置值；生产 Gateway 未保留服务端原始 model 字段，不将它冒充服务端独立型号证明。生产 Gateway + SecretStore，零自动重试。A 使用生产 `check_claim_support`，被测输入严格只有 claim/evidence，参考标签不进入请求。B 通过产品 WebSocket，以当时可见摘录为复核依据。

### A：检查器

| case | 实际判断 | 运行前参考草案 | 执行 |
|---|---|---|---|
| CC1_verbatim | SUPPORTED | SUPPORTED | COMPLETED |
| CC2_over_cited | SUPPORTED | SUPPORTED | COMPLETED |
| INJ1_tampered_quote | NOT_SUPPORTED | NOT_SUPPORTED | COMPLETED |
| INJ2_fabricated_source | SUPPORTED | SUPPORTED | COMPLETED |
| INJ3_quote_kind_mismatch | SUPPORTED | SUPPORTED | COMPLETED |
| S_missing_author | NOT_SUPPORTED | NOT_SUPPORTED | COMPLETED |
| S_added_positive_roots | NOT_SUPPORTED | NOT_SUPPORTED | COMPLETED |
| S_wrong_source | NOT_SUPPORTED | NOT_SUPPORTED | COMPLETED |

有效判断覆盖率=8/8=100%，UNKNOWN/timeout/error 各 0。按事前草案计算的有依据通过率=4/4=100%、无依据误放行率=0/4=0%，**仅为 provisional**：参考由独立于 DeepSeek 的 Codex 提议，未经人工审核。8 行仅 6 个不同模型输入，不增加独立样本数。INJ2/INJ3 的原 citation 操作拒绝标签不变；这里输入真实证据、测语义支持，不能把它们的操作标签挪作语义 gold。

### B：真实回答

| case | 产品终止原因 | 实际观察 |
|---|---|---|
| easy:canonical_term | NATURAL_STOP | 定义回答；待逐声明人工复核 |
| easy:spoken_variant | NATURAL_STOP | 等式性质回答；数值例题确定性核验 |
| easy:transposition | NATURAL_STOP | 移项回答；数值例题确定性核验 |
| easy:formula | PROVIDER_ERROR | response_incomplete，模板未回答问题 |
| easy:discriminant | TOKEN_LIMIT | 一次产品续写后仍截断，末尾为未完成等式 |
| easy:commutative | NATURAL_STOP | 交换律回答；待人工复核 |
| easy:associative | NATURAL_STOP | 结合律回答；待人工复核 |
| easy:cross_topic | PROVIDER_ERROR | response_incomplete，模板未回答问题 |
| easy:mixed_cjk_latex | NATURAL_STOP | a=0 退化为一次方程的说法漏 b≠0 条件 |
| hard:Q01 | PROVIDER_ERROR | response_incomplete，模板未回答问题 |
| hard:Q02 | PROVIDER_ERROR | response_incomplete，未给要求的完整步骤 |
| hard:Q03 | PROVIDER_ERROR | response_incomplete，模板未回答问题 |
| hard:Q04 | NATURAL_STOP | 完全平方回答；展开式确定性核验 |
| hard:Q05 | PROVIDER_ERROR | response_incomplete，模板未回答问题 |

14/14 有真实请求；7 正常完成、6 模板降级、1 截断。正常完成率 7/14=50%，不是 Faithfulness。所有题目原分母保留。12/12 引用标签可映射到当时片段，只是可解析性，不是引用语义准确率。原生工具调用=0、B support_check=0，本轮实际走表达路径，不能冒充 KnowledgeTools 工具/检查覆盖。

独立确定性复核复用 `solving.parse_problem/solve_problem/verify`，具体方程、候选与 verifier 结果见 `deterministic-math-review.json`。泛化文字的条件遗漏另列，不能让若干算式 VERIFIED 代表整篇回答正确。参考反例 a=b=0,c=1 得 1=0，不是一次方程。

`B-review-packet.json` 包含每题实际可见证据、最终回答、引用位置、调用关联和五维复核记录。完整原始请求/返回位于 request-001..024.json。当前是独立 AI 初审，未做人类校准；逐声明支持标注尚未完成，因此回答级 Faithfulness 宏平均、最低分、关键内容覆盖数值均为 null。6 个空洞模板没有被赋 1 分。

### 预算、限制与下一验收边界

24 次实际请求，0 自动重试，1 次产品自带续写；保守预算记账 169364 / 300000。18 个返回有 usage：9883 input + 4773 output = 14656；6 个失败的 usage 未由 Gateway 暴露，合计实际 token 不能精确报告，亦不能将这些失败按 0 计费。A 请求输出上限 1800，B 保留产品 512 上限，未在看过结果后调整。

候选阈值在调用前计划中保存，但正式阈值尚未获冻结确认。开发回归已存在明确任务失败，故质量 FAIL；这不等于正式样本质量估计。人工标签、独立 holdout、三次固定重复，以及仅提示/冲突/无答案/连续追问等模式仍不足，正式验收为 INSUFFICIENT_EVIDENCE。此轮不调提示词或重跑取最好结果。

## 当前报告口径修复（2026-09-19）

本节优先于后文历史增量说明。schema 保持 `mathtutor.rag-evaluation/2`，语料 `hard-corpus/2`、标注 `hard-annotations/3` 不变。
实跑 `artifacts/lifecycle-repair/evaluation-040-final-2.log`，机器结果仍为 `artifacts/rag-evaluation.json`。

零结果不再触发 BENCHMARK_INVALID。评分前独立验证 owner、绑定 scope、可见性、摄入状态及标注 chunk 的存在；合法已知答案未检出计 retrieval miss，空 scope / no-answer 仍保留在原分母中。四项守卫回归覆盖空排名、空 scope、错误 owner、缺失引用。

引用逐例算术（correct 仅指所引用来源键属于 required 来源集合，不是语义或逐字正确性）：

| case | cohort | correct / total | precision | 宏平均资格 |
|---|---|---:|---:|---|
| CC1_verbatim | valid_attribution | 1 / 1 | 1 | 是 |
| CC2_over_cited | incorrect_attribution | 1 / 2 | 0.5 | 是 |
| INJ1_tampered_quote | incorrect_attribution | 1 / 1 | 1 | 是 |
| INJ2_fabricated_source | malformed_or_unauthorized | 1 / 1 | 1 | 否 |
| INJ3_quote_kind_mismatch | incorrect_attribution | 1 / 1 | 1 | 是 |

因此 attribution 宏 precision = `(1 + 0.5 + 1 + 1) / 4 = 0.875`；4 case、5 link，微 precision 为 4/5=0.8。全部队列为 5 case、6 link。篡改 quote 或 quote-kind 的来源键可以匹配，但操作仍被拒绝；不得把这一宏指标描述为“87.5% 引文内容正确”。标签和原分值均未为了配平汇总而更改。每例现已导出 correct_link_count、total_link_count、citation_precision、cohort、aggregation_eligible。

0.4.0 工程回归：20 轮定向各 52 passed，3 次全量各 1336 passed / 11 skipped；Web 164 passed、Desktop 44 passed / 2 skipped。此类工程证据不进入语义评测分母。

0.4.0 包外验证：runtime/lifecycle 探针 exit=0，桌面 smoke 17/17；模块 provenance 与 SHA256 见 `artifacts/lifecycle-repair/release-040-final-manifest.json`。pypdf/FTS5 可用；PyMuPDF、OCR 与 neural embedding 的缺席仍按 OPTIONAL/DEFERRED 记录，不解释为这些能力已经实现。

本集 no-expansion **无 recall 增益**。语义评测保持 **BLOCKED_PROVIDER**，real_decisions=0、rates=null；协议桩不进入语义分母。

- 日期：2026-09-19
- 运行命令：`.venv/Scripts/python.exe -m pytest tests/test_rag_production_benchmark.py`
- 唯一官方 benchmark：`tests/test_rag_production_benchmark.py`

> 本文所有数字**来自实际运行**。无一项手写预期值。
> 未实现的部分明确标 NOT IMPLEMENTED，不以"待补"含糊带过。

---

## 0. 一次运行产出全部结果

```bash
.venv/Scripts/python.exe scripts/rag_hard_set_probe.py --evaluate
```

`[事实]` 该 runner **不是第二套评分器**：easy set 的语料、查询、排序与全部四个指标族
（Recall / MRR / nDCG / HitRate）都**直接从 `tests/test_rag_production_benchmark.py` 导入**
（`CORPUS` / `QUERIES` / `recall_at_k` / `mrr_at_k` / `ndcg_at_k` / `hit_rate_at_k` / `_rank`），
hard set 也复用同一批指标函数。**改一处定义，两边同时动。**

`[事实]` 为复用排序路径，官方基准的 `_rank` 增加了一个可选 `owner` 参数（默认 `OWNER`，行为不变）。
原因是：查错 owner 时检索可能静默返回空。此前以“全空排序”判定无效会把真实 retrieval miss 排除，现已移除该规则。`official_retrieval_metrics` 在评分前独立验证 owner、scope、可见性、摄入状态与 reference；只有前提无效才 `BENCHMARK_INVALID`，合法零结果照常评分并保留分母。

### 0.1 结果总览（实测）

| 集合 | 样本 | R@5 | MRR@5 | nDCG@5 | Hit@1 |
|---|---|---|---|---|---|
| easy（官方语料 + 9 条 seed query） | 9 | 1.000 | 1.000 | 1.000 | 1.000 |
| hard（17 chunk，5 条 query） | 5 | 1.000 | 0.900 | 0.949 | 0.800 |
| expansion-required 子集 | 4 | — | — | — | — |

`[事实]` **easy set 仍然全 1.0**（§2.1 的老问题）；**hard set 首次给出有区分度的检索数字**
（Hit@1=0.800、MRR@5=0.900），因为它的语料比 `evidence_limit` 大，且文档互相干扰。

### 0.2 每次运行都会记录的冻结信息

`run_provenance`：git HEAD / 分支 / 工作区是否 dirty / 生产源码树 digest / 本 runner digest /
官方基准 digest / chunker 版本 / 语料版本 / 标注版本 / 评分器版本。

`budgets`：`candidate_limit=20`、`evidence_limit=8`、`max_evidence_items=8`、
`max_evidence_chars=12000`、`max_per_item_chars=2000`、`max_expanded_items=4`、
`max_expansion_chars=2400`、`neighbour_radius=1`、`max/min/overlap_chunk_chars=1000/80/100`。

`[事实]` **工作区是 dirty 的**，所以 git sha 指向的代码**不是**实际跑出这些数字的代码 ——
这正是要同时记录**源码树 digest** 的原因。

`[事实]` 每条 query 都带 `metrics.counts`：分子、分母、计数单位与 RR 的原始计数。
任何比率都可以不重跑而直接复算。

---

## 1. Dataset

### 1.1 语料

真实 SQLite 库：6 份中文数学文档经 `DocumentIngestionService` 摄入 → 真实 parse → 真实 chunk → 真实 FTS。

| key | 文档 | 覆盖轴 |
|---|---|---|
| `linear` | 一次方程.md | 定义 / 移项 / 等式性质 |
| `quadratic` | 二次方程.md | 一般形式 / 求根公式 / 判别式（公式密集 + 中英混排） |
| `commutative` | 交换律.md | **近义干扰**：与结合律共享「加法」 |
| `associative` | 结合律.md | **近义干扰** |
| `fraction` | 分式笔记.md | 跨主题：去分母 / 增根 |
| `distractor` | 数学史话.md | 主题干扰（数学史 vs 解题方法） |

每份文档**两个 `##` 章节**，因此每份产出 2 个 chunk —— 单 chunk 文档无法考察多命中排序或上下文扩展。

### 1.2 Query 集（9 条）

| key | query | 覆盖轴 |
|---|---|---|
| `canonical_term` | 一元一次方程的定义是什么 | 规范术语 |
| `spoken_variant` | 等式两边同时减同一个数可以吗 | **口语改写 → 规范说法** |
| `transposition` | 移项要变号吗 | 术语 |
| `formula` | 求根公式 x = (-b ± √(b²-4ac)) / (2a) | **公式逐字** |
| `discriminant` | 判别式决定根的个数 | 公式相关 |
| `commutative` | 交换加数的位置和不变 | 近义词面 |
| `associative` | 加法结合律的字母表示 | **近义干扰** |
| `cross_topic` | 去分母后为什么要检验 | 跨主题 |
| `mixed_cjk_latex` | ax^2 + bx + c = 0 中 a 不能为零 | **中文 + LaTeX 混排** |

### 1.3 Ground truth

以 `(document_id, sequence)` 表达——即检索**实际返回的身份**，不是某个平行夹具类型的 id。

`[事实]` 夹具内自校验（`test_ground_truth_matches_the_real_chunking`）：每个 ground-truth 引用必须**存在**且**确实包含**声称的文本。这条测试是在一次真实夹具错误之后加的——手写的 sequence 指向了一个 chunker 从未产出的序号，指标因此把一次完全正确的检索报成了 miss。

---

## 2. Retrieval metrics

真实链路：`DocumentIngestionService → DocumentIndexManager.search → ProductionReranker → ContextExpander → EvidencePack`。

`[事实]` 实测结果（lexical-only，发布形态）：

| query | R@1 | R@3 | R@5 | MRR@3 | MRR@5 | nDCG@3 | nDCG@5 | Hit@1 | Hit@5 |
|---|---|---|---|---|---|---|---|---|---|
| canonical_term | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| spoken_variant | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| transposition | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| formula | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| discriminant | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| commutative | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| associative | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| cross_topic | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| mixed_cjk_latex | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 |
| **aggregate** | **1.0** | **1.0** | **1.0** | **1.0** | **1.0** | **1.0** | **1.0** | **1.0** | **1.0** |

### 2.1 ⚠ 这份语料没有区分度 —— 必须明说

`[事实]` **全部指标为 1.0。** 这不是好消息，是**基准设计不足**的证据：

- 一个在所有 query 上都满分的基准，**无法在回归早期发出信号**，只会在严重破坏时才掉分；
- 中文数学术语密集、文档间词汇高度可分，词法 + FTS + 中文 bigram 在这个规模上本就近乎完美；
- 因此**当前数字不能用来论证检索质量**，只能用来钉住"没有严重回归"。

`[事实]` 测试中的门槛因此设为**地板而非冻结值**（`recall@5 ≥ 0.95`、`mrr@5 ≥ 0.75` 等），且数值以 `record_property` 记录供本文引用 —— 冻结成常量会让任何无关的检索改动都失败，并让语料无法演进。

`[建议]` 要真正具备区分度，语料至少需要：**更多相似文档（≥3 份同主题）**、**更长文档（强制多 chunk 竞争）**、**同义改写密度更高的 query**。当前 6 文档 / 9 query 的规模不足以做到。

---

## 3. Context metrics

`[事实]` **PARTIAL —— hard set 已测量；easy set（§1.1 的 6 文档语料）仍未测量。**

### 3.0 为什么 §1.1 的语料测不了 Context

`[事实]` §1.1 语料中**上下文扩展一次都没有触发**（实测 `expansion_used = false`，9/9 条 query）：
每份文档两个短章节，每个 chunk 都以终止标点收尾且没有 child，`needs_expansion` 恒为 false。
没有触发就没有"被扩展补回的那一块"，precision/recall 的分子分母无从定义。

`[事实]` 因此专门构造了 **hard set**（`scripts/rag_hard_set_probe.py`），它按需求书 §E1 的
C1/C3/C5 形态**实际迫使**扩展触发。补充一条被前一轮误判的事实：**跨文档不可能互为邻居**
（`ContextExpander` 通过 `list_chunk_neighbourhood(chunk.document_id, ...)` 读取），
所以 C5 必须在**同一文件**内用两个 `##` section 构造。

### 3.1 Ground truth 与自检

标注**先于检索**写定，锚点同时绑定 `(document_id, sequence)` 与**逐字命中文本**：

```
required  答案不正确就不可能缺的 chunk（定义、题解所指的题干、跨边界的那一半）
relevant  实质上支持答案的 chunk（required ⊆ relevant，由自检强制）
forbidden 扩展**绝不允许**拉进来的 chunk（跨 section 的序列相邻块）
```

`[事实]` **50 条 fail-fast 自检在任何指标计算之前运行**，失败即 `BENCHMARK_INVALID` 且**不出数字**：
anchor 存在性与逐字命中、`required ⊆ relevant`、`forbidden ∩ relevant = ∅`、C1 同 section 且真邻接、
C3 `child.parent_chunk_id == stem.chunk_id` 且 parent 序列在前、C5 forbidden 确与 relevant 序列相邻但
`heading_path` 不同、isolation fixture 真实（跨 owner **逐块同文**且 chunk_id 互斥）。

### 3.2 实测（hard set，语料 17 chunk，5 条 query）

```
Q01 C1  CP=0.222 CR=1.000  intended C1, observed C1  disc#1 ← 补回 disc#0
Q02 C3  CP=0.250 CR=1.000  example#1 ← 补回 example#0（child→parent）
Q03 C5  CP=0.500 CR=1.000  guard exercised=True holds=True leaks=none
Q04 C4  CP=0.500 CR=1.000  distractor neighbour#2 被扩展拉入（预期），CP 受罚
Q05 C2  CP=0.250 CR=1.000  intended C2, observed C2  disc#0 ← 补回 disc#1
macro   CP=0.344 CR=1.000 NR=0.656 RR=0.913
expansion-required 子集（Q01/Q02/Q04/Q05）  CP=0.306 CR=1.000
intent/observation 不一致：0         isolation ok=True
```

`[事实]` **语料由 8 chunk 扩到 17 chunk**（`evidence_limit=8`），这是 CP 从"装得下整个语料"
变成可判别数值的前提。CP 现在落在 0.222–0.500 区间。

`[事实]` 五条机制结论（均为实测，非预期）：

| 机制 | 结果 |
|---|---|
| C1 previous+current | **触发**（Q01，实测 matched 后块、补回前块） |
| C2 current+next | **触发**（Q05，实测 matched 前块、补回后块） |
| C3 child→parent | **触发**，题干由 parent 补回 |
| C4 同 section 干扰邻居 | **危险成立**：`neighbour#2` 被扩展拉入，CP 降到 0.500 |
| C5 跨 section 拒绝 | **被真正行使且成立**——窗口里确实有 forbidden 块，未被拉入 |

`[事实]` **C1/C2 是「意图 vs 观测」而非断言**：两者共用同一份 fixture 真相（同 section 相邻两块），
差别只在 kernel 命中了哪一侧，这是**结果**不是夹具能保证的事。脚本因此计算
`observed_relation` 并单列 `relation_mismatches`——**实测为 0**，即 Q01 确实命中后块、Q05 确实命中前块。
一个"意图 C2、实际命中后块"的 query 会被报成 C1，而不是被悄悄改标签。

`[事实]` **C4 的 distractor 与 C5 的 forbidden 是两种相反的东西，因此分开标注**：

| 标签 | 含义 | 被扩展拉入时 |
|---|---|---|
| `forbidden`（C5） | 跨 section 邻居，**必须拒绝** | 记为 expansion leak（缺陷） |
| `distractor`（C4） | 同 section 邻居，**预期被拉入**且不相关 | 计入 CP（**非**缺陷，是 C4 要暴露的危险） |

`[事实]` 初版把两者混为 `forbidden`，会把一个**正常工作**的 C4 报成 expansion leak。
脚本对 C4 甚至把 distractor 移进独立 `##` section 做过反向注入：`C4_distractor_same_section` 当场失败。

`[事实]` C5 的 `guard_exercised` 是刻意区别于"没泄漏"的：既然 `boundary#1` 触发了扩展，
而该调用读取 `[seq-1, seq+1]`，`boundary#2` **必然**在它的窗口内。**没有泄漏 ≠ 通过检查**，
可能是根本没查。

`[事实]` 选中上下文定义为 `{evidence.chunk_id} ∪ evidence.expanded_from`——
扩展改变的是模型实际读到的内容，必须计入 precision/recall，不能藏在原始 hit 后面。

### 3.3 ⚠ 三条必须与这些数字同读的限制

1. `[事实]` **CP 已可判别但仍偏低**：语料 17 chunk > `evidence_limit=8`，CP 不再被 pack 大小
   锁死（实测 0.222–0.500）。但它在**小语料 + 8 条 evidence 预算**下仍同时反映两件事：
   排序质量 **和** 扩展把同 section 邻居一并拉入（C4）。两者目前无法从 CP 一个数里拆开。
2. `[事实]` **CR=1.000 在本语料上仍近乎必然**：pack 装得下 8 条，而多数 query 的 relevant 集合
   小于 8。CR 目前只能当"没有整个丢失"的地板读，不能当召回质量读。
3. `[事实]` **RR=0.913 主要来自 fixture 自身，不是产品缺陷**。用具体计数说话：

```
selected RR (macro)   = 0.9133     选中上下文 4-gram 重复率
corpus RR (未检索前)   = 0.8307     3440 / 4141 个 4-gram 已是重复
```

`[事实]` **语料在检索介入之前就已经 RR=0.831** —— 因为要逼出跨块边界，
fixture 必须把同一段话重复十几次（`opening * 12`、`body * 18`）。
所以 0.913 里约 0.83 是**夹具的自相似性**，检索/扩展/100 字 overlap 只贡献大约 0.08。
把 RR=0.913 当作"产品冗余"引用是错的；它首先是"这份夹具很重复"。

`[事实]` **RR 不是不相关度，两者不可互相解释**：
RR 统计的是**文本重复**，一个高度重复的选中集合可以完全切题；
NR（=1−CP）才是无关占比。**RR 高 ≠ CP 低，CP 低 ≠ RR 高**，代码与产物里都写明了这条。

`[事实]` **所有指标按 chunk 计权，不是按 token / 字符计权**：
一个 988 字符的块与一个 18 字符的块各算一项。任何数字都不得改读为逐 token 或逐字符比率
（已写入 `artefact.budgets.counting_unit`）。
4. `[事实]` `boundary#2` 被 kernel **直接检索命中**（对 Q03 属噪声）→ 已计入 CP。
   它是 **retrieval noise，不是 expansion leak**；两者分开计分，既避免用噪声掩盖扩展 bug，
   也避免用扩展 bug 冤枉一个正常工作的 guard。
5. `[事实]` **同 section + 相邻是 C4 的构造条件，不是它的判据**。C4 的三条性质被分开验证：
   邻接（结构）、**共享查询词汇**（`C4_distractor_shares_vocabulary`，用 `lexical_score` 实测）、
   **不含答案**（`C4_distractor_lacks_the_answer`）。只验"不相关"而不验"词汇相似"，
   会让一段毫不相干的填充文本冒充 distractor，CP 就会好看得毫无道理。
   注入验证：把答案句塞进 distractor → 该检查当场失败。

`[事实]` 五条都是**基准与产品的真实性质**，不是待办事项。`artifacts/rag-evaluation.json` 中
`context.discrimination_caveat` 逐字记录了第 1 条。

### 3.4 语料构成（hard set）

| key | 文档 | chunk | 承载 |
|---|---|---|---|
| `neighbour` | 乘法公式 | 3 | **C4**：同 section 干扰邻居（`定义：` 另起 group，共享 `heading_path`） |
| `disc` | 判别式 | 2 | **C1 / C2** |
| `example` | 例题.md | 2 | **C3** child→parent |
| `boundary` | 完全平方公式 + 分母有理化 | 3 | **C5** 跨 section 拒绝 |
| `weida` | 韦达定理 | 1 | 语料级词汇干扰 |
| `linear` / `fraction` / `inequality` | 一次方程 / 分式方程 / 不等式 | 2 each | 语料填充，使 pack 装不下全集 |

`[事实]` **填充文档是刻意的普通课程内容**，不是无关噪声：用永远匹配不上的文本填充语料，
会让 precision 因为错误的原因好看。它们与查询词汇的真实重叠（如 `linear#1` 与"移项"）正是干扰源。

`[事实]` **C4 的 distractor 必须自成 chunk**。先试过按长度调参让相关内容恰好占满两块——
失败了：`_split_group_text` 贪心装填，会继续吸收后面的句子，同 section 的边界无法用字符数定位。
最终改用结构手段：以「定义：」开头的行会另起一个 chunk group，**但继承同一个 `heading_path`**，
于是 `_same_section` 为真、扩展必然拉入，且因另起 group 而没有 100 字 overlap 污染。
这同时说明 `_split_group_text` 的 overlap 会与前一块共享 100 字——**若靠长度调参，
distractor chunk 的前 100 字就是答案本身**，标注会当场变成谎言。

---

## 4. Citation metrics

`[事实]` **PARTIAL** —— 行为有测试覆盖，但没有聚合指标。

### 4.1 已有测试覆盖

| 需求项 | 覆盖 | 位置 |
|---|---|---|
| seeded evidence 可引用 | ✅ | `test_agentic_retrieval.py::test_seeded_evidence_becomes_readable` |
| exact read 逐字匹配 | ✅ | `test_knowledge_workbench.py` |
| body_hash 重读校验 | ✅ | `test_knowledge_safety.py` |
| **guessed interval → REJECTED** | ✅ | `test_agentic_retrieval.py::test_seeding_does_not_widen_the_hit_restriction` |
| **guessed document_id → REJECTED** | ✅ | 同上 |
| disabled source after retrieval | ✅ | `test_rag_production_benchmark.py::test_disabled_document_drops_out_of_retrieval` |
| generation invalidation | ✅ | `test_knowledge_workbench.py` |
| 篡改文本不注册区间 | ✅ | `test_agentic_retrieval.py::test_seeding_registers_nothing_when_the_text_does_not_address` |

`[事实]` 其中「篡改文本不注册」这条是**测试逼出来的修复**：初版只校验了"派生区间与正文一致"，未校验"证据文本与该 chunk 一致"，导致篡改文本配真实 `chunk_id` 仍能注册 —— 模型会看到 X 而 `read_source` 返回 Y。

### 4.2 聚合指标（hard set claim fixture 实测）

`[事实]` 已补上 fixture 驱动的整链：真实 `ProductState` + `KnowledgeService` + `KnowledgeTools`
over 真实 SQLite，笔记正文与检索语料**同一批 fixture 文本**。

`[事实]` 关键约束：`read_source` **拒绝未被 `search_knowledge` 命中过的区间**
（"不能猜测资料 ID 或范围"）。因此 fixture 必须**先检索再读取**，读取区间是 kernel 选中的 chunk，
**不是**为了迁就 quote 而手工挑的偏移。引用文本不在该区间内时脚本直接 `BENCHMARK_INVALID`。

`[事实]` claim case 分成**三个队列**，各自报数，不合并：

| 队列 | 含义 | claim case | citation link |
|---|---|---|---|
| `valid_attribution` | 引用正确且充分 | 1 | 1 |
| `incorrect_attribution` | **故意错误归属**（多引一个源、改一个符号、声明 quote 实为转述） | 3 | 4 |
| `malformed_or_unauthorized` | 伪造 `source_id` 等**非法操作**探针 | 1 | 1 |

```
attribution (valid + incorrect)  P = 0.875   R = 1.000   cases = 4   links = 5
operational (malformed)          rejection = 1.000       cases = 1   links = 1
```

`[事实]` **claim case 数与 citation link 数是两个不同的计数单位**：
1 条 claim 可以挂 4 条 link，那是 1 次归属判断、4 次引用判断。只报其中一个都会误导，
所以两个都报（`totals.claim_cases` / `totals.citation_links`）。

`[事实]` **这里的 "precision" 指"对照参考证据的归属准确性"，不是操作合法性，
也不是生产语义检查准确率。** 两者分开测：CC2 可以**操作合法**（区间读到、引文逐字、body_hash 一致，
验证器接受）却**归属错误**（引了不需要的源）—— 这正是需要两个队列的原因。

`[事实]` **注入探针不计入 attribution precision**：每个注入用例都恰好引用了它需要的东西，
平均进去会把一条真实误引的影响稀释向 1.0。

### 4.3 篡改注入（评价器必须报警）

`[事实]` 五类确定错误全部被真实验证器拒绝，`mutations.verdict = OK`：

| 注入 | 结果 |
|---|---|
| `INJ1` quote 改一个符号 | REJECTED（摘录与区间不符） |
| `INJ2` 伪造未 surface 的 source_id | REJECTED |
| `INJ3` 声明为 quote 但正文是转述 | REJECTED（quote 必须逐字对应） |
| 无 entailment 后端时的 summary | REJECTED（fail closed） |
| entailment 检查返回 false 的 summary | REJECTED |

`[事实]` 最后两条落在同一处守卫（`support_checker is None or not await ...`），
但**原因不同**：一个是"没有检查器"，一个是"检查器说不支持"。两者都必须拒绝——
这正是需求书 §17「不得把相似度当蕴含」的落点。

### 4.4 历史引用凭证（receipt lifecycle）

```
Historical Receipt Validation Rate          1.000   (1/1 合法读取成功)
Unauthorized Historical Read Rejection Rate 1.000   (4/4 未授权读取被拒)
```

`[事实]` 两个比率**分开报**且分母分开，因为「合法读取仍然可用」与「非法读取被拒绝」
是两个不同性质：用一个混合比率，**全部拒绝**会得到与**精确拒绝**相同的分数。

四个被拒探针：区间加宽、起点偏移、跨会话、**资料删除后**（删除是物理删除，
隐私删除优先于历史引用可用性 —— F3 决策）。

---

## 5. Faithfulness metrics

`[事实]` **NOT MEASURED —— 如实记录，不生成虚假 faithfulness。**

```
Deterministic supported-claim rate    NOT MEASURED
LLM judge                             NOT USED（且不得作为权威判据）
```

`[事实]` 原因是**依赖真实缺失**，不是没做：

- `tutor_runtime.support_check` 需要**模型 provider**，而发布运行时**不带**模型；
- 内容支持是**蕴含**问题。脚本里确实放了一个返回 gold 标签的 stub，
  但它**只证明协议通，不证明语义质量**——把它算成 faithfulness 就是伪造。
  该 stub 在产物中被显式标注为 `protocol stub, NOT a judgement about meaning`。

`[事实]` 因此采用**分类计数**而不是编一个比率：

| 类别 | 状态 |
|---|---|
| `LEGAL_CITATION`（合法引用） | **已测**——结构检查（已 surface / 摘录逐字 / body_hash 一致） |
| `CONTENT_SUPPORT`（内容支持） | **UNKNOWN**——需蕴含模型 |
| `WRONGFUL_ADMISSION`（错误放行） | **已测**——注入的确定错误被接受的数量（实测 0） |
| `PARTIAL_SUPPORT`（部分支持） | **UNKNOWN**——需蕴含模型 |
| `UNKNOWN` | 只报**计数**，绝不折进任何比率 |

`[事实]` 现有 `support_check` 是**运行时闸门**，不是**评测指标** —— 两者不能相互替代。
本轮的替代品是"合法引用"这一**确定性**部分，它可测且已测；"内容支持"没有被冒充。

### 5.1 真实语义评测入口（当前 BLOCKED_PROVIDER）

`[事实]` 脚本带有真实语义评测模式，但当前状态是 **`BLOCKED_PROVIDER`**：

```
status        BLOCKED_PROVIDER
blocker       未显式授权任何 provider
real_decisions 0
semantic_rates null        ← 是 null，不是 0.0
```

`[判定]` **零真实决策 = 证据缺失，不是"测得 0"。** 报 0.0 会被读成"测了且失败"，
所以比率一律为 `null`，只报原始事件计数（此处为 0）。

`[事实]` 该模式的设计约束（均已落到代码里）：

- 只在操作者显式设置 `MATHTUTOR_EVAL_PROVIDER` 时才启用；
- **不去嗅探环境变量里的密钥、不打印任何密钥、不自动选择付费 provider、不下载模型、
  不改安装器依赖**；
- 用**真实的生产 `support_check`** 跑固定 claim + 真实 surface 证据；
- **provider 不会收到 gold 标签或期望解释**；
- 返回 gold 的 stub **只允许存在于隔离的协议测试**中，其运行**必须排除在语义指标之外**
  （本脚本中的 stub 已显式标注 `protocol stub, NOT a judgement about meaning`）。

`[事实]` 需要记录的字段已定义为：provider/model、support-check prompt 版本、实际决策、
单独保存的参考标签、UNKNOWN/timeout/error 计数、决策覆盖率、
supported-case 接受率、unsupported-case 误接受率、partial-support 结果。
**在 provider 到位之前这些字段不会有真实值**，因此不报。

`[判定]` **不得把"混合 fixture 上的接受比例"当作生成答案的忠实度报告。**
混合队列本来就让一部分用例**应该被拒**，对它们算接受率没有意义。

### 5.2 答案质量评测（当前 NOT_MEASURED）

`[事实]` 未运行任何已授权的 generator，因此**没有生成答案可评**。

`[事实]` 产物中提供 **provider-free 导出**（`answer_quality.status = EXPORTED_FOR_REVIEW`）：
它保存每条 query 的**实际可见上下文**与**引用候选**（含 `source_id` / `text_hash`），
供后续人工复核。`answers_generated = 0`、`reviewed = false`、`labels_from = null`。

`[判定]` **未复核的导出不构成答案质量评测。** 有 generator 之后，其保存的输出**独立评测**，
并标注标签来自**人工复核**还是**已具名的模型评审**；模型评审的分数一律标为 judge-estimated。

---

## 5.1 组件消融（与注入故障**分开**报告）

`[事实]` 三个臂**共用同一份语料、同一批 query、同一个 kernel、同一个 scope、
同一个 `candidate_limit` 与 `evidence_limit`**；唯一变化的是被消融的组件。

```
arm             CP        CR        说明
production      0.3444    1.0000    ProductionReranker + ContextExpander
no_reranker     0.3389    1.0000    IdentityReranker（保留 kernel 原序，不重排/不过滤）
no_expansion    0.3500    1.0000    expander=None

deltas vs production
no_reranker     dCP = -0.0055    dCR = 0.0000    → DECLINE_ON_THIS_SET（仅 Q05 差 1 项）
no_expansion    dCP = +0.0056    dCR = 0.0000    → GAIN_ON_THIS_SET
```

`[事实]` **no-reranker 基本没有影响**：CR 完全不变，CP 只差 0.0055，且 5 条 query 里只有 Q05 不同。
这不是"下降"，是**这一批数据分辨不出 reranker 的作用**。没有为了造出下降而重新筛数据。

`[事实]` **no-expansion 的 CR 没有任何损失，CP 反而略升**，且 `no_expansion_lost_required` 为空。
按需求必须先确认"必需事实是否本来就在别处可见"，再解释这个结果 —— 检查结果是**没有任何必需块丢失**，
因为 C1/C2/C3 的必需块**本来就被 kernel 直接命中**（只是同时也被扩展补了一次）。
所以在这个语料上：

```
扩展对 recall 的贡献        = 0（必需事实无需扩展即可得）
扩展对 precision 的影响      = 轻微为负（同 section 邻居被一并拉入，C4 即其形态）
```

`[判定]` 这不是"扩展没用"的结论，而是**这批数据测不出扩展的收益**：
`evidence_limit=8` 相对 17 块的语料仍偏大，必需块往往本来就在 pack 里。
要真正测出扩展的收益，需要一个**必需块经常落在直接命中之外**的语料。

`[事实]` 消融与注入故障在产物里是**三个独立小节**（`ablations` / `citation_mutations` /
`fixture_mutations`），各有各自的 verdict，不合并成一个说不清的 OK。

---

## 6. Latency

`[事实]` telemetry 已采集 `retrieval` / `rerank` / `context_build` 三个延迟直方图（`MathTutorMetrics`），并在 `rag_health()` 中输出均值。

`[事实]` **本文不报具体延迟数字**：benchmark 在 CI 环境运行，机器间方差远大于被测差异；报一个未标注环境的数字没有意义。

`[建议]` 需要引用延迟时，从 `/health` 或 `ProductState.metrics.rag_health()` 在**目标运行环境**读取，而不是从本文抄。

---

## 7. Degraded-mode result

`[事实]` 全部 9 条 query 在**无 embedding 后端**下运行（= 发布形态）：

```
mode                    = lexical     (9/9)
rag_hybrid_total        = 0
rag_vector_unavailable  = 9
retrieval_request_rate  = 1.0
```

`[事实]` 结论：**词法路径独立可用，不依赖任何向量能力**。这是 §2 全部指标成立的前提，也是产品在发布形态下的真实能力边界。

---

## 8. Security cases

`[事实]` 全部通过（`test_rag_production_benchmark.py`）：

| 场景 | 断言 |
|---|---|
| 未绑定会话的文档 | 9/9 query 中**零出现** |
| 跨 owner 文档（与本地未绑定文档**逐字节相同**） | 9/9 query 中**零出现** |
| 用户禁用文档 | 禁用后消失，重新启用后返回 |
| 软删文档 | 消失 |
| 空 scope | `retrieval_ran = false`，且**不触达 kernel** |
| 只有一个文档在 scope | 结果**全部**属于该文档 |
| 扩展不越界 | `expanded_from` 的 chunk 均在被授权文档内 |

---

## 9. Limitations（必须与数字一起读）

1. **语料规模小且无区分度** —— 全部指标 1.0，无法在回归早期报警（§2.1）。
2. ~~**上下文扩展从未触发**~~ —— **hard set 已触发并测量（§3）**；easy set 语料上仍是 9/9
   `expansion_used = false`，即 easy set 的扩展路径仍未被覆盖。
3. **Faithfulness 未测**（无蕴含模型，如实记录，不伪造）；**Citation 已测但样本极小**
   —— 只有 2 条真实 claim + 3 条注入探针，precision 0.750 的分母是 2；
   **Context 指标为 PARTIAL**：hard set 已测，easy set 未测（§3–§5）。
4. **hard set 的 CP 偏低且不可拆解**（0.222–0.500）：它同时反映排序质量与扩展拉入的同
   section 邻居（C4），目前无法从一个数里分开；CR=1.000 仍近乎必然（§3.3）。
5. **hard set 只有 5 条 query**（覆盖 C1–C5 各一条）——机制各有一次实测触发，**没有重复样本**，
   因此不能报方差，也不能据此断言"机制稳定"。C4/C5 各只有一个受限场景。
6. **无多跳（multi-hop）评测** —— `RetrievalHop` 语义（`hop_index` / `kind` / `second_retrieval_used`）
   已实现且有测试，但**没有任何指标度量二次检索的深度或收益**；二次检索率仅经 telemetry 采集。
7. **单一 embedding 形态** —— 所有结果来自 lexical-only；`hybrid` 分支在发布运行时**不可达**，因此未经评测。
8. **PDF 未进入本 benchmark** —— 语料为 markdown；PDF 的 `pypdf` baseline 由 `test_pdf_classification.py` 单独覆盖，未与检索指标联合评测。

---

## 10. 复现

```bash
# 唯一官方 RAG benchmark（easy set：检索指标 + 安全场景）
.venv/Scripts/python.exe -m pytest tests/test_rag_production_benchmark.py -q

# hard set：C1–C5 语料 + Context 指标 + claim/citation fixture + 篡改注入
# （写出 artifacts/rag-evaluation.json）
# 自检不通过时 exit 2 且不产出任何数字
.venv/Scripts/python.exe scripts/rag_hard_set_probe.py --evaluate
.venv/Scripts/python.exe scripts/rag_hard_set_probe.py       # 仅 chunk manifest

# PDF baseline 与分类
.venv/Scripts/python.exe -m pytest tests/test_pdf_classification.py -q

# 引用与 seeding 契约
.venv/Scripts/python.exe -m pytest tests/test_agentic_retrieval.py -q

# 运行时能力探测（dev venv 与发布运行时各跑一次）
.venv/Scripts/python.exe scripts/rag_runtime_probe.py --json
desktop/dist/win-unpacked/resources/python-runtime/python.exe scripts/rag_runtime_probe.py --json
```
