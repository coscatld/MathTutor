# 003 附件：EvidencePack 字符预算与来源一致性（MT-RAG-004）

时间：2026-10-24 12:40（Asia/Shanghai）。审查基线：`4e713f9`，在现有工作区增量修改；未提交、推送或部署。

## 问题与复现证据

`build_evidence_pack()` 的普通片段分支只执行 `item.text[:2000]`，没有同时考虑整包剩余字符数。因此，7 个各 1900 字的片段输出 **13300 字**，超过声明的 12000 字上限，并且 `partial=False`。前 6 项累计 11999 字时，最后一个 50 字片段仍完整输出，总量为 **12049 字**。

另有三个最终投影不一致：

- `text_hash` 在裁剪前生成，裁剪后的 `text` 与哈希不匹配。
- 父题干分支舍弃过长邻居后，`neighbour_texts` 和 `expanded_from` 仍保留已舍弃内容及来源。这些结构字段也被后续上下文装配器使用。
- 被舍弃的片段曾经过扩展时，`execution.expansion_used` 仍可能为真，而最终 `coverage.expansion_used` 为假。

新增测试先在旧实现执行：**11 failed、4 passed**。失败包含实际 `ConversationRetrievalOrchestrator.retrieve_for_turn()` 返回 13300 字，以及 ContextExpander → EvidencePack 的邻居来源残留；不是只检查辅助函数是否存在。

## 实际调用链和实施边界

本轮追踪：会话资料有效 document IDs → `ConversationRetrievalOrchestrator.retrieve_for_turn(owner, document_ids, query)` → 检索内核 → rerank → `ContextExpander` → `_project()` → `build_evidence_pack()` → 对话资料上下文 / 知识工作流 `seed_evidence()` → `read_source()` 和引用凭证。

`ContextExpander` 已按 parent、matched、neighbours 拼接正文；扩展 IDs 对应 parent（如有）、neighbours，顺序稳定。本轮利用这一现有契约更新最终投影，没有另造检索入口或更改权限判断。

## 实际修改

1. 每项上限统一为 `min(MAX_PER_ITEM_CHARS, remaining)`；总量仍是 12000 **字符**，每项 2000 字符、最多 8 项。
2. 已存在的“父题干 + 匹配解答”完整组规则继续生效：组放不下就舍弃，不裁掉题干中的否定条件或只留下解答。随后仍可容纳后续普通项。
3. 父题干分支逐项保留完整邻居，并同步保留相应 ID；普通分支按照实际输出前缀同步裁剪 matched/neighbour 文本与来源，部分邻居只记录实际保留的前缀。
4. 最终 `text_hash` 总是重新计算为最终正文的 SHA-256；`source_id`、document/chunk 身份保持稳定。
5. 最终扩展状态从保留的来源计算，使 execution、coverage 和公开投影一致；已有 `truncated=True` 不被再次投影抹掉。空白候选不被误记为预算损失。
6. 对没有可核对结构的旧式合并文本，不猜测扩展来源偏移；继续输出有界正文，清除无法归属的扩展声明。

只修改以下文件：

- `src/mathtutor/domain/evidence.py`
- 新增 `tests/test_evidence_budget.py`
- 本附件

未修改 `retrieval_orchestrator.py`、`context_expansion.py`、检索权限、数据库结构或模型调用。最终预算校验集中在公共构建入口，使现有消费者都获得相同保证。

## 研究依据与适用条件

检索日期为本轮执行日；阅读了方法、实验设置、前缀基线和局限，不只使用摘要。

| 资料 | 状态、方法与限制 | 对本轮的作用 |
| --- | --- | --- |
| Li、Peng、Chen，*Efficiency vs. Verifiability in Evidence-Aware RAG: Does Prompt Compression Preserve Citation Grounding?*，2026-07-03，[ACL 正式 workshop 论文](https://aclanthology.org/2026.customnlp4u-1.19/)，[全文](https://aclanthology.org/2026.customnlp4u-1.19.pdf) | ASQA 948 题，固定 Self-RAG 7B、检索和解码；比较 LLMLingua-2、前缀裁剪与分层保留，同时评答案和引用。单基座、单数据集，分层方案仅轻度压缩。 | 引用保真需要独立验证；本文没有证明 MathTutor 中文数学教学收益。本轮不引入压缩模型。 |
| Mody，*The Attribution–Compression Frontier in Retrieval-Augmented Generation*，2026-09-13，[arXiv v1 全文](https://arxiv.org/html/2609.14245v1)，[出版状态](https://arxiv.org/abs/2609.14245) | 当前读取的是预印本；作者元数据声明 GroundLM 2026 workshop 接收。固定 Qwen2.5-7B，在 ASQA/QASPER 比较压缩及来源恢复；NLI 同时参与恢复与判分，未做人类校准，代码待发表后公开。 | 区分压缩正文与原始来源支持，检查真实输出长度；不采纳其自动判分比例作为产品收益。 |

针对实施方案的七项判断：

1. **解决什么问题**：预算裁剪后，交付的正文和可追溯元数据必须对应。
2. **关键假设**：片段来源可定位，扩展文本与来源顺序可核对，已知题干与解答属于一个完整组。
3. **MathTutor 是否成立**：现有 DocumentChunk、ContextExpander 和 owner/document scope 已提供这些条件；普通片段的语义完整性仍无法仅靠长度判定。
4. **是否已有能力**：已有上限常量、完整组规则和引用授权；缺陷位于最终投影，而非缺少新 RAG 框架。
5. **最小实现**：修正剩余字符扣减，同步正文、来源和哈希，不新增模型、服务或依赖。
6. **验收方式**：用确定性边界输入检查真实输出长度、哈希、原始来源 ID、完整题干条件和调用链；教育效果需另设固定题集及对照评测。
7. **成本和风险**：最多 8 项的字符串裁剪、拼接和哈希，无额外网络调用。没有测量 tokenizer token 数、费用或延迟变化，不将字符上限换称为 token/成本预算。

## 测试与真实结果

执行环境：macOS，`<USER_HOME>/miniconda3/envs/deeptutor/bin/python`，`PYTHONPATH=src`。未安装新依赖。

| 检查 | 结果 |
| --- | --- |
| 修复前首组 15 个针对性测试 | 11 failed、4 passed；确认 13300/12049 字越界及元数据错误 |
| 修复后首组 + 既有 retrieval orchestration | 52 passed，18 条既有 pytest asyncio 标记警告 |
| 补充边界后独立专项 | 20 passed，0.19 秒 |
| 最终相关 10 文件回归 | **150 passed、4 skipped、81 warnings，4.85 秒** |
| `git diff --check` | 通过 |

专项最终 20 例覆盖混合长度、7×1900、恰好 12000、剩余 1 字、8 项边界、空白候选、旧哈希、2000/2001 字完整组、父题干混排、跳过长邻居后保留短邻居、邻居部分保留/完全舍弃、最终扩展状态，以及实际 orchestrator/expander 调用链。

最终回归命令：

```sh
PYTHONPATH=src <USER_HOME>/miniconda3/envs/deeptutor/bin/python -m pytest \
  tests/test_evidence_budget.py \
  tests/test_retrieval_orchestration.py \
  tests/test_agentic_retrieval.py \
  tests/test_retrieval_safety.py \
  tests/test_conversation_reference_scope.py \
  tests/test_knowledge_workbench.py \
  tests/test_knowledge_safety.py \
  tests/test_retrieval_policy.py \
  tests/test_phase6_retrieval_metadata_first.py \
  tests/test_rag_production_benchmark.py \
  -q --tb=short --disable-warnings
```

相关用例覆盖 SQLite 可见性/跨用户拒绝、禁用文档、会话范围、已种入证据的 read_source 限制、错误引用拒绝及题干条件保留。新专项中的检索内核和邻域输入为确定性测试 fixture；调用生产 reranker/orchestrator/expander，并未调用外部 LLM。这些 fixture 不是学生效果数据。

4 项跳过均来自 `test_phase6_retrieval_metadata_first.py`，原因是 `/tmp/sqlite_vec_probe` 不存在专用 sqlite-vec 探测动态库；本轮没有将它们标为通过。未运行前端构建、桌面打包或 Windows/Linux；本轮未修改其代码。

## 遗留风险与下一轮候选

- 12000 字符只是 EvidencePack 的正文总量，不覆盖提示词模板、其他上下文、生成输出或 tokenizer 差异。
- 普通片段仍采用原有前缀裁剪策略，可能损失语义条件；本轮只保证有明确 parent 结构的题干与解答不被拆开。下一轮可用固定数学材料集评估普通片段关键条件保留率，再判断是否需要句子或结构级选取。
- 来源一致性和哈希一致性是工程保证，不等于引用所支持的数学结论正确，更不等于学习效果提升。
- 暂不引入学习式压缩或 NLI 验证器；重新评估条件是有代表性的中文数学证据集、源文支持人工标注及可接受的延迟/成本测量。
