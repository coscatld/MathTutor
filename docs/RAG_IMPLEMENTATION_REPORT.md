# RAG IMPLEMENTATION REPORT

## 0.4.2 主线集成候选（2026-09-20）

在独立 worktree 集成，原工作区与历史证据保持不变。最小续写修复识别闭合数字根列表及括号小数接缝，保留不确定接缝、错误生成段和真实截断保护；COMPLETED只表示交付，不生成数学VERIFIED。定向首轮56项通过，包括最终WebSocket正文与持久化；最终集成回归、PR/合并和发行包结果另在本次发布执行记录中记录，不能借用下面历史数字。

测试保留原产品行为和质量边界断言，并将依赖本地原始请求记录的回放改为脱敏响应夹具与合成输入；原请求逐字比较改为合成提示及续写上下文检查，历史原始日志不提交。CI发现干净环境缺少测试用numpy，以及Windows/Unix换行导致夹具字节哈希不一致；补dev依赖并固定夹具LF，不关闭测试、不放宽哈希验证。预算未变，无新增付费调用。新增发行说明见 [RELEASE_0.4.2.md](RELEASE_0.4.2.md)。原质量FAIL、BUDGET_BLOCKED、PROVISIONAL_AI及人工PENDING继续有效。

## 2026-09-20 最新增量：0.4.2，仅离线

新增真实调用0，原75请求/293690 token账本逐字节不变；历史语料、结果与原B评分保持只读。新14篇和退化3篇独立绑定原回答哈希、请求编号及0.4.1生成版本，另作0.4.2 AI初审，未复用旧Faithfulness或声称人工通过。

已离线修复续写无分隔与不确定断点被宣称完成的问题；错误原句仍完整保留。修正版正常资料独立版本/哈希，原错误片段单列来源含错组。复用受限solver/verifier补参数、零乘非等价和分母条件回归，超范围UNKNOWN。新增数学条件提示词尚未真实模型复测；没有重新打包。

本轮定向57 passed，最终工程证据见`artifacts/offline-math-042/validation.json`；具体“错误→位置→证据”、资料区别、人工审阅包及后续项目见 [OFFLINE_MATH_REPAIR_042.md](OFFLINE_MATH_REPAIR_042.md)。**离线修复通过不等于真实模型质量通过。** 下方0.4.1条目与数字作为历史结果保留，不作0.4.2验收证据。

## 0.4.1 历史报告

- 更新日期：2026-09-20（历史工程证据日期保留）
- 事实基线：`docs/CURRENT_STATE_RAG_AUDIT.md`
- 架构：`docs/RAG_ARCHITECTURE.md` · 评测：`docs/RAG_EVALUATION.md`
- 当前版本：**0.4.1**。本轮后端全量 **1356 passed / 11 skipped**；定向 **86 passed**（包含全量启动后新增的 7 个评测守卫）；Web **164 passed**；Desktop **44 passed / 2 skipped**。此前 0.4.0 的 schedule-3 与安装包证据仍属历史，不迁移为新版本回归。

> 状态：**PARTIAL — §42 未全部 PASS。** 未完成项标 FAILED 并给原因，不用 PARTIAL 掩盖。

---

## 2026-09-20 后续结果：交付修复与独立语义复核

详见 `RAG_EVALUATION.md` 最上方及 `artifacts/delivery-regression-20260920/final-review.json`。原始目录及 request-001..024 全部通过原 SHA256 校验，保留失败运行。

- **真实调用完成**：新增 51、累计 75/120；保守 token 293690/300000，0 自动重试，缺失 usage 不记零。剩余 6310，本轮停止新增调用。
- **交付故障已定位并受控修复**：诊断复现 HTTP 200/length、512 输出 token 全用于 reasoning、正文为空；原六次具体原始返回未保留，不倒推或统归服务商错误。DeepSeek 仅关闭 thinking，其他生成参数不变，原 14 题全部正常交付。
- **TOKEN_LIMIT 单独定位**：原判别式两次均 512/length、2/2 步骤耗尽，总预算仍余 13477。修复后一次正常结束；新退化题仍有续写接缝瑕疵，保留为缺陷。
- **路径覆盖分开**：表达组 14 题；Knowledge 组 3 个真实模型用例及一个提示门控用例。先修 seed 区间未传给模型的缺口，再明示既有 quote/summary Schema 契约，分别实测，不放宽校验。最终总结实际调用 support_check，逐字引用按契约无需检查，无答案实际补搜，提示门控无调用。
- **语义评分已完成 AI 初审**：原 14 篇 57 个独立数学声明；provisional Faithfulness 宏平均 0.520153、最低0、内容覆盖0.571429、任务完成6/14。新增表达正文3题数学失败、退化c=0题仍错误；正常停止不作数学 PASS。所有参考和审阅仍 provisional / human PENDING。
- **开发质量 FAIL；正式验收 INSUFFICIENT_EVIDENCE**：剩余原因是实际数学/续写正文错误及人工校准、正式阈值、holdout/重复不足，不再是“未调用”或“AI逐声明数值未产生”。

新版本变更限于 Gateway 诊断与 DeepSeek bounded 模式、Knowledge 初始可读参数和 Claim Schema 说明、评测记录及版本元数据；未重构 RAG。新摘要见 `source-manifest.json`；未重建 0.4.1 安装包。

## 2026-09-20 真实模型首轮结果（历史快照）

**真实调用测量已完成：SEMANTIC_MEASUREMENT=COMPLETE。开发回归质量：SEMANTIC_QUALITY=FAIL。正式质量验收：INSUFFICIENT_EVIDENCE。** Provider 阻塞已解除，不能再把本轮写成“没有真实模型结果”。质量失败来自实际输出，正式结论仍缺人工逐声明复核和独立 holdout。

配置为用户明确指定的 DeepSeek / `deepseek-flash`；模型标识证据是请求/配置值；生产 Gateway 未保留服务端原始 model 字段，不将它冒充服务端独立型号证明。沿现有 Gateway 的 DeepSeek preset 使用 `https://api.deepseek.com/v1`，凭据通过隐藏输入进入现有 Windows SecretStore。非敏感配置、授权与计划位于 `artifacts/live-acceptance-20260920-v4/`，未另建 HTTP 客户端。只使用隔离合成资料与会话。

| 路线 | 已执行结果 | 结论边界 |
|---|---|---|
| A：生产 support_check | 8/8 有效判断，无 UNKNOWN/timeout/error；按调用前冻结的独立 AI 参考草案，有依据放行 4/4、无依据误放 0/4 | 草案尚未经人工确认，两个比例为 provisional；8 行仅 6 个不同输入，不是 8 个独立样例；不替代真实回答质量 |
| B：实际应用回答 | 14/14 问题发起真实调用；7 NATURAL_STOP、6 PROVIDER_ERROR 后模板降级、1 TOKEN_LIMIT | 正常完成率 7/14=50%；降级答案未回答原问题，截断答案未正常结束；开发回归不通过 |

调用预算：24 次实际请求，0 自动重试（其中一次是产品自带续写）；预算保守记账 169364 / 300000。18 个成功返回上报 input=9883、output=4773，合计 14656 token；另 6 个 gateway 错误没有可取得的 usage，**不能将它们按 0 token 计费，也不能把 14656 当完整总量**。未设额外金额上限。

B 的请求记录显示产品本轮输出上限是每次 512 token，授权的 1800 是上限而非强制覆盖产品配置。6 个失败均被 gateway 分类为 response_incomplete；原始失败响应及 usage 没有被现有接口暴露，因此不推断全部都是同一个服务端原因，也不把它们隐藏为模板成功。

B 实际落到 Tutor 表达路径：提供 Initial Retrieval 资料摘录，原生工具调用=0，support_check 调用=0。不能把“支持工具的架构存在”写成“本轮每个回答经过工具读取与语义检查”。12 个回答内引用标签都能映射到当时可见片段，但 12/12 只证明标签存在，**不是语义引用 precision 或回答 Faithfulness**。

独立 AI 核对发现 `easy:mixed_cjk_latex` 将 a=0 后的 bx+c=0 无条件称为一次方程，遗漏 b≠0；a=b=0,c=1 即给出反例。已用现有生产确定性 verifier 核验可支持的数值方程与展开样例，见 `deterministic-math-review.json`。不以支持检查器自评充当数学标签。

完整逐例上下文、实际输出、引用位置、错误/续写/模板标记以及五维人工复核栏位已导出：`execution/A-results.json`、`execution/B-results.json`、`execution/B-review-packet.json`。当前核对者为 Codex（与被测 DeepSeek 分离），不是人工或经人工校准的模型裁判；回答级 Faithfulness 宏平均/最低分及内容覆盖分数留 null，空模板不默认得 1 分。

本轮保留现有 corpus/annotation，使用 8 个 claim 行与 9 easy + 5 hard 问题，一次固定开发回归。参考草案在第一次请求前保存；未改提示词、标签或参数后挑最好结果。正式阈值仍待操作者冻结，尚无独立 holdout、三次重复、仅提示/资料冲突/多轮追问等完整教学验收覆盖。

本轮源码增量只有共享生产 support_check 与隔离记录/预算入口；已有离线协议/预算及工作台/E2E 回归为 21 passed，不作为语义证据。此前 0.4.0 安装包和 20+3 工程回归仍对应 2026-09-19 冻结源码，未冒充本轮新增入口的打包验证。第 22 项的“没有真实 provider”原因已撤销；保留 FAILED 的剩余原因是**独立回答 Faithfulness 指标与复核未完成**，不是把实际模型答错改写成未执行评测。

## 1. §42 验收清单逐条判定

| # | 验收项 | 判定 | 依据 |
|---|---|---|---|
| 1 | 三条消费路径共享 Orchestrator | **PASS** | 四条（Chat / Knowledge / hint+explain / practice）共享**同一个实例**；`UserDocumentsSourceProvider` 降为纯 EvidencePack 投影 |
| 2 | `DocumentIndexManager` 唯一 kernel | **PASS** | 签名未改 |
| 3 | `RetrievalPolicy` 收窄 practice-only | **PASS** | 生产类改为 `PracticeRetrievalPolicy`；旧名称仅保留兼容别名；漂移守卫通过 |
| 4 | `ProductionReranker` 单一化 | **PASS** | 内联魔数已移除 |
| 5 | `ContextExpander` 已实现 | **PASS** | parent-first（按 chunk_id 解析，非 sequence 推导）+ sequence±N；预算内；**跨 section 邻接被拒绝** |
| 6 | `EvidencePack` 已冻结 | **PASS** | `query_fingerprint` / `EvidenceCoverage` / `timings` / `partial` 已补；`partial` 仅由**预算截断**决定 |
| 7 | Initial Evidence 可直接引用 | **PASS** | `seed_evidence` 双校验 |
| 8 | Second Retrieval 可工作 | **PASS** | 工具链 + telemetry |
| 9 | scope UNSET fail closed | **PASS** | `document_ids` 必填无默认 |
| 10 | no embedding 完整可用 | **PASS** | 全量回归 lexical |
| 11 | PDF baseline 与 package 一致 | **PASS** | extras + package-surface 测试 |
| 12 | D20 回退链修复 | **PASS** | baseline 无关 + 测试 |
| 13 | FTS 不再全表重建 | **PASS** | 哨兵测试 |
| 14 | index signature 完整 | **PASS** | migration 022 + `normalization`/`runtime_version` |
| 15 | stale bindings 清理 | **PASS** | `_detach_from_conversations` |
| 16 | fake v1 snapshot 修复 | **PASS** | 显式 version 缺行 → fail closed |
| 17 | historical citation contract | **PASS** | CitationReceipt（迁移 023）：签发/校验/删除即失效；扩权矩阵 14 项测试 |
| 18 | telemetry 真实接线 | **PASS** | 首次实例化 |
| 19 | RAG health 可读取 | **PASS** | `rag_health()` 全 scalar |
| 20 | production benchmark 完成 | **PASS** | `tests/test_rag_production_benchmark.py` |
| 21 | 旧 benchmark 完成迁移 | **PASS（DEPRECATED REMAINING）** | 新基准取代；旧文件已标记弃用未删（§4） |
| 22 | Retrieval/Context/Citation/Faithfulness 指标真实产生 | **FAILED** | 测量已 COMPLETE；独立 AI 对原 B 14篇/57声明的 provisional Faithfulness 数值已产生，不能再写未测量。保留正式门未通过：人工校准/冻结阈值/holdout不足；开发数学质量 FAIL。不得将 AI 初审改写为人工验收 |
| 23 | package-surface 覆盖新增模块 | **PASS** | 27 项 |
| 24 | Windows packaged runtime probe | **PASS** | 0.4.0 最终源码候选包；仓库外 isolated Python / 事务取消 / backup-restore / 严格目录清理通过；桌面 smoke 17/17；202 个模块 hash 匹配 |
| 25 | backend regression | **PASS** | schedule-3：20 轮定向各 52 passed；3 次全量各 1336 passed / 11 skipped / 0 failed；所有前后源码摘要一致 |
| 26 | web regression | **PASS** | 0.4.0 web-040-final.log：164 passed / 0 failed；历史结果独立保留 |
| 27 | desktop regression | **PASS** | 0.4.0 desktop-040-final.log：distribution 验证与契约 44 passed / 0 failed / 2 skipped |
| 28 | `RAG_ARCHITECTURE.md` | **PASS** | 本目录 |
| 29 | `RAG_EVALUATION.md` | **PASS** | 本目录 |
| 30 | `RAG_IMPLEMENTATION_REPORT.md` | **PASS** | 本文件 |

**PASS 29 · PARTIAL 0 · FAILED 1 —— 合计 30 项**（保留原 ID；Web/Desktop 使用本轮实跑证据）
（首轮为 PASS 14 / PARTIAL 3 / FAILED 13）

### 1.1 台账口径更正（30 项 vs 此前写的 28；历史更正记录）

本小节保留此前算术更正的原始依据，以下 27/2/1 及“仅第 22 项失败”描述的是当时状态；本轮曾重新开启第 25 项，修复后按固定重复证据恢复 PASS；当前判定以 §1 表格为准。

`[事实]` 本表**一直是 30 行**（ID 1–30 无缺号），但此前的小结行写成 `PASS 25 · PARTIAL 2 · FAILED 1`，
即 28 项。**这是小结行的算错，不是漏了门槛。** 逐行核对结果：

```
行数 30        实际判定：PASS 27 · PARTIAL 2 · FAILED 1 = 30
此前小结         PASS 25 · PARTIAL 2 · FAILED 1 = 28   ← PASS 少算 2 项
```

`[事实]` 少算的 2 项是第 11 项（PDF baseline 与 package 一致）与第 23 项（package-surface 覆盖新增模块），
两行都写着 **PASS** 却未被计入小结。

`[判定]` **分母是 30，不改为 28。** 未删除任何门槛，也未通过改分母取得闭合。
本次更正只把小结改回与表格一致（27+2+1=30），**没有任何一项判定由 FAILED/PARTIAL 变为 PASS**。

`[判定]` **§42 仍有 1 项 FAILED（第 22 项），不输出 FINAL_RAG_CLOSURE。**

---

## 2. CLOSED

| 缺陷 | 修复 | 证据 |
|---|---|---|
| **D1** scope fail-open | 编排器 `document_ids` 必填无默认；provider 对 `None` fail closed | `test_retrieval_safety.py` |
| **D2** stale binding | `_detach_from_conversations`（`delete_document` 内，经 `DataLifecycleService`） | `test_phase6_data_lifecycle.py` |
| **D4** index signature | migration 022：`embedding_normalization` / `embedding_runtime_version` 纳入 `matches_signature`；空值视为不匹配 → 旧行重建一次 | `test_embedding*.py` |
| **D5** FTS 写放大 | `sync_document_chunks_fts(document_id=...)` 按文档同步 | 哨兵测试（他文档行未被重建） |
| **D7** recovery 冒充 text_layer | `parse_mode="recovered_external"` | `test_pdf_classification.py` |
| **D10** 历史引用未解耦 | `CitationReceipt` + 独立 `read_citation` 模式；删除即失效 | `test_citation_receipts.py`（14 项） |
| **D8** 两个 hash 混淆 | `source_hash` → **`source_file_hash`**（正文侧另有 `body_hash`） | `knowledge.py` |
| **D9** version 冒充 | 显式 version 且无行 → `KnowledgeError` | `test_knowledge_safety.py`（含前提断言） |
| **D11** 可见性守卫 | `list_retrievable_chunks` / `list_chunk_neighbourhood` 均带门 | `test_retrieval_safety.py` |
| **D12** ingest 返回 None | 并发删除时回退稳定 failed 投影 | `test_document_pipeline.py` |
| **D13** policy 职责误述 | 精确 SCOPE + `PRODUCTION_INTENTS` + 扫描源码漂移守卫 | `test_retrieval_policy.py` |
| **D17** 重复分词 | 单次计算 | 代码审查 |
| **D19** 声明/打包不一致 | `pdf-rich` / `embedding` extras | `test_declared_dependencies_match_the_shipped_runtime` |
| **D20** MinerU 可达性 | 与 baseline 解耦 | `test_external_recovery_is_reachable_without_pymupdf` |

### 2.1 本轮新增

| 项 | 说明 |
|---|---|
| **Chat 路径统一** | `ChatDocumentContext` 降为 projection/selection adapter，检索全经 orchestrator |
| **Reranker 单一化** | `KnowledgeService.search` 的内联 `+1.0/+0.25` 移除，走 `ProductionReranker` 命名常量 |
| **Telemetry 按轮次** | `second_retrieval_rate = 有二次检索的轮次 / 有初始检索的轮次`；`average_second_search_calls` 分离成本信号；`retrieval_request_rate` 分母改为**总轮次**（此前会算出 9.0 这种 >1 的"比率"） |
| **`rag_health()`** | 10 项全 scalar |
| **唯一官方 benchmark** | 真实 SQLite 语料 → 真实 kernel → 真实 EvidencePack；含安全场景与夹具自校验 |
| **Package-surface 硬验收** | 27 项，生产模块必在包内 / test-only 必在包外 / 无模块被静默排除 |
| **探针扩展** | 检查全部新增生产模块可导入 + `ProductState.metrics` 存在 |

---

## 3. 本轮被抓出的真实缺口（值得单列）

1. **`desktop/main.js` 硬编码迁移版本号**（`frozen === "020"`）。我连升两级却没同步，**Desktop 契约测试当场失败**。这是"源码改了、发行面没跟上"的又一次实例——正是 §32 那条硬验收要防的东西。已修为 `022`。
2. **`src/mathtutor/__main__.py` 不在打包清单**（package-surface 测试发现）。核实后确认**有意且正确**（`desktop/main.js` 用 `import mathtutor.standalone` 启动），已作为 `SOURCE_CHECKOUT_ONLY` 显式记录而非静默放行。
3. **`retrieval_request_rate` 口径错误**：分子是检索次数、分母是轮次，9 条 query 一轮闭合时算出 `9.0`——一个不可能 >1 的"比率"。已改为 `有初始检索的轮次 / 总轮次`。

`[事实]` **三处测试夹具自身的错误**也被测试捕获：D5 哨兵测试用相同字节导入两份文档（命中去重，实为同一文档）；benchmark 的 `(doc, sequence)` ground truth 指向 chunker 从未产出的序号；另一处断言未随语料重构同步。夹具已自校验化（`test_ground_truth_matches_the_real_chunking`）。

---

## 4. DEPRECATED / DELETED

`[事实]` **本轮未删除任何源文件。** 结果：**DEPRECATED REMAINING**。

| 模块 | 标记 | 理由 |
|---|---|---|
| `application/retrieval_router.py` | **DEPRECATED** | 零生产引用；由 orchestrator + kernel 取代 |
| `application/lexical_reranker.py` | **DEPRECATED** | 由 `rerank.py` 取代 |
| `tests/test_phase6_retrieval*.py` + `benchmark_fixtures.py` | **DEPRECATED** | 覆盖上述栈；官方基准已迁移 |
| `infrastructure/sqlite_vec_index.py` | **DEFERRED（非死代码）** | `production sqlite-vec ANN` 在冻结 DEFERRED 清单内 |

`[事实]` 三个模块的 docstring 顶部已加显式弃用说明，并写明"Do NOT wire into a production path"。

**未删除的原因（诚实说明）**：删除 `retrieval_router.py` / `lexical_reranker.py` 会连带使 `test_phase6_retrieval*.py` 无法导入，而其中 `test_phase6_retrieval_metadata_first.py` 同时是 **sqlite-vec 适配器唯一的测试覆盖**——而 sqlite-vec 属于 DEFERRED（保留）而非删除项。要正确删除需先把那部分测试重新安置；本轮未完成该工作，因此选择按你允许的 `DEPRECATED REMAINING` 口径显式标记，而不是做一次我无法充分验证的删除。

`[事实]` **旧的 `test_phase6_retrieval_benchmark.py` 不再是官方基准**，其文件头已注明被 `test_rag_production_benchmark.py` 取代。

---

## 5. 已知缺口（不记为已验证）

1. `[事实]` ~~D9 的修复没有专项测试~~ —— **已补**：`test_knowledge_safety.py::test_explicit_missing_version_fails_closed_without_prior_snapshot`，用**摄入型文档**（有 chunks、无 version 行）构造该路径，并先断言前提成立再断言 fail closed。
2. `[事实]` **benchmark 语料无区分度**：全部指标 1.0。见 `docs/RAG_EVALUATION.md` §2.1 —— 这本身是基准设计不足，不是质量证明。
3. `[事实]` **上下文扩展在真实链路上一从未触发**（9/9 `expansion_used=false`），因此扩展路径**未被评测覆盖**。
4. `[事实]` ~~D10 未解耦~~ —— **已关闭**（§6.3）。
5. `[已验证]` 当前 0.4.0 候选包已完成仓库外探针，见本次修复证据；后端固定重复门也已按 schedule-3 完成验证。

---

## 6. 剩余 FAILED

### 6.1 ~~结构化路径未接入 orchestrator~~ — **已关闭（F1）**
`ProductState.retrieval_orchestrator` 是唯一实例，被四条消费路径共享：Tutor chat
（`ChatDocumentContext`）、Knowledge QA、hint/explain 与 practice（经
`ContextAssembler`）。`UserDocumentsSourceProvider` 降为**纯投影**：`EvidencePack →
DocumentContextSelection`，自身不再持有任何检索能力（`_searchable is None`），
没有 orchestrator 时**拒绝**而不是自己搜。

`[事实]` 实施中该测试**抓出两处真实缺口**：`ChatDocumentContext` 与 `KnowledgeQA`
各自 `new` 了一个 orchestrator —— 同类同配置但**不是同一对象**，功能上今天等价、
未来必然漂移；以及 orchestrator 的构造位置早于 `document_index` 赋值。两者已修。

### 6.2 历史快照：Faithfulness 缺少真实 provider（当前阻塞已解除，见顶部）
当前 hard-corpus/2 已具备 C1–C5 与 Context 指标，不再重建语料。缺口是语义评测 `BLOCKED_PROVIDER`：real_decisions=0、rates=null；需显式批准现有配置中的 provider，协议桩不作为语义质量证据。

### 6.3 ~~D10 历史引用未解耦~~ — **已关闭**
`CitationReceipt`（迁移 023）+ `read_citation_receipt` + 独立 `read_citation` 工具。
**F3 决策（选项二）**：删除是物理删除，`privacy deletion overrides historical citation
availability` —— 删除后 receipt 一并移除且校验 fail closed；禁用则 receipt 继续可验
（禁用不是删除，已发出的引用不该因为后来关掉检索就失效）。

### 6.4 历史待办及本轮进展

本轮已完成命名和附录 B 的 8 项自动化场景；E2E4 验证实际发现并补齐 `AGENT_SEARCH` hop 记录。新包须等待生命周期重复门完成后重建验证。下段为历史待办，不作为当前状态：
`RetrievalPolicy` → `PracticeRetrievalPolicy` 改名（§A2）；显式文件引用（"根据这份资料"）进入 decision 层；Query rewrite 的 `formula_terms` / `skill_terms`；hard set 语料与 Context/Faithfulness 指标（§E/F/G）；八条 E2E 场景未编写为自动化测试
（清单见**附录 B**，原引 §N）；`win-unpacked` 探针重跑（§M）。

`[事实]` 本轮已完成（此前列于本节）：`RetrievalHop` multi-hop 语义（hop 1 = INITIAL，`hop_count` / `second_retrieval_used`，**只存 query 指纹不存 query 文本**）；`EvidencePack` 的 `query_fingerprint` / `coverage` / `timings` / `partial`；D9 专项测试。

---

## 7. 冻结 DEFERRED

```
built-in OCR engine                  NOT IMPLEMENTED
production sqlite-vec ANN            NOT IMPLEMENTED（维持 OPTIONAL）
optional neural reranker             NOT IMPLEMENTED
bundled heavy embedding runtime      NOT IMPLEMENTED
advanced GraphRAG                    NOT IMPLEMENTED
```

`[事实]` `rag_reranker_unavailable_total` **确认不实现**：生产 reranker 确定性、随包发布、无 unavailable 状态。

---

## 8. 回归证据

### 8.1 本轮实际运行（2026-09-19）

```
.venv/Scripts/python.exe -m pytest tests/ -q -p no:randomly
  运行 1（全量）                       1 failed, 1313 passed, 11 skipped
  运行 2（剔除本轮唯一改动的测试文件）   1 failed, 1300 passed, 11 skipped
  运行 3（全量）                       2 failed, 1312 passed, 11 skipped

聚焦（官方 benchmark + 编排 + 引用凭证 + agentic + 安全 +
      knowledge 安全/工作台 + context assembler）
                                    114 passed, 0 failed
```

### 8.2 Windows 关闭失败：重新调查

此前“预先存在、与本轮无关、根因已证明为竞态”的归因撤回。仅凭改动文件范围或单测独跑通过，不能确定引入来源或排除顺序依赖。上述三次失败结果保留；本轮先重开全量门，修复后再以 schedule-3 的固定重复证据恢复 PASS。

本次确定性复现见 `artifacts/lifecycle-repair/ownership-before.log`：
重复迁移的 stdlib SQLite 连接在函数返回后仍可执行 SQL；持有读连接时，原 `shutdown_runtime` 在手动 unlink WAL 处抛出 PermissionError。
`with sqlite3.connect()` 只管理事务，不关闭连接。生产迁移和测试 `_cycle_count` 都存在此所有权缺口。
修复显式关闭连接、由 SQLite 删除侧文件、保留关闭失败并阻止恢复替换。随后还定位并修复 ASGI 取消打断 TeachingRepository 清理；最终 20 轮定向与 3 次全量已完成，详见“本次修复证据”。

### 8.3 其他回归面（0.4.0 当时源码）

```
web (npm test)                  164 passed / 0 failed
Desktop distribution/contracts  44 passed / 0 failed / 2 skipped
```

证据为 `web-040-final.log` / `desktop-040-final.log`；较早运行结果保留在独立日志，不替代本次执行。

---

## 9. 当前结论

0.4.0 当时源码与候选包已完成历史工程验证：20 轮定向、3 次后端全量、Web/Desktop 回归、附录 B 八项 E2E、包外 runtime/lifecycle/桌面 smoke 均通过。原 30 个 ID 的台账为 **29 PASS / 0 PARTIAL / 1 FAILED**。

2026-09-20 最新更新：第 22 项真实测量 COMPLETE，原 B 的逐声明 AI 初审及 provisional Faithfulness 数值已完成；剩余为人工校准、正式标准及独立验收证据。0.4.1 原题集交付恢复，数学正文及新增续写接缝仍有失败，开发质量 FAIL；正式验收 INSUFFICIENT_EVIDENCE。详见顶部新版本实测，不复用旧包门作为新版本证据。

---

## 附录 A — F2 历史恢复区

以下保留增量 5 的历史记录；当前状态与 0.4.0 证据以 §1、§9 和“本次修复证据”为准。

**当前子任务**：F2 **增量 5 完成** —— 评测补全：easy set 接官方实现、组件消融、citation 分队列、
fixture/citation 双注入小节、语义模式入口、答案质量导出、台账 30/28 更正。
**历史快照：§42 第 22 项当时为 FAILED**（当时 Faithfulness 无 provider、easy set 无区分度；当前原因见顶部）。
**下一步：E2E 1–8（清单见附录 B）/ `PracticeRetrievalPolicy` 改名 / 新版本包验证（见 §7）。**
`[事实]` 八条清单原不在仓库内，已由需求方补入**附录 B**（含两个 E2E7 版本及取舍理由）——**阻塞解除**，
E2E 门现在可施工，因为范围已有落盘依据。

**增量 5 实测**
```
easy  9 query / 12 chunk   R@5=1.000 MRR@5=1.000 nDCG@5=1.000 Hit@1=1.000
hard  5 query / 17 chunk   R@5=1.000 MRR@5=0.900 nDCG@5=0.949 Hit@1=0.800
ablations  production CP=0.3444 | no_reranker CP=0.3389 (dCP -0.0055, dCR 0)
           no_expansion CP=0.3500 (dCP +0.0056, dCR 0, required 无丢失)
citation   attribution(valid+incorrect) P=0.875 R=1.000  cases=4 links=5
           operational(malformed) rejection=1.000        cases=1 links=1
           receipt validation=1.000   unauthorized rejection=1.000
semantic   BLOCKED_PROVIDER（real_decisions=0，rates=null，不报 0.0）
failures   citation_mutations=OK   fixture_mutations=OK
RR         selected 0.9133 vs corpus 0.8307 → 主要是夹具自相似，不是产品缺陷
台账       30 项：PASS 27 / PARTIAL 2 / FAILED 1（小结行此前少算 2 项 PASS）
```

**增量 4 实测（Citation / Faithfulness / mutations）**
```
Citation Precision (macro) = 0.750   仅 CC1/CC2 两条真实 claim（注入探针不计入）
Citation Recall    (macro) = 1.000
Historical Receipt Validation Rate          = 1.000  (1/1)
Unauthorized Historical Read Rejection Rate = 1.000  (4/4，含删除后失效)
mutations.verdict = OK —— INJ1 篡改 quote / INJ2 伪造 source_id / INJ3 quote-kind 不符
                     全部被拒；另两条 fail-closed（无 entailment 后端 / 检查器返回 false）
Faithfulness = NOT_MEASURED（无蕴含模型；stub 只证协议通，不冒充语义质量）
```

**增量 3 实测（Context）**
```
Q01 C1 CP=0.222 CR=1.000  intended C1, observed C1
Q02 C3 CP=0.250 CR=1.000  example#1 ← 补回 example#0（child→parent）
Q03 C5 CP=0.500 CR=1.000  guard exercised=True holds=True leaks=none
Q04 C4 CP=0.500 CR=1.000  distractor neighbour#2 被扩展拉入（预期），CP 受罚
Q05 C2 CP=0.250 CR=1.000  intended C2, observed C2
macro CP=0.344 CR=1.000 NR=0.656 RR=0.913   expansion-required 子集 CP=0.306
intent/observation mismatches: 0    自检 91 条 / 0 失败    isolation ok=True
```

**已修改文件**
- `scripts/rag_hard_set_probe.py`（评测补全：easy/消融/队列/注入/语义入口/导出/provenance）
- `tests/test_rag_production_benchmark.py`（**唯一改动**：抽出 `build_benchmark()` 供 runner 复用；
  `_rank` 增加可选 `owner` 参数，默认值不变 —— 行为中性，13 项测试通过）
- `artifacts/rag-evaluation.json`（产物，schema `mathtutor.rag-evaluation/2`）
- `docs/RAG_EVALUATION.md`（§0 新增、§3.3 RR 归因、§4 队列、§5 语义/答案质量、§5.1 消融）
- `docs/RAG_IMPLEMENTATION_REPORT.md`（§1.1 台账更正、附录 A）
- **生产代码零改动**（`src/` 未动）

**已运行命令**
```
.venv/Scripts/python.exe scripts/rag_hard_set_probe.py --evaluate      # exit 0
.venv/Scripts/python.exe -m pytest tests/test_rag_production_benchmark.py \
    tests/test_retrieval_orchestration.py tests/test_citation_receipts.py \
    tests/test_agentic_retrieval.py tests/test_retrieval_safety.py \
    tests/test_knowledge_safety.py tests/test_knowledge_workbench.py \
    tests/test_context_assembler.py -q -p no:randomly
# 114 passed / 0 failed
.venv/Scripts/python.exe -m pytest tests/ -q -p no:randomly            # 全量，见 §8
# 运行 1：1 failed / 1313 passed / 11 skipped
# 运行 3：2 failed / 1312 passed / 11 skipped
# 失败项为既有 Windows WAL 句柄竞态（§8.2），非本轮引入
```

**产物路径**：`artifacts/rag-evaluation.json`（结构含 easy/hard/overall/context/faithfulness/citation/mutations）

**语料（17 chunk / 8 文档）**
```
neighbour 3 chunk  C4：`定义：` 另起 group 但继承 heading_path → 同 section 干扰邻居
disc      2 chunk  C1 / C2      example 2 chunk  C3 (child→parent)
boundary  3 chunk  C5           weida 1 chunk    词汇干扰
linear / fraction / inequality  各 2 chunk  填充，使 pack 装不下全集
```

**两处必须记住的判断**
1. **C1/C2 是「意图 vs 观测」**：两者 fixture 真相相同（同 section 相邻），差别只在 kernel 命中哪一侧，
   这是**结果**。脚本算 `observed_relation` 并单列 `relation_mismatches`（实测 0）。
2. **C4 的 distractor ≠ C5 的 forbidden**：前者**预期被拉入**（计入 CP，非缺陷），后者**必须拒绝**
   （拉入即 expansion leak）。混用会把正常工作的 C4 报成缺陷。

**自检 91 条 / fail-fast / 0 失败**（在指标计算之前运行，失败即 BENCHMARK_INVALID 且不出数字）。
注入验证已确认这些检查真的会失败：anchor 指错 sequence；required ⊄ relevant；伪造 C5（不同 section）；
C4 distractor 移入独立 section；答案句塞进 distractor —— 五种注入各自触发对应检查。

**历史增量小结（由 §1 与本次修复证据覆盖）**

**当时下一条具体动作**
`PracticeRetrievalPolicy` 改名 / win-unpacked 探针重跑；E2E 需先解除 §7.1 的清单阻塞。

**当前阻塞点（精确）**
1. **语义评测 `BLOCKED_PROVIDER`** —— 需操作者显式授权 provider；脚本不会自行发现密钥或选择付费 provider。
2. **release 门未验** —— `desktop/dist` 是 **0.2.0** 旧构建，仓库是 0.3.3。
   必须重新构建当前版本并记录 SHA / app version / migration / artifact hash；
   无法构建时记 `RELEASE_BLOCKED`，**不得借旧包 Python 导入新源码冒充打包通过**。
3. **全量回归不全绿** —— Windows 资源所有权故障（§8.2）；此前“与本轮无关”的归因已撤回，必须按当前证据定位。
4. ~~需求书 §N 八条清单缺失~~ —— **已解除**：清单已补入附录 B，E2E 门可施工（尚未编写为测试）。

**未开始（不得记为已验证）**：Faithfulness（provider 阻塞）、答案质量（无 generator）、
E2E 1–8（清单已就位，测试未编写）、`PracticeRetrievalPolicy` 改名、新版本包验证、web/desktop 本轮重跑。

### 7.1 外部引用清单缺失（历史调查；E2E 已按附录 B 实现）

本轮明确采用现有 30 个稳定 ID 和用户提供的附录 B，保留以下来源调查，不因缺少外部 §42 原件而暂停已授权工作。下面“测试未写”和实现一致性的判断均为施工前状态：E2E4 实跑发现 hop 接线缺口，现已修复。

`[事实]` 本报告多处引用**需求书的字母小节**，而**该需求书不在本仓库内**：

| 引用 | 出现位置 | 指向 |
|---|---|---|
| `§42` | §1 的 30 项台账 | 需求书 §42（验收清单原件） |
| `§N` | §6.4 一行 | 八条 E2E 场景 |
| `§A2` / `§E1` / `§E/F/G` / `§M` | §6.4、§6.2 | 改名 / C1–C5 形态 / 评测指标 / 探针重跑 |

`[事实]` **`§N` 的八条清单在本仓库中不存在。** 全仓唯一出处是 §6.4 那一行本身，
它只说"八条 E2E 场景未编写为自动化测试（§N）"，**从未列出这八条是什么**。检索证据：

```
grep -rl "需求书"  → 仅 docs/CURRENT_STATE_RAG_AUDIT.md、docs/RAG_EVALUATION.md、本文件
                    三者都是"引用它"，没有一个是它本身
git log -S "§N"    → 空（该串只存在于未提交的工作区文本里）
docs/ 23 个文件 + rc/ releases/ standalone/ ci/ 子目录 → 无任何需求书 / 规格文件
仓库外同目录（deliverables / mathtutor_rnd_pack / ppt资料 / 专利）→ 亦无
git log --diff-filter=D -- '*需求*' '*requirement*' → 空，即历史上也从未提交过
```

`[判定]` **我无法提供原八项清单，也不会据此编造。** 杜撰八条并写成"已编写"，
等于**悄悄把验收范围重新定义成我刚好能交付的东西** —— 这正是要避免的。

`[更正]` `[事实]` 另外需要更正我自己的措辞：附录与小结里我写的 **"E2E 1–8"是我从"八条"推出来的**，
原始文本只有"八条 E2E 场景（§N）"，**并不存在被我见过的编号清单**。已改回准确表述。

`[判定]` 在清单缺位时：**E2E 门既不能开工，也不能标 PASS，更不能标 FAILED**
（FAILED 意味着"测过且没过"，而这里是"根本不知道要测什么"）。它应记为**外部依赖缺失**。

`[事实]` **该项已解除**：需求方随后把八条清单补入**附录 B**，含两个 E2E7 版本与取舍理由。
范围因此有了落盘依据，E2E 门从"外部依赖缺失"转为**"范围已定、测试未写"** ——
这是两种不同的状态，未编写不得记为已验证，但也不再是阻塞。

`[事实]` 拿到清单后做了一次**与既有实现的一致性核对**（避免一组自相矛盾的验收判据）：

| 用例 | 与已实现代码是否一致 |
|---|---|
| E2E3 seed→cite 免重复 search | 一致（台账第 7 项 / `test_agentic_retrieval.py`） |
| E2E4 `AGENT_SEARCH` / `hop_count` / `second_retrieval_rate` | 一致（`RetrievalHop` 已实现） |
| E2E7 **后修版**（disable 可验 + delete 失效） | 一致（F3 决策二；本 runner 实测 `after_deletion` 被拒） |
| E2E8 UNSET scope fail closed | 一致（台账第 9 项 / `test_retrieval_safety.py`） |
| E2E5 无 `sentence_transformers` 仍可用 | 一致（发布形态即 lexical-only，见记忆与 §7） |
| E2E6 无文字 PDF → `needs_ocr`、不得 500 | 一致（D7/D20） |

`[判定]` **未发现与实现冲突的判据**，因此不再需要就清单本身提异议。E2E7 采用后修版，
且本 runner 的 receipt 生命周期实测（禁用后仍可验、删除后拒绝）与该版本判据同向。

`[事实]` 同一问题更严重的一面：**§42 台账本身也是转抄**。表中 30 行的条目名与 ID 来自需求书 §42，
本仓库无法交叉核对"第 22 项"是否真的名为 `Retrieval/Context/Citation/Faithfulness 指标真实产生`。
`[判定]` §1.1 那次"30 行 vs 小结 28"的更正是**表内算术**核对，与需求书无关，因此依然成立；
但**条目名与编号的权威性**在拿到 §42 原文前无法确认。

`[需求]` 仍缺 **§42 原文**（或需求书本身/路径）。§N 的八条已由附录 B 满足。
在 §42 原件到位前，"保持原验收范围"只能以**本仓库 §1 这张转抄表**为准，
并显式标注它**未经原件核对**（条目名与编号的权威性尚未确认）。

## 本次修复证据（2026-09-19，0.4.0）

当前权威台账为第 1 节；历史小结不覆盖当前门槛。原 30 个稳定 ID 未增删。附录 B 的后修版 E2E7（含删除后物理移除 receipt）原样保留。

### 已证实的资源与退出顺序问题

- 迁移和部分测试夹具把 `with sqlite3.connect(...)` 当作关闭连接；它只结束事务。`ownership-before.log` 留住引用后证明连接仍可执行 SQL。生产迁移改为显式 closing、迁移引擎 finally dispose；夹具也显式关闭，保留原事务提交语义。
- 外部 reader 仍持有 SQLite 文件时，旧 shutdown 尝试 unlink WAL，确定性产生 WinError 32。现在关闭入口、排空请求、等待 owned services/workers 后检查 pool；有活跃连接或残留 sidecar 就明确 FAILED，拒绝 restore。不会手动删除 WAL/SHM，也不依赖 GC。
- `schedule-2/full-1` 暴露真实 ASGI 取消路径：展示确认写入 TeachingRepository 时 WebSocket 断开，AnyIO 反复取消 rollback/close，首个异常是连接终止时的 CancelledError，随后才出现 no active connection 与 checkpoint busy。完整首错在 `full-1-trace.log`，不能把后续 WAL 错误当作首因。独立取消作用域复现曾卡在清理中（超时诊断保留）；新增 `test_transaction_cancellation.py` 在 INSERT 后主动取消并验证 rollback、checkedout=0 和 checkpoint 成功。事务退出和 WS 子任务回收现有取消保护与 5 秒边界。
- 同次全量还发现第二次创建应用复用 STOPPED 单例而返回 503。工厂仅重建已完整停止的状态，FAILED 仍关闭入口。
- shutdown 并发调用共用清理任务；调用方取消也等待清理。stage 失败保留首异常，并继续独立安全清理；部分 startup 失败执行 shutdown。backup 线程任务显式归属、等待；verifier 超时保留未退出进程的所有权并报错。失败不会宣称 STOPPED，不进入数据库替换。

生命周期 trace 仅记录实例/任务/线程/进程/连接标识、阶段、异常类型和函数行号。原始 pytest 日志只使用隔离测试库；生产 trace 不含 SQL 参数、正文、凭据或用户数据路径。

### 验证记录及失败保留

证据目录为 `artifacts/lifecycle-repair/`。修复前诊断全量一次 1314 passed / 11 skipped（`baseline-full.log`），未采集该运行初始源码摘要，因此不是当前门槛证据。`ownership-before.log` 为两个确定性失败；`fixture-ownership-diagnostic.log` 为 11 failed / 13 passed，暴露尚未关闭的 fixture 连接。

schedule-1 在发现 fixture 缺陷后中断；schedule-2 的 full-1 为 **2 failed / 1333 passed / 11 skipped**，full-2 中断、full-3 未运行；所有日志和 interruption.json 保留，未运行/中断均不计 PASS。schedule-2 的版本切换混合轮也明确不作为同一摘要重复证据。

修复上述具体缺陷后，`cancellation-fix-first.log` **73 passed**。预先声明并已完成的 schedule-3 为 **20 × 52 项**定向测试（生命周期、事务取消、连续应用创建、完整 phase5 E2E 前序及 phase6 集成），然后 **3 次后端全量**。每次执行一次，记录退出码与前后摘要，不以某次绿灯覆盖失败。**20 轮定向全部通过；3 次全量每次均为 1336 passed / 11 skipped / 0 failed**，用时分别 422.53 / 429.86 / 429.35 秒（含 pytest 启动）。23 次运行前后摘要始终为 `e2f5b90b7d7f53174270aaa225345e1ebc09607915ec65a5d320a49e1ef6b7d7`。未复现此前连接终止/no active connection 异常；有限重复不代表普遍安全。

0.4.0 冻结源码 Web **164 passed**（`web-040-final.log`）；Desktop distribution 与契约 **44 passed / 2 skipped**（`desktop-040-final.log`）。较早的 web-current.log / desktop-current.log 保留为本轮中间证据。附录 B **8 项 E2E 已执行通过**，见 `final-040-targeted.log`，也进入后续全量。E2E 中脚本化模型仅验证工具/协议链路，不计语义质量。E2E4 实测发现 `AGENT_SEARCH` 只有定义未接线，现按真实 search 记录 hop 并验证 hop_count 和 second_retrieval_rate。

### 评测与版本证据

0.4.0 是当前目标版本；0.2.0 dist 和本轮中间构建均不替代最终源码证明。修复后的候选包位于 `release-0.4.0-final/`；仓库外目录 `../runtime-validation-20260919`、隔离 `-I -B` Python、精简环境运行，未注入 checkout 源码路径。202 个包内 Python 文件逐一 hash 匹配；migration=023。runtime / lifecycle / desktop 三个探针 exit=0，桌面 17/17（含 restore→restart→post-restore solve→tracked processes gone/temp removed），包内事务取消、backup-restore、严格目录清理均通过。模块位置与来源位于 `packaged-040-final-*`。安装包 132278651 bytes，SHA256=`d954d8c4e3723d297d11ce8139fdbad2a0ae13d75ed05fe0a918d06c4db22d3a`；详见 `release-040-final-manifest.json`。该包源码摘要与已完成的 23 次重复验证一致。语义 provider 门仍未通过，不能据此宣称所有 RAG 验收闭合。

构建主机 Node 22.20.0 的原生 fs.cpSync fast path 曾异常退出（Windows 0xC0000409）。最小复现确认 copyFileSync 与带 filter 的 JS copy 路径可用；构建仅用未打包的 preload 指定恒真 filter，保留全部文件与原选项，未跳过 distribution 验证。preload SHA256=`306740517473a59dff8d165942daa0f72ccdbb8e0dbf0664e03b254fcb9487eb`，原失败日志仍保留。

评分前独立检查 owner、scope、可见性、摄入状态与 reference；合法零结果是 scored miss，empty/no-answer 不从分母剔除。引用宏 P=`(1+0.5+1+1)/4=0.875`，4 case/5 link，微 P=0.8；逐例标签和分数保持原样，详见 RAG_EVALUATION。schema v2、hard-corpus/2、hard-annotations/3 不变；本集 no-expansion 的 recall 增益为 0。语义评测 **BLOCKED_PROVIDER**，real_decisions=0、rates=null，无批准 provider，不访问无关凭据。

### 复现入口

重复计划从仓库根目录执行：

```powershell
$env:MATHTUTOR_REPEAT_ID='schedule-new'  # 必须使用尚不存在的目录，避免覆盖历史
.venv/Scripts/python.exe scripts/repeat_lifecycle_acceptance.py
```

`schedule.json` 在首轮开始前落盘，包含完整固定顺序及逐文件 SHA256；运行摘要覆盖 tracked/untracked 源码、脚本和测试，排除 docs/artifacts。`results.jsonl` 保留每轮退出码、时长、运行前后摘要。

已有 web 0.4.0 build 与 provisioned runtime 下，从 desktop 目录复现打包（输出另选新目录）：

```powershell
$preload=(Resolve-Path '../artifacts/lifecycle-repair/windows-copy-preload.cjs').Path.Replace('\','/')
$env:NODE_OPTIONS='--require="' + $preload + '"'
$env:MATHTUTOR_PYTHON_RUNTIME=(Resolve-Path '../.runtime/python-win-x64').Path
$env:ELECTRON_BUILDER_CACHE=(Resolve-Path '../.runtime').Path + '\electron-builder-cache'
$env:CSC_IDENTITY_AUTO_DISCOVERY='false'
.\node_modules\.bin\electron-builder.cmd --config electron-builder.config.cjs --win nsis --x64 --config.directories.output=../artifacts/lifecycle-repair/release-reproduce
```

包外 probe 的完整 command/cwd/environment key 列表保存在 `packaged-040-final-results.json`；所用探针位于仓库外 `../runtime-validation-20260919/`，包内解释器以 `-I -B` 启动。桌面探针用 `--smoke-full`，进程以隐藏窗口运行。

### 独立 SQLite 依赖事项

开发 SQLite **3.45.1**，source_id=`2024-01-30 16:01:20 e876e51a0ed5c5b3126f52e532044363a014bc594cfefa87ffb5b82257cc467a`。
打包 SQLite **3.49.1**，source_id=`2025-02-18 13:38:58 873d4e274b4988d260ba8354a9718324a1c26187a4ab4c1cc0227c03d0f10e70`。
两者均早于 [SQLite 3.51.3 WAL-reset 修复记录](https://www.sqlite.org/releaselog/3_51_3.html)，此修复不在当前二进制中；保留为独立依赖事项，本轮未升级依赖，也不把它假定为本次句柄所有权故障的原因。

---

## 附录 B — E2E 1–8 原始验收清单（此前只被引用，未落盘）

`[事实]` 本清单此前**只存在于需求方会话原文**，仓库内仅有三处 "E2E 1–8" 的**引用**（§7 及本文件上方两处），
无任何文件列出八项内容。此附录把原文补回，作为验收范围的权威来源。

`[事实]` 需求方先后给出**两个版本**，**仅 E2E7 不同**。本附录采用**后修版**，理由：
后修版的 E2E7 追加了删除腿，与已冻结的 F3 决策（选项二：删除即彻底删除，
`privacy deletion overrides historical citation availability`）及已实现代码一致；
沿用原始版会漏掉 `receipt removed` 与 `read_citation fails` 两条断言。

| # | 名称 | 步骤 | 通过判据 |
|---|---|---|---|
| E2E1 | PDF Tutor | upload pypdf-readable PDF → attach conversation → question → shared orchestrator → EvidencePack → Tutor response | Tutor 给出回答，且链路经过共享 orchestrator |
| E2E2 | Conversation Isolation | conversation A bind doc；conversation B 未绑定 → B query | B **取不到 A 的任何 evidence** |
| E2E3 | Initial Evidence Citation | Initial Retrieval → `seed_evidence` → `read_source` → citation | 拿到合法引用；**不允许先重复 `search_knowledge` 才取得引用权限** |
| E2E4 | Second Retrieval | initial evidence 故意不足 → Agent `search_knowledge` → read_source → final answer | 出现 `RetrievalHop AGENT_SEARCH`；`hop_count` 与 `second_retrieval_rate` 正确增加 |
| E2E5 | No Embedding | 真实 baseline：`sentence_transformers` 缺席 | FTS → reranker → expander → EvidencePack **仍完整可用** |
| E2E6 | No-text PDF | pypdf → 零可提取文字 → external recovery 不可用 | 落 `needs_ocr`；**不得 500** |
| E2E7 | Historical Receipt | retrieve → issue `CitationReceipt` → **disable** → new retrieval blocked → `read_citation` succeeds → **delete** → receipt removed → `read_citation` fails | 禁用后凭证仍可验；**删除后凭证移除且读取失败** |
| E2E8 | UNSET Scope | 绕过 WS 初始化直接调用 retrieval | **fail closed**；绝不 owner-wide 检索 |

### 原始版 E2E7（存档，不采用）

```
E2E 7 — disabled document
disable → new retrieval forbidden → valid prior citation receipt remains verifiable
```

`[判定]` 采用后修版。若下游已按原始版编写用例，需补齐 `delete → receipt removed → read_citation fails` 两条断言。
