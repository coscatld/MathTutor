# CURRENT STATE RAG AUDIT — Phase A

## 2026-09-20 最新离线增量：0.4.2

本轮没有真实Provider调用，预算及历史结果不变。独立版本的数学条件资料、来源含错组、原回答哈希绑定的两组AI审阅，以及保留原文/标记未完成的续写拼接修复均已落地；实际模型提示效果未重新测量，人工标签待确认，新包未构建。详见 [OFFLINE_MATH_REPAIR_042.md](OFFLINE_MATH_REPAIR_042.md) 和 `artifacts/offline-math-042/`。以下0.4.1及此前审计均为历史记录。

## 2026-09-20 最新增量：0.4.1

下文 2026-09-18 的只读审计及后续历史状态仍保留。当前真实回归不再是 BLOCKED_PROVIDER；最新结果以 `RAG_EVALUATION.md` 顶部为准。

原 24 条请求与 B packet 未改，已逐条关联调用链并完成 14 篇/57 声明的独立 AI 初审，参考仍 provisional、人工 PENDING。新诊断复现 DeepSeek 默认 reasoning 消耗短输出额度、Gateway 拒绝空正文；关闭 thinking 的单变量实测使原 14 题均正常交付。判别式原 TOKEN_LIMIT 来自两次512上限及2/2步骤，非总预算耗尽。

真实 Knowledge 组发现并顺序修复：seed 可读范围内部已登记、却未传给模型；quote 与 summary 契约未在模型 Schema 中明确。最终实际执行直接 read_source、summary support_check、按需 AGENT_SEARCH 与提示门控，未强迫重复搜索。证据见 `artifacts/delivery-regression-20260920/knowledge-final/`。

交付通过不代表数学通过：新表达组3题仍有数学正文错误，c=0退化题将含零的根对称作一正一负，另有续写接缝瑕疵。开发质量 FAIL、正式验收 INSUFFICIENT_EVIDENCE。累计75请求、保守293690 token，原未知usage不按零计费。

新版本工程实跑：后端全量1356 passed/11 skipped，定向86 passed（包含后加评测守卫），Web164 passed，Desktop44 passed/2 skipped。源码摘要另存；未重建安装包，不复用0.4.0包外验证作为0.4.1证据。

## 2026-09-18 原始只读审计

- 日期：2026-09-18
- 范围：MathTutor 现有检索/摄入/证据链的**只读**审计
- 方法：11 个子系统并行深读 + 15 个问题独立核验 + 高风险结论 3 票对抗反证；全部结论要求 `file:line`
- 证据规则：**不根据类名或函数名推断行为**。未读到函数体的结论标记 `NOT_VERIFIED`
- 本轮**未修改任何生产代码**

> 标注约定
> `[事实]` 直接读代码可验证 · `[推断]` 由多处事实推导 · `[建议]` 主观工程判断
> `IMPLEMENTED` · `PARTIAL` · `TEST_ONLY` · `INFRASTRUCTURE_ONLY` · `DEAD_CODE` · `DEPRECATED` · `DEFERRED` · `NOT_IMPLEMENTED`

---

## 0. 结论摘要

### 0.1 需求书前提的三处事实性错误

`[事实]` **错误一：RAG 不是缺失特性，而是已端到端接线的现存系统。**
`validate → store → parse → chunk → FTS → optional vector → 检索 → LLM prompt` 全链路在生产路径上。上传入口 [desktop_api.py:1361](../src/mathtutor/api/desktop_api.py#L1361) → [document_ingestion.py:177](../src/mathtutor/application/document_ingestion.py#L177) → [sqlite_documents.py:287](../src/mathtutor/repositories/sqlite_documents.py#L287) / [:436](../src/mathtutor/repositories/sqlite_documents.py#L436)。

`[事实]` **错误二：文件名叫 `retrieval_router` / `lexical_reranker` 的模块恰恰是唯一没接线的那部分。**
`MetadataFirstRetriever`、`LexicalScoreReranker`、`SqliteVecVectorIndex` 在 `src/mathtutor/api`、`src/mathtutor/application`（服务层）、`src/mathtutor/repositories` 下**零引用**；唯二调用者是 `scripts/math_tutor_rc_benchmark.py:124` 与 `tests/`。

`[事实]` **错误三：OCR 不是"未按规范实现"，而是根本不存在。**
仓库内无任何 OCR 引擎（`tesseract|pytesseract|paddleocr|easyocr|rapidocr|surya|ocr_engine|run_ocr` 全零命中）。声明依赖仅 `pymupdf>=1.24`、`pypdf>=4.0`（[pyproject.toml:19-20](../pyproject.toml#L19-L20)）。

### 0.2 对设计前提的修订结论

`[事实]` 真实生产文档检索路径（下称 **production retrieval kernel**）：

```
knowledge.search                        knowledge.py:384-416
ChatDocumentContext.build               chat_documents.py:21-72
UserDocumentsSourceProvider.retrieve    context_assembler.py:425-475
        │
        └──► DocumentIndexManager.search            document_ingestion.py:494-538
                 │
                 └──► repo.search_chunks            sqlite_knowledge.py:235-258
                          │
                          └──► search_document_chunks   sqlite_documents.py:436-574
                                   ├─ doc_where 元数据预过滤    :461-470
                                   ├─ FTS5 bm25 候选          :577-605
                                   └─ optional cosine 融合     :539-555
```

`[事实]` **三条消费路径已共享同一个 kernel**：装配点 [product_state.py:390-393](../src/mathtutor/api/product_state.py#L390-L393)，分别注入 [knowledge.py:398](../src/mathtutor/application/knowledge.py#L398)、[product_state.py:426-429](../src/mathtutor/api/product_state.py#L426-L429)、[product_state.py:660-662](../src/mathtutor/api/product_state.py#L660-L662)。

`[建议]` 因此 **Route 2（Production-path consolidation）成立**，无需建立第三套检索体系。

### 0.3 四项反证条件核验结果

| # | 反证条件 | 结果 | 依据 |
|---|---|---|---|
| 1 | `DocumentIndexManager.search` 非真生产路径 | **不成立** | 三条生产调用链，见 §4.1 |
| 2 | metadata-first SQL 存在权限漏洞 | **不成立** | 过滤先于评分，见 Q15 |
| 3 | 无法承载 reranker / EvidencePack / context expansion | **不成立** | `RetrievedChunk` 字段已齐备，见 §4.3 |
| 4 | 存在关键链路依赖 `MetadataFirstRetriever` | **不成立** | `src/` 零引用 |

`[事实]` 全部 5 项高风险问题（Q6/Q7/Q9/Q14/Q15）经 3 票对抗复核，**反证票数 0/3**。

---

## 1. CURRENT STATE REPORT — 15 问逐条

### Q1 文档上传从 API 到数据库完整调用链

`[事实]` 全仓共 **4 个接受文件字节的 HTTP 端点**，3 个进入摄入管线（另见 §6.8 D19/D20）：

| 端点 | 位置 | 去向 |
|---|---|---|
| `POST /desktop/documents/import` | [desktop_api.py:1361-1381](../src/mathtutor/api/desktop_api.py#L1361-L1381) | `_ingest` → ingest |
| `POST /desktop/documents/pick` | [desktop_api.py:1384-1405](../src/mathtutor/api/desktop_api.py#L1384-L1405) | 原生选择器 → 同一 `_ingest` |
| `POST /knowledge/libraries/{sid}/imports` | [knowledge_api.py:134-151](../src/mathtutor/api/knowledge_api.py#L134-L151) | `state.documents.ingest` → `knowledge.attach` |
| `POST /images` | [image_api.py:19-27](../src/mathtutor/api/image_api.py#L19-L27) | 独立图片链，非文档 |

`[事实]` 完整链：

```
desktop_api.py:1361 import_document
 → :1368 file.read()
 → :1369-1373 大小守卫             (MAX_DOCUMENT_BYTES)
 → :1374-1379 PickedFile
 → :1380 _validate_or_422
 → :1381 _ingest
 → :1268-1272 require_active → state.documents.ingest → conversations.attach_document
 → document_ingestion.py:179 validate_import   (扩展名 → 大小 → MIME)
 → :180-184 sha256 + find_by_content_hash 去重
 → :186-189 sanitize_filename → ref_for → store_bytes
 → :191-201 UserDocument(status="importing") → add_document
 → :207-209 status="parsing"
 → :210 → :309-319 → LocalDocumentParser.parse
 → :211 → :321-363 TextChunker.chunk → DocumentChunk + build_fts_text
 → :212 → :270-294 replace_chunks → update_document(最终状态)
 → :228 → :296-307 _maybe_build_index   (best-effort，吞掉 EmbeddingUnavailableError)
```

`[事实]` 状态机：`importing → parsing → ready | ready_with_warnings | needs_ocr | failed`（[document_ingestion.py:68-109](../src/mathtutor/application/document_ingestion.py#L68-L109)）。`DocumentStatus` 中的 `"deleted"` 字面量**从未被赋值**，删除一律走 `deleted_at`。

`[事实]` **摄入不可由模型触发**：`knowledge_tools.py:83-84` 的 7 个工具中没有 ingest；`.ingest(` 仅出现在两个 API 路由。

`[事实]` **旁路文档写入**：`save_markdown`（[knowledge.py:244-338](../src/mathtutor/application/knowledge.py#L244-L338)）直接写 `user_documents` + `document_chunks`，用**自己的一套 chunker**（`markdown_chunks`），不经过 parser、不做 index build。可达路径：HTTP `POST /libraries/{sid}/notes`（[knowledge_api.py:122-131](../src/mathtutor/api/knowledge_api.py#L122-L131)）与模型工具 `save_note`（[knowledge_tools.py:205-218](../src/mathtutor/application/knowledge_tools.py#L205-L218)）。

### Q2 PDF 如何解析 / 是否存在 OCR

`[事实]` 唯一生产 parser 是 `LocalDocumentParser`，默认构造于 [document_ingestion.py:173](../src/mathtutor/application/document_ingestion.py#L173)。

**决策树**（[document_parser.py:87-149](../src/mathtutor/infrastructure/document_parser.py#L87-L149)）：

```
parse()
 ├─ 扩展名 ∈ {.txt,.md,.markdown,.tex,.pdf}   否则 ValueError
 ├─ .pdf → _parse_pdf
 │   ├─ try import fitz (PyMuPDF)
 │   │    └─ ImportError → _parse_pdf_pypdf 并 return   ← MinerU 在此分支永不尝试
 │   ├─ PyMuPDF 抽取 (逐页表格 → 文本块 → 图片)
 │   └─ extractable_chars > 0 → 返回
 │       else → try_mineru_parse          (:134)
 │            └─ 失败/缺失 → 返回空 stats
 └─ 其它 → _parse_text (UTF-8)
```

`[事实]` PyMuPDF 路径实际做的工作（[document_parser.py:169-259](../src/mathtutor/infrastructure/document_parser.py#L169-L259)）：`page.find_tables()` 表格转管道行、`page.get_text("dict")` 文本块（跳过 bbox 中心落在表格矩形内的块）、按字号与页中位数分类 heading/formula/paragraph、`page.get_images()` 抽图（<40×40px 丢弃）。

`[事实]` **OCR：全仓不存在。**
- 零 OCR 引擎标识符（全仓 grep 无命中）
- `ocr_text` 字段存在（[documents.py:100](../src/mathtutor/domain/documents.py#L100)）并透传到 chunk metadata（[chunking.py:438-449](../src/mathtutor/infrastructure/chunking.py#L438-L449)），但**唯一写入者是 MinerU 分支**（[parse_adapters.py:84,104](../src/mathtutor/infrastructure/parse_adapters.py#L84)）
- MinerU 是外部 CLI shell-out（`subprocess.run(["mineru",...], timeout=90)`，[parse_adapters.py:65-70](../src/mathtutor/infrastructure/parse_adapters.py#L65-L70)），**不是声明依赖**，正常安装下立即返回 `None`
- 该路径下 `ocr_text` 只进 `metadata_json`，**不进 `chunk.text`、不进 `fts_text`**（[lexical.py:55-91](../src/mathtutor/infrastructure/lexical.py#L55-L91) 只消费 text/heading_path/latex），故不可独立检索

`[事实]` `DoclingAdapter` / `LlamaParseAdapter` 是抛异常的桩（[parse_adapters.py:126-157](../src/mathtutor/infrastructure/parse_adapters.py#L126-L157)），无人 import。

`[事实]` **无逐页分类**：仅有聚合 `empty_pages` 与文档级 `parse_mode`（text_layer / mixed / empty，[document_parser.py:390-421](../src/mathtutor/infrastructure/document_parser.py#L390-L421)）。不存在 `Page 1=TEXT / Page 3=SCAN` 这类结构。

### Q3 chunk 如何生成

`[事实]` 生产中有**两个互不相干的 chunker**：

| chunker | 位置 | 版本 | 结构感知 |
|---|---|---|---|
| `TextChunker` | [chunking.py:86](../src/mathtutor/infrastructure/chunking.py#L86) | `mt-chunker-v2` | **是** |
| `KnowledgeService.markdown_chunks` | [knowledge.py:226-242](../src/mathtutor/application/knowledge.py#L226-L242) | `knowledge_offsets_v1` | 否（固定 1200 字符窗口） |

`[事实]` `TextChunker` 算法：中文标记正则 `_LINE_ROLE`（[chunking.py:37-51](../src/mathtutor/infrastructure/chunking.py#L37-L51)）识别 `例n / 解： / 证明： / 定义 / 定理 / 引理 / 推论 / 命题 / 习题`；`_group_units`（[:337-419](../src/mathtutor/infrastructure/chunking.py#L337-L419)）状态机分组：标题刷新区块路径、例题吞并后续、`解：`作为子组挂到例题、公式/表格/图并入当前组；仅在超过 `max_chunk_chars=1000` 时按句切分并保留 ~100 字符重叠（[:184-231](../src/mathtutor/infrastructure/chunking.py#L184-L231)）。

`[事实]` 持久化字段（`DocumentChunk`，[documents.py:171-196](../src/mathtutor/domain/documents.py#L171-L196)）：`chunk_id / document_id / student_id / sequence / page / section / text / content_hash / chunk_type / heading_path / page_start / page_end / parent_chunk_id / metadata_json / chunker_version / fts_text`。

`[事实]` SQL 列（[schema.py:575-590](../src/mathtutor/infrastructure/schema.py#L575-L590)）**不含** `heading_path`、`page_start/end`、`parent_chunk_id`、`chunk_type` —— 它们只存在于 `metadata_json`，由 `_chunk_from_row`（[sqlite_documents.py:102-126](../src/mathtutor/repositories/sqlite_documents.py#L102-L126)）反序列化。**因此 SQL 层无法 join 层级**。

`[事实]` 层级：**仅单级 `parent_chunk_id`**（solution → 该 example 组首个 draft），无祖父/多级树。`heading_path` 是扁平元组。

`[事实]` **`prev`/`next` 全仓不存在**（grep `prev_chunk|next_chunk|prev_index|next_index|prev_chunk_id|next_chunk_id` 零命中）。顺序只靠整数 `sequence`（`UNIQUE(document_id, sequence)`，[schema.py:581,589](../src/mathtutor/infrastructure/schema.py#L581)）。

### Q4 FTS 如何建立

`[事实]` 表 `document_chunks_fts`，FTS5 虚拟表，DDL 在两处（[document_fts.py:16-24](../src/mathtutor/infrastructure/document_fts.py#L16-L24) 与 [008_document_chunk_fts.py:21-29](../src/mathtutor/infrastructure/migrations/versions/008_document_chunk_fts.py#L21-L29)）。索引列仅 `fts_text`；`chunk_id/student_id/document_id` 为 `UNINDEXED`。

`[事实]` 分词器 `unicode61`，但 **CJK bigram 是在 Python 侧预切好再存进去的**（[lexical.py:80-82,127-144](../src/mathtutor/infrastructure/lexical.py#L127-L144)），`unicode61` 实际只做空格切分。`fts_text` 还折入了 skill/concept 别名（[lexical.py:88-90](../src/mathtutor/infrastructure/lexical.py#L88-L90) → [retrieval_query.py:53-71](../src/mathtutor/application/retrieval_query.py#L53-L71)），使「解方程」能命中只写「一元一次方程」的块。

`[事实]` **无触发器**（全仓 `CREATE TRIGGER` 零命中）。填充方式是**全表重建**：每次 `replace_document_chunks` 都调 `sync_document_chunks_fts`（[sqlite_documents.py:314](../src/mathtutor/repositories/sqlite_documents.py#L314) → [document_fts.py:36-51](../src/mathtutor/infrastructure/document_fts.py#L36-L51)）执行 `delete-all` + 全量 `INSERT ... SELECT`。即**每次写一个文档都重建整张 FTS 表**。

`[事实]` 唯一查询点 `_fts_candidate_ids`（[sqlite_documents.py:577-605](../src/mathtutor/repositories/sqlite_documents.py#L577-L605)）：

```sql
SELECT chunk_id, bm25(document_chunks_fts) FROM document_chunks_fts
WHERE student_id = :sid AND document_id IN :doc_ids AND document_chunks_fts MATCH :match
```

`[事实]` **关键门控**：该 MATCH 仅在 `vector is None` 时执行（[sqlite_documents.py:479](../src/mathtutor/repositories/sqlite_documents.py#L479)）。因为 embedding 默认关闭（[embedding_config.py:39](../src/mathtutor/infrastructure/embedding_config.py#L39) `"enabled": False`），**FTS 是默认生产词法召回器**；一旦用户启用 embedding，FTS 被绕过，改为对可见 chunk 全表扫描做余弦融合。

`[事实]` bm25 经 `fts_rank_component = 1/(1+exp(bm25))`（[lexical.py:122-124](../src/mathtutor/infrastructure/lexical.py#L122-L124)）以 `FTS_FUSION_WEIGHT = 0.5` 并入总分（[sqlite_documents.py:550-555](../src/mathtutor/repositories/sqlite_documents.py#L550-L555)）。

### Q5 embedding 何时建立

`[事实]` **仅在写入侧**，四个触发点：[document_ingestion.py:228](../src/mathtutor/application/document_ingestion.py#L228)（import）、[:265](../src/mathtutor/application/document_ingestion.py#L265)（reparse）、[knowledge_api.py:146](../src/mathtutor/api/knowledge_api.py#L146)（library import，复用 ingest）、[data_lifecycle.py:629](../src/mathtutor/application/data_lifecycle.py#L629)（显式 force rebuild）。检索时只调 `embed_query`，绝不 build。

`[事实]` 门控 `_maybe_build_index`（[:296-307](../src/mathtutor/application/document_ingestion.py#L296-L307)）：`needs_ocr`/`failed`/零 chunk 文档永不 embedding（`can_enable_retrieval()`，[documents.py:151-157](../src/mathtutor/domain/documents.py#L151-L157)）；`EmbeddingUnavailableError` 被吞。

`[事实]` 后端：`EmbeddingRuntime` 默认无 backend（[embedding_runtime.py:267-279](../src/mathtutor/infrastructure/embedding_runtime.py#L267-L279)），生产单例 [product_state.py:226](../src/mathtutor/api/product_state.py#L226)。唯一选择器 `EmbeddingConfigService`（[embedding_config.py:138-159](../src/mathtutor/infrastructure/embedding_config.py#L138-L159)）。`FakeEmbeddingBackend` **不被产品配置选中**。

`[事实]` 索引签名 `IndexBuildRecord`（[documents.py:225-247](../src/mathtutor/domain/documents.py#L225-L247)）：`index_version / embedding_backend_id / embedding_model_id / embedding_model_version / embedding_dimension / chunker_version / parser_version / built_at`。

`[事实]` **缺陷**：`EmbeddingDescriptor.index_signature()`（[embedding.py:54-64](../src/mathtutor/domain/embedding.py#L54-L64)）在 `src/` 下零调用点；`matches_signature` **不含 `normalization` 与 `runtime_version`**（[documents.py:249-263](../src/mathtutor/domain/documents.py#L249-L263)）。归一化策略变更不会触发重建。

### Q6 vector retrieval 是否进入 production path

`[事实]` **是，但为条件性（opt-in）。**

- **不是** `sqlite-vec` ANN，**不是** `MetadataFirstRetriever`
- **是** 生产 SQLite 仓库内的朴素 Python 余弦扫描 + 词法/FTS 融合：[document_ingestion.py:494-538](../src/mathtutor/application/document_ingestion.py#L494-L538) → [sqlite_documents.py:511-565](../src/mathtutor/repositories/sqlite_documents.py#L511-L565)

三条生产调用链均已验证：chat（[chat_documents.py:45](../src/mathtutor/application/chat_documents.py#L45)）、structured hint（[context_assembler.py:439](../src/mathtutor/application/context_assembler.py#L439)）、knowledge QA（[knowledge.py:398](../src/mathtutor/application/knowledge.py#L398)）。

条件：默认 `EmbeddingRuntime()` 无 backend（[product_state.py:226](../src/mathtutor/api/product_state.py#L226)），须用户显式 `PUT /settings/embedding` 启用；且向量须先 build 过。

### Q7 reranker 是否进入 production path

`[事实]` **分裂结论。**

**专用 Reranker 组件：NOT_WIRED。** 全仓唯一 `.rerank(` 调用点是 [retrieval_router.py:222](../src/mathtutor/application/retrieval_router.py#L222)（在 `MetadataFirstRetriever.retrieve` 内）。`LexicalScoreReranker` 唯一非测试构造处是 [scripts/math_tutor_rc_benchmark.py:124](../scripts/math_tutor_rc_benchmark.py#L124)。

**但生产检索确实存在内联重排，且不使用 Reranker 协议：**
- `KnowledgeService.search` 内联加分（[knowledge.py:410](../src/mathtutor/application/knowledge.py#L410)）：
  ```python
  score = hit.score + int(query.casefold() in hit.chunk.text.casefold()) + .25 * int(query in hit.chunk.section)
  ```
  注释自称 "Transparent local rerank"（[:408](../src/mathtutor/application/knowledge.py#L408)）。**IN_PRODUCTION_PATH**
- 仓库层融合排序：[sqlite_documents.py:552-566](../src/mathtutor/repositories/sqlite_documents.py#L552-L566)
- 装配层按最大 chunk 分重排文档：[context_assembler.py:464-466](../src/mathtutor/application/context_assembler.py#L464-L466)

`[事实]` 结果是**两套并行打分机制、无共享契约**：`lexical_score + 0.5·vector + 0.5·bm25` 与 `+1.0 精确 query + 0.25 section`。`.25` 与 `1.0` 两个魔数无任何测试钉住。

### Q8 conversation 与 document 的绑定关系

`[事实]` 存在**三套并存的绑定机制**：

| 机制 | 表 | 写入点 | 语义 |
|---|---|---|---|
| 会话绑文档（legacy） | `conversation_documents` | [desktop_api.py:1272](../src/mathtutor/api/desktop_api.py#L1272)、[:1468](../src/mathtutor/api/desktop_api.py#L1468) | 一对多，一份文档可绑多个会话 |
| 知识空间成员 | `knowledge_members` | [knowledge.py:144](../src/mathtutor/application/knowledge.py#L144) | 文档 ↔ 空间（personal / course / session） |
| 会话挂载配置 | `knowledge_bindings.payload` | [knowledge.py:133-134](../src/mathtutor/application/knowledge.py#L133-L134) | 每会话一行 JSON：`space_ids / only_selected / document_ids / mode / save_space_id / tool_mode / hints_only` |

`[事实]` `scope()` 把三者**取并集**（见 Q9）。会话型空间受 `spaces.conversation_id == cid` 约束（[knowledge.py:164](../src/mathtutor/application/knowledge.py#L164)），personal/course 空间对所有会话生效。

`[事实]` **删除文档不清 `conversation_documents`**：[data_lifecycle.py:466-498](../src/mathtutor/application/data_lifecycle.py#L466-L498) 只做 `user_documents` 软删 + storage 移除，全仓无 `conversation_documents` 的 delete。判定 **`DEAD_CODE`（清理逻辑缺失）**。

### Q9 scope() 如何计算

`[事实]` [knowledge.py:153-170](../src/mathtutor/application/knowledge.py#L153-L170)，纯 id 集合计算，**不做评分、不做状态过滤**：

```
1. require_conversation(owner, cid)          :154  → 会话不存在/已 trash/purge 则抛
2. config = configuration or 读 bindings      :155
3. ids = legacy  ∪  globals_  ∪  mounted      :156-166
     legacy   = conversation_documents
     globals_ = owner 的全部 is_global 文档
     mounted  = members ⋈ spaces（未删、enabled、space_id ∈ config.space_ids、
                (kind != 'session' OR conversation_id == cid)）
4. if config["only_selected"]:
       ids = [x for x in ids if str(x) in config["document_ids"]]   :167-168
5. return ids                                 :170
```

`[事实]` **三者之间无优先级**，是纯并集；唯一的"优先级"是最后施加的 `only_selected` 交集，它**同时也能剔除 legacy 与 global 文档**。

`[事实]` `scope()` 故意宽松（注释 [:169](../src/mathtutor/application/knowledge.py#L169)："Repository repeats owner/status/disabled checks before scoring"）。真正过滤在 SQL 层：

- [sqlite_documents.py:461-470](../src/mathtutor/repositories/sqlite_documents.py#L461-L470) 的 `doc_where` = `student_id` + `retrieval_enabled==1` + `deleted_at IS NULL` + `status IN RETRIEVABLE` + （若传）`document_id IN scope`
- FTS 候选同样受限（[:480-481](../src/mathtutor/repositories/sqlite_documents.py#L480-L481)、[:587-596](../src/mathtutor/repositories/sqlite_documents.py#L587-L596)）
- 融合评分只在此后的 Python 循环中进行（[:531-566](../src/mathtutor/repositories/sqlite_documents.py#L531-L566)）

`[事实]` 空 scope 在进入仓库前短路：[context_assembler.py:436-438](../src/mathtutor/application/context_assembler.py#L436-L438)、[chat_documents.py:22-24](../src/mathtutor/application/chat_documents.py#L22-L24)。

`[事实]` **唯一的 scope 写入者**是 WebSocket 回合处理器 [math_tutor_ws.py:307-312](../src/mathtutor/api/math_tutor_ws.py#L307-L312)。

`[事实]` **`state.knowledge is None` 时存在第二套公式**（[math_tutor_ws.py:310-311](../src/mathtutor/api/math_tutor_ws.py#L310-L311)：`conversations.document_ids + is_global`），而非 fail closed。

### Q10 search_knowledge 具体调用哪个 retriever

`[事实]` 完整链：

```
knowledge_tools.py:147  executor._dispatch("search_knowledge")
 → knowledge.py:384-416   KnowledgeService.search
     ├─ :387 ids = await self.scope(owner, cid)
     ├─ :390-396 若 runtime 是 FakeEmbeddingBackend → document_repository.search_chunks（显式拒绝假后端）
     └─ :398 否则 → state.document_index.search
 → document_ingestion.py:494-538  DocumentIndexManager.search
     ├─ :508 tokens = tokenize_lexical(query)
     ├─ :513-528 status.available ? embed_query + validate_vector : vector=None
     └─ :529-538 repo.search_chunks(..., document_ids=document_ids, vector=vector, ...)
 → sqlite_knowledge.py:235-258 → sqlite_documents.py:436-574
```

`[事实]` 候选生成两条路：`vector is None` 时走 FTS5 MATCH（[:479-491](../src/mathtutor/repositories/sqlite_documents.py#L479-L491)），否则对可见 chunk 全扫描（[:509-529](../src/mathtutor/repositories/sqlite_documents.py#L509-L529)）。

`[事实]` **FTS 不可用时不静默降级为 LIKE** 只在"FTS 从未调用成功"时发生；若 FTS 调用成功但零命中，直接返回空结果而非回退 LIKE（[:499-508](../src/mathtutor/repositories/sqlite_documents.py#L499-L508)）。

`[事实]` `knowledge.py:392-396` 显式检测并**拒绝** `FakeEmbeddingBackend` 进入产品检索路径。

### Q11 read_source 如何限定可读区间

`[事实]` [knowledge.py:370-382](../src/mathtutor/application/knowledge.py#L370-L382)，四道限定：

```python
allowed = await self.scope(owner, cid)                      # ① 会话 scope
doc = await self.state.documents.get_document(owner, UUID(did))
if UUID(did) not in allowed or not doc or not doc.is_retrievable():
    raise KnowledgeError("引用不在当前已启用的资料范围内。")     # ② 在 scope 内 + 当前可检索
row = await self.snapshot(owner, did, version)
if start < 0 or end <= start or end > len(row["body"]) or end - start > 6000:
    raise KnowledgeError("引用区间无效或超过 6000 字。")        # ③ 区间合法 + ≤6000 字符
return {... "body_hash": row["body_hash"], "text": row["body"][start:end], ...}
```

`[事实]` 工具层再套一层：`read_source` 只能读 `search_hits` 里记过的四元组（[knowledge_tools.py:152-155](../src/mathtutor/application/knowledge_tools.py#L152-L155)），猜 ID/区间直接 `REJECTED`。

`[事实]` **副作用（缺陷）**：`doc.is_retrievable()` 要求的是**当前**文档状态，因此停用/删除一份文档会让**已发出的合法引用变得不可读**，尽管不可变 version 仍然存在。

### Q12 body_hash / version / provenance

`[事实]` `body_hash = sha256(body)`（[knowledge.py:34,252](../src/mathtutor/application/knowledge.py#L252)），hash 对象是**整份正文的 UTF-8 字节**，`body` 来源于：

- markdown 笔记：用户提交的原文（[knowledge.py:252](../src/mathtutor/application/knowledge.py#L252)）
- 抽取型文档：`"\n".join(c.text for c in chunks)`（[knowledge.py:355](../src/mathtutor/application/knowledge.py#L355)）—— 即**重建拼接**，不是原始文件字节

`[事实]` **缺陷**：抽取型文档的 `provenance.source_hash` 是 `doc.content_hash`（**原始导入字节**的哈希），而 `body_hash` 是重建拼接的哈希。二者不同源；若 chunk 在 body 未变的情况下发生变化，两者会失配。

`[事实]` `versions` 行内容（[knowledge.py:317-320](../src/mathtutor/application/knowledge.py#L317-L320)）：`student_id / document_id / version / body / body_hash / title / tags / links / provenance / created_at`。`provenance` 含 `format`（`markdown` | `extracted`）与自定义字段。

`[事实]` `snapshot` 惰性合成：无常量行时，从当前 chunks 拼 body 并写一条版本（[knowledge.py:351-368](../src/mathtutor/application/knowledge.py#L351-L368)）。**缺陷**：请求 `version=1` 而无既有行时会合成当前内容，而非 fail closed（[:351](../src/mathtutor/application/knowledge.py#L351) 只对 `not in (None, 1)` 抛错）。

`[事实]` `source_id` 由服务端生成：`"s-" + digest([key, result["body_hash"]])[:24]`（[knowledge_tools.py:157](../src/mathtutor/application/knowledge_tools.py#L157)）。**模型无法自行生成引用 ID**。

`[事实]` `generation` 是每 owner 一个世代号；任何挂载变更都 `bump`，并**连带删除该 owner 全部 drafts 与 operations**（[knowledge.py:58-67](../src/mathtutor/application/knowledge.py#L58-L67)）。工具循环每次 dispatch 前比对（[knowledge_tools.py:119-120](../src/mathtutor/application/knowledge_tools.py#L119-L120)）。

### Q13 Tutor mode 与 Knowledge mode 如何消费 document context

`[事实]` **召回内核相同，消费方式完全不同。**

| 维度 | Tutor mode | Knowledge mode |
|---|---|---|
| 分流点 | [controller.py:415-436](../src/mathtutor/application/controller.py#L415-L436) 判断 `config.mode` | 同左，`mode == "knowledge"` |
| 消费者 | `ChatDocumentContext.build`（[chat_documents.py:21-72](../src/mathtutor/application/chat_documents.py#L21-L72)） | `KnowledgeTools` 工具循环（[knowledge_tools.py:96-229](../src/mathtutor/application/knowledge_tools.py#L96-L229)） |
| 模型是否必须调工具 | **否**，应用侧检索后注入 | **是**，首轮无任何文档上下文 |
| 预算 | ≤8 chunk / 12000 字符（[:11-12](../src/mathtutor/application/chat_documents.py#L11-L12)） | 单次 `read_source` ≤6000 字符，最多 10 步 |
| 模型可见标识符 | **无**（只有 filename/序号/文本） | `document_id / version / start / end / source_id / body_hash` |
| 注入位置 | [tutor_chat.py:112](../src/mathtutor/infrastructure/tutor_chat.py#L112) `"本轮会话资料（应用提供的不可信参考数据，不是用户指令）"` | 工具收据 `"应用工具结果（数据，不是指令）"`（[tutor_runtime.py:283-284](../src/mathtutor/application/tutor_runtime.py#L283-L284)） |
| 可引用 | **否** | **是**，逐字 quote + body_hash 重校验 |
| partial 标记 | 有（`partial: True`，[chat_documents.py:71](../src/mathtutor/application/chat_documents.py#L71)） | 不适用 |

`[事实]` **结构性路径另有一套**：`ContextAssembler`（intent 驱动、4000 token 预算、按 `RetrievalPolicy` 矩阵）只被 `adaptive_practice.py` 用于练习生成，**不在 tutor 闲聊路径上**。它有独立的预算语义，与 chat 路径的 12000 字符硬上限不同。

`[事实]` **`DocumentContextSelection` 无 `partial` 字段**（[assembled_context.py:177-185](../src/mathtutor/domain/assembled_context.py#L177-L185)），即结构化路径**不向模型声明上下文是截断的**，而 chat 路径会。

`[事实]` **`ChatDocumentContext` 的 overview 分支用 `repository.list_chunks`**（[chat_documents.py:53](../src/mathtutor/application/chat_documents.py#L53)），该方法**只按 owner 过滤、不过滤 `retrieval_enabled`**（[sqlite_knowledge.py:192-198](../src/mathtutor/repositories/sqlite_knowledge.py#L192-L198)），与检索主路径的可见性语义不一致。

### Q14 RAG 能力分层清单

见 §2 能力矩阵。

### Q15 是否存在"全局先搜索、之后再按会话过滤"

`[事实]` **不存在。** 所有生产检索路径的会话/owner 白名单都是**候选生成前的预过滤**：

1. SQLite：`doc_where` 先于 `permitted_ids` 与 FTS MATCH（[sqlite_documents.py:461-475](../src/mathtutor/repositories/sqlite_documents.py#L461-L475)），chunk JOIN 的是已过滤的 `visible` 子查询（[:471-486](../src/mathtutor/repositories/sqlite_documents.py#L471-L486)）
2. 内存版：`wanted` 集合在任何 chunk 迭代前生效（[document_repository.py:292-305](../src/mathtutor/repositories/document_repository.py#L292-L305)）
3. 装配路径：[context_assembler.py:434-444](../src/mathtutor/application/context_assembler.py#L434-L444)
4. Chat 路径：[chat_documents.py:22-45](../src/mathtutor/application/chat_documents.py#L22-L45)
5. Knowledge 路径：[knowledge.py:384-398](../src/mathtutor/application/knowledge.py#L384-L398)

`[事实]` 唯一真实的"先取 owner 全域、再按会话过滤"的代码是**元数据列表端点** `GET /documents`（[desktop_api.py:1284-1290](../src/mathtutor/api/desktop_api.py#L1284-L1290)），它不排序、不截断、不含 chunk 文本，不是检索路径。

`[事实]` **真正的风险是反向的（latent）**：`current_document_scope()` 默认 `None`（[conversation_scope.py:7](../src/mathtutor/application/conversation_scope.py#L7)），而 `None` 在 [context_assembler.py:436-444](../src/mathtutor/application/context_assembler.py#L436-L444) 与 [sqlite_documents.py:467](../src/mathtutor/repositories/sqlite_documents.py#L467)（`if document_ids is not None`）被解释为**不做文档过滤 = owner 全域检索**。当前所有生产入口都被 `math_tutor_ws.py:312` 设过 scope，**暂不可达**；但任何未来在 WS 回合之外调用 `ContextAssembler.assemble` 的代码都会静默跨会话检索。

---

## 2. 能力分类矩阵

### 2.1 IMPLEMENTED — 在生产路径且已验证

| 能力 | 位置 |
|---|---|
| 文件校验（扩展名→大小→MIME） | [document_ingestion.py:112-133](../src/mathtutor/application/document_ingestion.py#L112-L133) |
| 内容哈希去重（owner + bytes） | [:180-184](../src/mathtutor/application/document_ingestion.py#L180-L184) |
| 受控存储（临时文件 + 原子替换 + 越界检查） | [document_storage.py:90-109](../src/mathtutor/infrastructure/document_storage.py#L90-L109) |
| PDF 文本层抽取（PyMuPDF，含表格/图片/标题分类） | [document_parser.py:169-259](../src/mathtutor/infrastructure/document_parser.py#L169-L259) |
| pypdf 回退（仅文字） | [:261-289](../src/mathtutor/infrastructure/document_parser.py#L261-L289) |
| 结构感知切片（中文 role 识别 + 父子） | [chunking.py:337-419](../src/mathtutor/infrastructure/chunking.py#L337-L419) |
| FTS5 索引 + CJK bigram 预切 + 别名扩充 | [lexical.py:55-119](../src/mathtutor/infrastructure/lexical.py#L55-L119) |
| 元数据优先过滤（SQL 级，先于评分） | [sqlite_documents.py:461-475](../src/mathtutor/repositories/sqlite_documents.py#L461-L475) |
| 词法 + 向量 + bm25 融合排序 | [:550-566](../src/mathtutor/repositories/sqlite_documents.py#L550-L566) |
| embedding 不可用 → 纯词法降级 | [document_ingestion.py:527-528](../src/mathtutor/application/document_ingestion.py#L527-L528) |
| 可选 embedding（本地 ST / OpenAI 兼容） | [embedding_config.py:138-182](../src/mathtutor/infrastructure/embedding_config.py#L138-L182) |
| 索引签名 + 重建（不重新导入原件） | [document_ingestion.py:437-492](../src/mathtutor/application/document_ingestion.py#L437-L492) |
| 会话 scope 三源并集 + only_selected | [knowledge.py:153-170](../src/mathtutor/application/knowledge.py#L153-L170) |
| 不可变版本 + body_hash + provenance | [knowledge.py:340-382](../src/mathtutor/application/knowledge.py#L340-L382) |
| 工具循环 + call_id 幂等 + 步数/token 上限 | [tutor_runtime.py:166-319](../src/mathtutor/application/tutor_runtime.py#L166-L319) |
| 逐字引用校验 + 蕴含检查 | [knowledge_tools.py:231-250](../src/mathtutor/application/knowledge_tools.py#L231-L250) |
| generation 世代号（撤销即失效） | [knowledge.py:58-67](../src/mathtutor/application/knowledge.py#L58-L67) |
| 数据生命周期（软删 + 派生索引重建） | [data_lifecycle.py:466-645](../src/mathtutor/application/data_lifecycle.py#L466-L645) |

### 2.2 PARTIAL

| 能力 | 已有 | 缺失 |
|---|---|---|
| PDF 分类 | 文档级 `parse_mode` = text_layer/mixed/empty（[document_parser.py:390-421](../src/mathtutor/infrastructure/document_parser.py#L390-L421)） | **无逐页分类**，无 `TEXT_PDF/SCAN_PDF/MIXED_PDF/ENCRYPTED/CORRUPTED` 枚举 |
| 上下文扩展 | 单级 `parent_chunk_id` + `heading_path` | 无 prev/next，无多级 section 树，无 token 预算扩展器 |
| Rerank | `KnowledgeService` 内联加分行（[knowledge.py:410](../src/mathtutor/application/knowledge.py#L410)） | 无独立可测试的 rerank 阶段；权重无测试钉住 |
| 引用可读性 | 不可变 version 永久保留 | 停用文档后已发引用**不可再读**（[knowledge.py:373](../src/mathtutor/application/knowledge.py#L373)） |
| 检索策略 | `RetrievalPolicy` 六意图 × 六来源矩阵 | **不驱动 tutor 文档检索**，仅 `adaptive_practice` 消费 |

### 2.3 TEST_ONLY

| 模块 | 位置 | 唯一使用方 |
|---|---|---|
| `MetadataFirstRetriever` | [retrieval_router.py:104](../src/mathtutor/application/retrieval_router.py#L104) | `scripts/math_tutor_rc_benchmark.py:124` + 4 个 test_phase6_retrieval* |
| `LexicalScoreReranker` | [lexical_reranker.py:35](../src/mathtutor/application/lexical_reranker.py#L35) | 同上 |
| `NoOpReranker` | [retrieval_router.py:57](../src/mathtutor/application/retrieval_router.py#L57) | 同上 |
| `FakeEmbeddingBackend` | [embedding_runtime.py:39](../src/mathtutor/infrastructure/embedding_runtime.py#L39) | 测试；生产侧 [knowledge.py:392-396](../src/mathtutor/application/knowledge.py#L392-L396) 显式拒绝 |
| `InMemoryDocumentRepository` / `InMemoryConversationRepository` | [document_repository.py:151](../src/mathtutor/repositories/document_repository.py#L151) | 测试 + 无 DB 模式 |

### 2.4 INFRASTRUCTURE_ONLY

| 模块 | 位置 | 状态 |
|---|---|---|
| `SqliteVecVectorIndex` | [sqlite_vec_index.py:71](../src/mathtutor/infrastructure/sqlite_vec_index.py#L71) | 无 `src/` importer；文件头自述"零生产引用"（[:6-8](../src/mathtutor/infrastructure/sqlite_vec_index.py#L6-L8)） |
| `ocr_text` 字段 | [documents.py:100](../src/mathtutor/domain/documents.py#L100) | 仅 MinerU 分支填充；不进 `text`/`fts_text` |

### 2.5 DEAD_CODE

| 模块 | 位置 | 说明 |
|---|---|---|
| `DoclingAdapter` | [parse_adapters.py:126-142](../src/mathtutor/infrastructure/parse_adapters.py#L126-L142) | `parse()` 抛异常，无人 import |
| `LlamaParseAdapter` | [:145-157](../src/mathtutor/infrastructure/parse_adapters.py#L145-L157) | 同上 |
| `DocumentIndexManager.is_current` | [document_ingestion.py:425-435](../src/mathtutor/application/document_ingestion.py#L425-L435) | 仅 `tests/test_embedding.py` 调用 |
| `DocumentStatus."deleted"` | [documents.py:42](../src/mathtutor/domain/documents.py#L42) | 从未赋值 |
| `conversation_documents` 清理 | — | 删除文档时不清理，全仓无对应 delete |
| `downgrade_db` | [migrate.py:51-52](../src/mathtutor/infrastructure/migrate.py#L51-L52) | 无 `src/` 调用者 |

### 2.6 NOT_IMPLEMENTED

| 能力 | 证据 |
|---|---|
| **OCR runtime** | 全仓零引擎标识符；依赖仅 pymupdf/pypdf |
| **自动 OCR 回退** | 无任何触发路径 |
| **`needs_ocr` 消费 worker** | `needs_ocr` 是终态，无消费者 |
| **逐页 scan/text 分类** | 无该类型或字段 |
| **数学符号 / LaTeX 恢复** | 无数学模型或转换器；`formula` 仅来自字面 `$` 定界符 |
| **FTS 触发器** | 全仓 `CREATE TRIGGER` 零命中 |
| **prev/next chunk 链接** | 全仓零命中 |
| **ANN 向量索引（生产）** | 向量检索是 Python 全扫描（[:511-565](../src/mathtutor/repositories/sqlite_documents.py#L511-L565) 自称 naive scan） |
| **EvidencePack** | 不存在该类型 |
| **ContextExpander** | 不存在 |
| **RAG telemetry** | 只有 loop metrics（[tutor_runtime.py:19-38](../src/mathtutor/application/tutor_runtime.py#L19-L38)） |
| **RAG eval（Retrieval/Context/Generation 三类）** | 只有 benchmark，且针对未接线的 `RetrievalItem` 数据集 |
| **RetrievalDecision 分类** | 不存在；分流靠 `config.mode` 与正则 |

### 2.7 DEPRECATED 建议（Route 2 下）

`[建议]` `MetadataFirstRetriever` / `NoOpReranker` / `RetrievalItem` / `RetrievedResult` 标记 DEPRECATED，保留至 benchmark 迁移完成后删除。

---

## 3. 已确认缺陷

> 全部为 `[事实]`，逐条附 `file:line`。按严重度排序。

| # | 缺陷 | 位置 | 影响 | 状态 |
|---|---|---|---|---|
| D1 | `current_document_scope()` 默认 `None`，`None` = **不做文档过滤（owner 全域）** | [conversation_scope.py:7](../src/mathtutor/application/conversation_scope.py#L7) + [context_assembler.py:436-444](../src/mathtutor/application/context_assembler.py#L436-L444) + [sqlite_documents.py:467](../src/mathtutor/repositories/sqlite_documents.py#L467) | **latent 跨会话检索**；当前不可达，但任何 WS 回合外的 assembler 调用会静默泄漏 | **CLOSED (A2)** |
| D2 | 删除文档**不清理** `conversation_documents` | [data_lifecycle.py:466-498](../src/mathtutor/application/data_lifecycle.py#L466-L498) | 绑定行残留；当前由 `doc_where` 兜住，但绑定表与文档表不一致 | OPEN |
| D3 | `DocumentIndexManager.is_current` 在生产中**永不被调用** | [document_ingestion.py:425-435](../src/mathtutor/application/document_ingestion.py#L425-L435) | 无调用者 → 索引陈旧检测在写入侧无出口（实际由 `build_index` 内的 `matches_signature` 覆盖） | OPEN |
| D4 | `matches_signature` **不含 `normalization` 与 `runtime_version`** | [documents.py:249-263](../src/mathtutor/domain/documents.py#L249-L263) | 归一化策略变更不触发重建 → 向量与水印失配 | OPEN |
| D5 | 每次写 chunk 都**全表重建 FTS** | [sqlite_documents.py:314](../src/mathtutor/repositories/sqlite_documents.py#L314) + [document_fts.py:36-51](../src/mathtutor/infrastructure/document_fts.py#L36-L51) | O(全库 chunk) 写入放大；无触发器，绕过 `replace_document_chunks` 的写入会静默失配 | OPEN |
| D6 | 上传路径**先全量读入内存再检查大小** | [desktop_api.py:1368](../src/mathtutor/api/desktop_api.py#L1368) | 20 MiB 上限在缓冲之后才生效（knowledge 路由正确用了 `MAX+1`，[knowledge_api.py:138](../src/mathtutor/api/knowledge_api.py#L138)） | OPEN |
| D7 | `MinerU` 结果被标为 `parse_mode="text_layer"` | [parse_adapters.py:114](../src/mathtutor/infrastructure/parse_adapters.py#L114) | 扫描件被 MinerU 恢复后变 `ready` 而非 `ready_with_warnings`，用户无从知晓来源 | **CLOSED (B2)** |
| D8 | 抽取型文档 `provenance.source_hash`（原始字节）与 `body_hash`（chunk 拼接）**不同源** | [knowledge.py:355](../src/mathtutor/application/knowledge.py#L355) | 两者失配时无法判断是文件变了还是切片变了 | OPEN |
| D9 | `snapshot(version=1)` 在无既有行时**合成当前内容**而非 fail closed | [knowledge.py:351](../src/mathtutor/application/knowledge.py#L351) | 可读到并非当时版本的"v1" | OPEN |
| D10 | 停用/删除文档使**已发引用不可读** | [knowledge.py:373](../src/mathtutor/application/knowledge.py#L373) | 不可变版本仍在，但 `is_retrievable()` 拦住了读取 | OPEN |
| D11 | `ChatDocumentContext` overview 分支用 `list_chunks`（**只按 owner 过滤**） | [chat_documents.py:53](../src/mathtutor/application/chat_documents.py#L53) + [sqlite_knowledge.py:192-198](../src/mathtutor/repositories/sqlite_knowledge.py#L192-L198) | 与检索主路径可见性语义不一致（不含 `retrieval_enabled`）。**注意：审计确认这不是现行泄漏** —— 调用方恰好传入了预过滤列表；真实问题是"安全性依赖调用方纪律，数据层无独立守卫" | **CLOSED (A2)** |
| D12 | 解析失败分支可能返回 `None` → `_project_document(None)` 500 | [document_ingestion.py:216-226](../src/mathtutor/application/document_ingestion.py#L216-L226) | `reparse` 有 `None` 守卫，`ingest` 没有 | OPEN |
| D13 | `RetrievalPolicy` **职责范围被误述**（见 §6.5 更正） | [retrieval_policy.py](../src/mathtutor/domain/retrieval_policy.py) | 实际驱动结构化路径（practice + hint/explain），但不驱动 chat / KB 路径；且 3 行矩阵为 TEST_ONLY | **CLOSED (§6.4)** |
| D14 | 结构化路径 `DocumentContextSelection` **无 `partial` 字段** | [assembled_context.py:177-185](../src/mathtutor/domain/assembled_context.py#L177-L185) | 不向模型声明上下文被截断 | OPEN |
| D15 | 两套并行打分机制无共享契约 | [knowledge.py:410](../src/mathtutor/application/knowledge.py#L410) vs [sqlite_documents.py:552-555](../src/mathtutor/repositories/sqlite_documents.py#L552-L555) | 魔数 `1.0`/`.25` 无测试钉住 | OPEN |
| D16 | `needs_ocr` 无消费 worker | [document_ingestion.py:87](../src/mathtutor/application/document_ingestion.py#L87) | 扫描件永久不可检索，用户只能自行删除 | OPEN |
| D17 | `fts_query_tokens` 每次检索重复计算两次 | [sqlite_documents.py:457-458](../src/mathtutor/repositories/sqlite_documents.py#L457-L458) | 轻微 | OPEN |
| D18 | `parser_version` 变更不触发重新切片 | [document_ingestion.py:283](../src/mathtutor/application/document_ingestion.py#L283) | 仅影响索引签名，chunk 内容不重算 | OPEN |

`[事实]` D19 / D20 由运行时探测发现，列在 **§6.8**。

`[事实]` 状态汇总：**6 CLOSED（D1, D7, D11, D13, D19, D20）· 14 OPEN**。

### 3.1 TEST INFRASTRUCTURE DEFECT（必须明确标注）

`[事实]` sqlite-vec 真实 KNN 测试**在任何非 macOS 环境永远 skip**：

```python
_PROBE_DYLIB = Path("/tmp/sqlite_vec_probe/extracted/sqlite_vec/vec0.dylib")
requires_sqlite_vec = pytest.mark.skipif(
    not _PROBE_DYLIB.exists(),
    reason="sqlite-vec 探测 dylib 不在 /tmp/sqlite_vec_probe（本轮实测环境专用）",
)
```

位置：[tests/test_phase6_retrieval_metadata_first.py:47-52](../tests/test_phase6_retrieval_metadata_first.py#L47-L52)。

- `[事实]` 路径硬编码 POSIX `/tmp`，**Windows 上恒不成立**
- `[事实]` 依赖手工下载到 `/tmp` 的探测产物，**不在 CI 中产生**
- **结论：不得将任何"Windows 上 sqlite-vec 验证通过"写成结论。Windows 上该测试从未真正执行。**

`[事实]` 本机实测确认：全量回归中 `test_phase6_retrieval_metadata_first.py` 的 4 个 sqlite-vec 测试全部 `SKIPPED`，跳过原因为 `sqlite-vec 探测 dylib 不在 /tmp/sqlite_vec_probe`。

### 3.2 Phase A2 — Retrieval Safety Hardening（已实施）

在 Phase C 之前插入的安全加固阶段，先关闭 D1 与 D11。**本阶段不涉及检索语义，未改动任何召回/排序逻辑。**

`[事实]` **D1 修复** — `UserDocumentsSourceProvider.retrieve` 对 `None` scope 改为 fail closed：

```python
document_ids = current_document_scope()
if document_ids is None:
    return LoadOutcome(empty_data=True, detail="no conversation document scope")
if not document_ids:
    return LoadOutcome(empty_data=True, detail="conversation has no documents")
```

两个状态在 provenance 中以 `detail` 区分，telemetry 可分辨"该路径从未设置 scope"（接线缺陷）与"会话确实无文档"（正常）。见 [context_assembler.py:436-444](../src/mathtutor/application/context_assembler.py#L436-L444)；契约写入 [conversation_scope.py:1-19](../src/mathtutor/application/conversation_scope.py#L1-L19)。

`[事实]` **D11 修复** — 新增数据层独立守卫 `list_retrievable_chunks`，复用与 `search_document_chunks` **完全相同**的 `doc_where` 谓词：

| 文件 | 变更 |
|---|---|
| [document_repository.py](../src/mathtutor/repositories/document_repository.py) | Protocol 新增方法 + `InMemoryDocumentRepository` 实现 |
| [sqlite_documents.py](../src/mathtutor/repositories/sqlite_documents.py) | `list_retrievable_chunks` SQL 实现（owner + `retrieval_enabled` + 未删 + 可检索状态） |
| [sqlite_knowledge.py](../src/mathtutor/repositories/sqlite_knowledge.py) | `SQLiteDocumentRepository` 适配器 |
| [chat_documents.py:53](../src/mathtutor/application/chat_documents.py#L53) | overview 分支改用新方法 |

`[事实]` `list_chunks` **保持不变**（owner-scoped）。它是 `snapshot`（版本重建）、`build_index`（索引构建）、`purge`（清理）的正确原语 —— 这三者必须能看到已停用文档。可见性从此由"用哪个方法"表达，而非靠调用方自觉。

`[事实]` 回归测试 [tests/test_retrieval_safety.py](../tests/test_retrieval_safety.py) 覆盖：未设 scope 不触达检索器、空 scope 与未设 scope 可区分、assembler 端到端 fail closed、合法路径不受影响、内存与 SQLite 两种实现的可见性门、跨 owner / 软删 / `needs_ocr` / `retrieval_enabled=False` 全部拒绝、`list_chunks` 对版本化保持宽松、chat overview 不读禁用文档。

`[事实]` 连带修正两处**原本依赖 fail-open 的既有测试**：
- [test_context_assembler.py:411](../tests/test_context_assembler.py#L411) —— 未设 scope 直接 `assemble`，靠 owner 全域命中 stub；已按生产用法补 `set_document_scope`
- [test_chat_document_context.py:83](../tests/test_chat_document_context.py#L83) —— 假仓库改用新方法名

`[事实]` 回归结果（`pytest tests/ -q -p no:randomly`）：**1182 passed, 9 skipped, 0 failed**。

`[事实]` 9 项 skip 全部为**环境既有跳过**，与本次改动无关：4 项 sqlite-vec（POSIX `/tmp` 探测路径，见 §3.1）、3 项 `torch` 未安装、2 项 `pymupdf` 未安装。

---

## 4. Architecture Decision

### 4.0 已采纳的决策（2026-09-18）

| 决策项 | 结论 |
|---|---|
| 路线 | **Route 2 — Production-path consolidation** |
| `RetrievalPolicy` | **收窄为 practice-only**（§4.6 选项 B）；改文档与命名，不参与 tutor 文档检索决策 |
| Context expansion | **本轮实现**；邻接关系由 `(document_id, sequence)` **动态解析**，不新增 `prev_chunk_id` / `next_chunk_id` 持久字段，**不创建 migration 021** |
| 前置阶段 | 新增 **Phase A2 Retrieval Safety Hardening**，先关闭 D1 与 D11（已完成，见 §3.2） |

### 4.1 Route 1 vs Route 2 前提

`[事实]` 生产调用链（三条，均已验证）：

```
① 普通/视觉对话
   math_tutor_ws.py:303-316 run() → set_document_scope(:312) → controller.run(:316)
   → controller.py:892 _chat_message → :906-909 document_source.build
   → chat_documents.py:45 self.search.search()

② 结构化 hint/explain
   controller.py:2227-2267 _document_context_for_action（仅 GIVE_HINT/EXPLAIN_CONCEPT）
   → adaptive_practice.py:246 assemble_for_intent → context_assembler.py:439
   → UserDocumentsSourceProvider.retrieve → self._searchable.search()

③ 知识库问答
   knowledge_qa.py:32 / knowledge_tools.py:147 → knowledge.py:384-398
   → state.document_index.search()
```

三条全部落到同一个 `DocumentIndexManager.search`（[product_state.py:390-393](../src/mathtutor/api/product_state.py#L390-L393) 单例）。

### 4.2 Route 1 — 把 `MetadataFirstRetriever` 适配到生产 `DocumentChunk`

| file | symbol | change | new dependency | migration | tests affected | risk | code surface |
|---|---|---|---|---|---|---|---|
| `application/retrieval_router.py` | `RetrievalItem` | 替换为对 `DocumentChunk` + metadata 的适配器 | 无 | 无 | test_phase6_retrieval*.py 全部 | 数据模型语义丢失（`stage/grade/skill_codes/mapping_ids` 在文档上无对应） | ~120 行改写 |
| `application/retrieval_router.py` | `_metadata_filter` | 需新增 `conversation_id` 维度（`RetrievalItem` 目前**没有该字段**） | 需注入 scope 解析器 | 无 | 新增 | 过滤逻辑与 SQL `doc_where` **重复** | ~60 行 |
| `application/retrieval_router.py` | `MetadataFirstRetriever.retrieve` | 增加候选装载（从 repository 取全部 owner chunk），再过滤 | `DocumentRepository.list_chunks` | 无 | 新增 | **候选装载会退化为全库扫描**——目前 SQL 是先过滤后取行 | ~80 行 |
| `repositories/document_repository.py` | `search_chunks` | 需保持与 router 一致的排序契约 | 无 | 无 | test_document_pipeline.py | 两套打分并存 | ~40 行 |
| `application/knowledge.py` | `KnowledgeService.search` | 改走 `MetadataFirstRetriever` | 无 | 无 | test_knowledge_* | 需重写假后端拒绝逻辑（[:392-396](../src/mathtutor/application/knowledge.py#L392-L396)） | ~30 行 |
| `application/chat_documents.py` | `ChatDocumentContext.build` | 改走 `MetadataFirstRetriever` | 无 | 无 | test_chat_document_context.py | 现有 `partial` 契约需重建 | ~40 行 |
| `application/context_assembler.py` | `UserDocumentsSourceProvider` | 改走 `MetadataFirstRetriever` | 无 | 无 | test_context_assembler.py | 预算语义需重定 | ~30 行 |
| `scripts/math_tutor_rc_benchmark.py` | — | 无需改（本就是它） | — | — | benchmark 数值需重算 | — | — |
| `tests/test_phase6_retrieval*.py` | — | 需重写为针对真实 contract | — | — | 4 个文件 | **丢失现有回归基准** | ~400 行 |

`[推断]` **收益**：命名与需求书一致；`RetrievalPolicy` 矩阵天然作用于 `RetrievalItem`，Route 1 下 D13 可自然消解。
`[推断]` **代价**：① 引入第二次数据模型转换（`DocumentChunk` → `RetrievalItem` → 回 `RetrievedChunk`）；② **候选装载必须先在 Python 侧取回 owner 全部 chunk**，因为 `MetadataFirstRetriever` 的过滤是内存过滤（[retrieval_router.py:122-169](../src/mathtutor/application/retrieval_router.py#L122-L169)）—— 这会把当前"SQL 先过滤后取行"降级为"先取行后过滤"，**违反硬约束 #1 的原始意图**；③ 4 个 retrieval 测试文件需重写，现有 benchmark 冻结值失效。

### 4.3 Route 2 — 保留 `DocumentIndexManager` 为生产检索内核

| file | symbol | change | new dependency | migration | tests affected | risk | code surface |
|---|---|---|---|---|---|---|---|
| `application/retrieval_orchestrator.py` | **新增** `ConversationRetrievalOrchestrator` | decision + scope + rewrite，调用 kernel | 无 | 无 | 新增测试 | 新模块的边界划分 | ~200 行 |
| `application/document_ingestion.py` | `DocumentIndexManager.search` | **不改签名**；新增 `get_candidates()` 返回带 `chunk_id`/score 的稳定契约 | 无 | 无 | 现有测试 | 低 | ~20 行 |
| `application/rerank.py` | **新增** `ProductionReranker` | 重构 `LexicalScoreReranker.rerank` 使其直接作用于 `RetrievedChunk`（当前用 `getattr(candidate,"text","")`，[lexical_reranker.py:59](../src/mathtutor/application/lexical_reranker.py#L59)，对 `RetrievedChunk` 不成立） | 无 | 无 | 复用 test_phase6_retrieval_reranker.py 算法断言 | 接口重构 | ~60 行 |
| `application/evidence_pack.py` | **新增** `EvidencePack` / `Evidence` | 冻结投影，字段来自 `RetrievedChunk`（已含 `document_id`/`filename`/`score`/`lexical_score`/`vector_score`）+ `chunk.page/section/heading_path` | 无 | 无 | 新增 | 需与 `knowledge.read_source` 的 `source_id` 契约对齐 | ~150 行 |
| `application/context_expansion.py` | **新增** `ContextExpander` | parent/相邻扩展 + token 上限 | 无 | 无 | 新增 | 邻接由 `(document_id, sequence)` 动态解析（`sequence` 有 `UNIQUE(document_id, sequence)` 约束，[schema.py:581](../src/mathtutor/infrastructure/schema.py#L581)）；仅需一次按 sequence 的区间读 | ~100 行 |
| `application/knowledge_qa.py` | `KnowledgeQA.respond` | 先跑 orchestrator → EvidencePack 注入首轮 messages | 无 | 无 | test_knowledge_* | **改变首轮语义**（当前首轮无文档上下文） | ~50 行 |
| `application/chat_documents.py` | `ChatDocumentContext.build` | 改调 orchestrator；保留既有 `partial` 与 12000 字符上限 | 无 | 无 | test_chat_document_context.py | 低 | ~40 行 |
| `application/context_assembler.py` | `UserDocumentsSourceProvider.retrieve` | 改调 orchestrator；补 `partial` 字段 | 无 | 无 | test_context_assembler.py | `assembled_context.py` 需加字段 | ~40 行 |
| `domain/assembled_context.py` | `DocumentContextSelection` | 增加 `partial: bool` | 无 | 无 | 现有测试 | 低 | ~5 行 |
| `application/knowledge_tools.py` | `search_knowledge` / `read_source` | **语义收窄为 second retrieval**；`read_source` 的 hit restriction 保留不变 | 无 | 无 | test_knowledge_safety.py | 需补 pinned 测试 | ~20 行 |
| `application/knowledge.py` | `KnowledgeService.search` | 内联加分行（[:410](../src/mathtutor/application/knowledge.py#L410)）迁入 `ProductionReranker` | 无 | 无 | 新增 | 需钉住魔数 | ~25 行 |
| `application/retrieval_router.py` | `MetadataFirstRetriever` | 标 `DEPRECATED`，docstring 说明替代者 | 无 | 无 | 保留不删 | 无 | ~10 行 |
| `application/lexical_reranker.py` | `LexicalScoreReranker` | 接口重构后由 `ProductionReranker` 复用 | 无 | 无 | 算法断言复用 | 无 | ~30 行 |
| `scripts/math_tutor_rc_benchmark.py` | — | 改为喂真实 `RetrievedChunk` / 真实 SQL | 无 | 无 | benchmark 数值需重算 | **迁移完成前不删旧路径** | ~150 行 |
| `infrastructure/sqlite_documents.py` | **新增** `list_chunk_neighbourhood` | 按 `(document_id, sequence)` 区间取邻接 chunk，供 ContextExpander 使用 | 无 | **无** | 新增 | 轻量；复用既有 `document_chunks` 索引 | ~35 行 |
| `infrastructure/schema.py` | `document_chunks` | **不改动** —— 不新增 `prev_chunk_id` / `next_chunk_id` | 无 | **无** | 无 | 无 | 0 行 |
| `application/conversation_scope.py` | `current_document_scope` | **已完成 (A2)**：`None` 语义 fail-closed，契约写入 docstring | 无 | 无 | test_retrieval_safety.py | 已关闭 D1 | 已完成 |
| `api/desktop_api.py` | `GET /documents/{id}` | 补 `partial` / 索引状态到投影 | 无 | 无 | test_desktop_bridge.py | 低 | ~20 行 |

`[推断]` **收益**：① 不引入第三次数据模型转换；② 保留"SQL 先过滤后取行"的权限前置语义；③ 三条消费路径本就共享 kernel，改动集中在**编排层**；④ 现有 isolation 测试（test_document_pipeline / test_global_documents / test_knowledge_safety）语义不变。
`[推断]` **代价**：① 与需求书"新增 `RetrievalOrchestrator`"字面一致，但与"把 `MetadataFirstRetriever` 接进生产"字面不一致；② `RetrievalPolicy` 矩阵与 `RetrievalItem` 的天然配对关系被放弃 —— 已按 §4.6 决策 B 收窄为 practice-only。

`[事实]` **本路线无 migration。** 邻接关系由 `(document_id, sequence)` 动态解析（`sequence` 已具 `UNIQUE(document_id, sequence)` 约束，[schema.py:581](../src/mathtutor/infrastructure/schema.py#L581)），Phase C 不引入任何 schema 变更。

### 4.4 十一维度对比

| Dimension | Route 1 | Route 2 |
|---|---|---|
| production code touched | 5 个生产模块改写调用方式 + 1 个模块重写 | 1 个模块新增 + 6 个模块改调用 |
| new model conversion | **是**：`DocumentChunk` → `RetrievalItem` → `RetrievedChunk` | **否** |
| DB/repository changes | 无 | **无**（邻接按 `(document_id, sequence)` 动态解析，不落列） |
| migration risk | 无 | **无** |
| existing isolation tests reuse | 需重写 test_phase6_retrieval*（4 文件） | 全部保留；benchmark 迁移后再改 |
| benchmark reuse | 数值需重算且语义漂移 | 数值需重算，语义不变 |
| duplicate architecture risk | **高**：两套过滤逻辑（内存 filter vs SQL doc_where）并存 | 低：SQL 过滤保持唯一 |
| rollback complexity | 高（调用方式全面改写） | 低（新增模块可摘除，调用点回退 stubs） |
| Tutor integration cost | 改 `chat_documents.py`，需重建 `partial` 契约 | 改 `chat_documents.py`，`partial` 原样保留 |
| Knowledge mode integration cost | 改 `knowledge.py`，需重写假后端拒绝逻辑 | 改 `knowledge_qa.py` 加前置检索，`knowledge.py` 仅迁移内联加分行 |
| long-term maintainability | 三个数据模型长期共存 | 两个数据模型（`DocumentChunk` + `EvidencePack`） |
| **候选装载语义** | **退化**：需先取回 owner 全部 chunk 再内存过滤 | **保持**：SQL 先过滤后取行 |
| **是否违反硬约束 #1 原始意图** | **是**（过滤晚于候选装载） | 否 |

`[事实]` **已采用 Route 2**（见 §4.0）。

### 4.5 Route 2 下的职责边界

```
ConversationRetrievalOrchestrator   = decide + scope + rewrite + orchestrate
DocumentIndexManager                = retrieve / index      （唯一 kernel，不改签名）
ProductionReranker                  = rank
ContextExpander                     = restore neighbour / parent context（token 预算内）
EvidencePackBuilder                 = immutable public evidence projection
KnowledgeTools                      = agentic second retrieval / exact read / action
```

`[建议]` 不要合并为单个 `RetrievalManager`。

### 4.6 `RetrievalPolicy` 处置（已决策：选项 B）

`[事实]` 现状是"看起来是全局检索策略、实际只影响 adaptive practice"（D13）。

- **选项 A**：让 orchestrator 消费矩阵的 `USER_DOCUMENTS` 列 → 会造成矩阵"部分字段生效"的新模糊态
- **选项 B**：明确收窄为 practice-only，改文档与命名

`[事实]` **决策：采用 B —— 收窄为 practice-only。**

`[建议]` 收窄后需同步三件事：① `RetrievalPolicy` 的 docstring 明确声明"本矩阵只服务于练习生成的 ContextAssembler 路径"；② tutor 侧文档决策改由 `config.mode` + `hints_only` + 练习态决定（[controller.py:415-436](../src/mathtutor/application/controller.py#L415-L436)），并把 `USE_MY_DOCUMENT` 从"Tutor 文档检索由矩阵控制"的叙述中移除；③ D13 关闭。

`[推断]` 为何不选 A：Route 2 下 orchestrator 已经有一条确定的文档决策链，强行让六来源矩阵参与只会引入第二套决策源；且矩阵中 `STUDENT_MODEL` / `MISCONCEPTION_HISTORY` / `RECENT_ATTEMPTS` 与文档检索无关，部分采用会造成"哪些格子真的生效"这一新的模糊态。

---

## 5. 需求修正

### 5.1 OCR 状态模型（严格口径）

```
OCR status model:                EXISTS        (needs_ocr 状态字面量)
OCR metadata field:              EXISTS        (ParsedBlock.ocr_text, documents.py:100)
MinerU optional adapter:         EXISTS        (parse_adapters.py:39-117，非依赖项)
built-in OCR runtime:            NOT IMPLEMENTED
automatic OCR fallback:          NOT IMPLEMENTED
needs_ocr consumer worker:       NOT IMPLEMENTED
per-page scan/text classification: NOT IMPLEMENTED
```

`[事实]` **本轮未批准引入 OCR runtime** —— Phase B 只做 PDF 分类（text / scan / mixed，含逐页）与 `scan page → needs_ocr`。**不引入** PaddleOCR / Tesseract / EasyOCR，也不把上述六项中的任何 NOT IMPLEMENTED 写成已完成。

`[事实]` 另需注意：MinerU 成功恢复的扫描件当前被标为 `parse_mode="text_layer"`（[parse_adapters.py:114](../src/mathtutor/infrastructure/parse_adapters.py#L114)），会以 `ready` 而非 `ready_with_warnings` 进入检索（D7）。

### 5.2 Chunker 现状与真实缺口

`[事实]` 旧需求"把固定 1000/100 overlap chunker 升级为 structure-aware"**与事实不符**。`TextChunker` v2 已具备：

- 中文 section / example / solution / proof / definition / theorem / exercise 角色识别（[chunking.py:37-51](../src/mathtutor/infrastructure/chunking.py#L37-L51)、[:322-334](../src/mathtutor/infrastructure/chunking.py#L322-L334)）
- `heading_path`、`page_start/page_end`、`chunk_type`、`parent_index`→`parent_chunk_id`
- latex / table / figure metadata（[:435-456](../src/mathtutor/infrastructure/chunking.py#L435-L456)）

`[事实]` 真实缺口：

| 缺口 | 是否 retrieval 必需 | 证据 |
|---|---|---|
| `prev` / `next` 链接 | **否 —— 已决策不落持久列** | 全仓零命中；但 `sequence` 已有 `UNIQUE(document_id, sequence)` 约束（[schema.py:581](../src/mathtutor/infrastructure/schema.py#L581)），邻接可在读取时按 `sequence ± 1` 动态解析。落列需要 migration + 回填，收益不足以抵消 schema 变更风险 |
| section 树 | **待证明** | 现有 `heading_path` 扁平元组已能表达层级；无证据表明检索需要可导航树 |
| `raw` / `normalized` 双文本 | **待证明** | 当前只有单一 `text` + `content_hash=sha256(text)`；无清洗层，故无双文本需求 |
| token 预算 | **是** | chat 路径有字符预算但无 token 预算；assembler 路径有 4000 token 但语义不同 |

`[建议]` **不重写已通过测试的切片算法**。仅补 `prev`/`next`（需 migration，nullable）与统一 token 预算。section 树与 raw/normalized 双文本**先证明收益再实现**。

---

## 6. 未决 / NOT_VERIFIED

以下为审计未能定论的事项，**不得在后续文档中当作已确认事实**：

1. ~~`fitz`（PyMuPDF）在部署运行时是否可 import~~ —— **已解决，见 §6.1**
2. ~~MinerU 内部是否执行 OCR~~ —— **已解决，见 §6.1**（本仓内 MinerU 不可达）
3. ~~FTS5 在已发布的 SQLite 构建中是否可用~~ —— **已解决，见 §6.1**
4. `StaticCurriculumProvider` 在生产中是否有构造点（`context_assembler.py:478-508`）
5. 是否存在 migration 或回填把 `conversation_documents` 与 `knowledge_members` 互相写入 —— migration 020 明确保留 legacy 绑定
6. `user_documents` 是否有软删之外的硬删路径
7. 真实 pre-003 / pre-007 数据库的列集合 —— 仓库内无 `.db` 文件，列清单取自 `schema.py`（活源）
8. `controller.run` 之外是否还有进入 `ContextAssembler.assemble` 的路径 —— 已 grep 全部已知调用点，未发现；但 D1 的风险正源于此模式本身

`[建议]` 4–8 项在 Phase C 触及对应模块时确认。

### 6.1 运行时探测结果（Phase B 前置，已执行）

`[事实]` 探测脚本：[scripts/rag_runtime_probe.py](../scripts/rag_runtime_probe.py)，只读、无副作用。两个环境均实测：

| | dev venv | **发布运行时** |
|---|---|---|
| 路径 | `.venv/Scripts/python.exe` | `desktop/dist/win-unpacked/resources/python-runtime/python.exe` |
| Python | 3.12.3 | 3.12.10 (embeddable) |
| SQLite | 3.45.1 | 3.49.1 |
| PyMuPDF (`fitz`) | **缺失** | **缺失** |
| pypdf | 6.17.0 | 6.17.0 |
| torch / sentence_transformers / modelscope | 缺失 | 缺失 |
| MinerU CLI | 不在 PATH | — |
| OCR 引擎 | 无 | — |

**① PyMuPDF 两个环境都缺失 —— 且这是声明依赖。**

`pyproject.toml:19` 声明 `pymupdf>=1.24`，但两个环境都 `ModuleNotFoundError`。原因在打包策略 [desktop/package_allowlist.json](../desktop/package_allowlist.json)：

- `python_runtime.required_import_roots` 含 **`pypdf`**，**不含 `pymupdf`**
- `python_runtime.forbidden_feature_packages` 明确移除 `torch` / `transformers` / `sentence_transformers` / `modelscope` / `huggingface_hub`

`[事实]` 端到端验证（同一份手工构造的带文字层 PDF，两个运行时结果**完全一致**）：

```
parse_mode     = text_layer
block_types    = {"paragraph": 1}      ← 只有段落块
heading 块     = 0
table 块       = 0
figure 块      = 0
total_pages    = 1, text_pages = 1, empty_pages = 0
```

`[推断]` **发布产品实际走的是 pypdf 回退分支**（[document_parser.py:122-125](../src/mathtutor/infrastructure/document_parser.py#L122-L125)），其直接后果：

1. 无表格抽取（`find_tables()` 是 PyMuPDF 专有）
2. 无图片抽取（`get_images()` 同上）→ **`figure` 块永不产生**
3. 无字号标题识别（[document_parser.py:461-471](../src/mathtutor/infrastructure/document_parser.py#L461-L471)）→ **`heading` 块永不产生**
4. `_parse_pdf` 的零字数分支**永不执行** —— 而 MinerU 调用点正在该分支内（[:134](../src/mathtutor/infrastructure/document_parser.py#L134)）。**即便用户自行安装了 MinerU，没有 PyMuPDF 也永远走不到它。**

`[事实]` **② FTS5 可用且工作正常**（两个运行时一致），包括 CJK bigram 匹配与别名扩充：

```
fts5_create            PASS
fts5_match:求根公式      PASS  tokens=['求根', '根公', '公式', '求根公式'] matched=1
fts5_match:判别式        PASS  matched=1
fts5_match:二次方程      PASS  matched=1
fts5_alias_expansion   PASS  「解方程」命中源文只写「一元二次方程」的块
```

`[事实]` 一处**探针自身的错误**已修正并记录：初版探针直接向 FTS 表插入原始中文，得到 0 命中，一度被误读为 FTS5 不可用。实际原因是 CJK bigram 在 Python 侧预切（[lexical.py:80-82](../src/mathtutor/infrastructure/lexical.py#L80-L82)），必须用 `build_fts_text` 构造索引串。改用生产同款 `build_fts_text` + `fts_query_tokens` + `fts_match_query` 后全部通过。

`[事实]` **③ 打包策略把 Phase A 的结论固化为政策**。[package_allowlist.json](../desktop/package_allowlist.json) 的 `python_source.exclude` 显式排除：

```
application/lexical_reranker.py
application/retrieval_router.py
infrastructure/sqlite_vec_index.py
```

即这三个模块是**按策略**不进发布产物，不只是"恰好没接线"。

`[事实]` **④ 打包产物缺少 `parse_adapters` 等模块**：`desktop/dist/win-unpacked` 内的 `python-app/mathtutor/infrastructure/` 无 `parse_adapters.py`、`document_fts.py`、`knowledge_schema.py`、`embedding_config.py`。注意该 dist 为 **0.2.0** 构建，而仓库为 0.3.3 —— 该缺失反映的是旧构建，当前 `include` 规则 `infrastructure/**/*.py` 会包含它们。**不得据此判断当前打包缺文件。**

### 6.2 Phase B — 已实施（2026-09-19）

`[事实]` 冻结声明（D19 最终决策）：

> **MathTutor 发布版以 pypdf 作为 guaranteed PDF baseline，不将 PyMuPDF 纳入本轮发行依赖；PyMuPDF 调整为 optional rich-parser capability。Phase B 的 PDF 分类仅基于可证明的文本层事实，不伪造图像/版面能力；同时独立修复 D20，使无文本层文档在任何 baseline parser 下均可进入 optional recovery / needs_ocr 流程。**

能力表（`[事实]`，与 §6.1 实测一致）：

| 能力 | 状态 |
|---|---|
| pypdf baseline parsing | **IMPLEMENTED**（发布运行时实测可用） |
| PyMuPDF rich parsing | **OPTIONAL**（不在发布产物；环境门控测试） |
| OCR engine | **NOT IMPLEMENTED** |
| MinerU adapter reachable | **IMPLEMENTED**（本轮修复） |
| MinerU bundled runtime | **NOT IMPLEMENTED** |
| 自动 OCR 能力 | **NOT IMPLEMENTED** |

`[事实]` 变更清单：

| 文件 | 变更 |
|---|---|
| [domain/documents.py](../src/mathtutor/domain/documents.py) | 新增 `PdfPageProfile`、`PageTextLayer`、`DocumentClassification`、`DocumentParseError`、`classify_pdf`；`ParseMode` 增 `recovered_external`；`ParsedTextDocument` 增 `pages`/`classification`/`parser_id`；`UserDocument` 增 `parser_id`/`classification` |
| [document_parser.py](../src/mathtutor/infrastructure/document_parser.py) | `_parse_pdf` 重构为 baseline → optional recovery；新增 `_pymupdf()` 显式接缝；pypdf 逐页 profiling + encrypted/corrupted 分类；`PARSER_VERSION → mt-local-parser-v3` |
| [document_ingestion.py](../src/mathtutor/application/document_ingestion.py) | `_failure_update` 落库分类；`ingest_outcome_from_parse` 透传 `classification`/`parser_id` |
| [schema.py](../src/mathtutor/infrastructure/schema.py) + [迁移 021](../src/mathtutor/infrastructure/migrations/versions/021_document_parser_provenance.py) | `user_documents` 增 `parser_id`/`classification`（backward compatible，旧行只回填可证明的值） |
| [sqlite_documents.py](../src/mathtutor/repositories/sqlite_documents.py) | 行映射与 insert/update 覆盖新列 |
| [pyproject.toml](../pyproject.toml) | `pymupdf` / `sentence-transformers` / `modelscope` 移出 core，改为 `pdf-rich` / `embedding` extras —— 关闭 D19 契约错误 |
| [test_pdf_classification.py](../tests/test_pdf_classification.py) | Phase B 验收测试（B1–B10） |

`[事实]` 验收对照：

| # | 条目 | 测试 |
|---|---|---|
| B1 | pypdf baseline 在发布运行时真实可用 | `test_pypdf_baseline_extracts_a_text_layer` |
| B2 | 每页 extractable-text profiling | `test_per_page_profile_records_extractable_text_chars`、`test_page_profile_does_not_fabricate_measurements` |
| B3 | document text-layer classification | `test_classification_from_observable_page_facts`、`test_classifier_never_claims_a_page_is_scanned` |
| B4 | encrypted / corrupted 明确区分 | `test_encrypted_pdf_is_classified_*`、`test_corrupted_pdf_is_classified_*` |
| B5 | 无文本层 → needs_ocr，不伪成功 | `test_no_text_layer_pdf_becomes_needs_ocr_not_ready` |
| B6 | optional recovery 不依赖 PyMuPDF 可达 | `test_external_recovery_is_reachable_without_pymupdf` |
| B7 | recovery 来源被显式标记 | `test_recovered_text_is_labelled_as_external` |
| B8 | pypdf 文本进入现有 TextChunker v2 | `test_baseline_text_flows_into_the_existing_chunker` |
| B9 | 中文 role 切片回归不退化 | `test_chinese_math_role_detection_survives_baseline_parsing` |
| B10 | parser capability 与真实 package manifest 一致 | `test_declared_dependencies_match_the_shipped_runtime` |

`[事实]` PyMuPDF 相关期望单列为 **OPTIONAL / 环境门控**（`test_pdf_classification.py` 末尾），**其 skip 不作为产品能力 PASS 的证据**。

`[事实]` 全量回归：**1201 passed, 11 skipped, 0 failed**。

`[建议]` **Chunker 未改动**。需在文档中区分两种结构：

```
text-semantic structure   ← 中文 role 标记（例/解/证明/定义/定理）在文本自身里
                            PDF 与文本文件都保留，TextChunker v2 由此工作
PDF-layout structure      ← heading / table / figure 块类型
                            仅 PyMuPDF 可产出；pypdf baseline 下对 PDF 不适用
```

### 6.3 Phase C 设计约束（不得写死 lexical）

`[事实]` 发布运行时观察到的是 lexical-only，但**该事实不得反向污染 domain/application 契约**。

`[建议]` Phase C 保留：

```python
RetrievalMode = "lexical" | "hybrid"     # 架构能力，不因某个发行包缺依赖而收缩
```

并以结构化执行记录实际发生的事：

```python
RetrievalExecution(
    lexical_used=True,
    vector_used=False,
    reranker_used=True/False,
    degraded_reasons=(...),   # 例如 runtime_unavailable
)
```

理由：① embedding 本就是可选能力；② package policy 可变；③ remote/OpenAI-compatible embedding 是否仍可启用需按实际 production wiring 单独确认；④ **vector 不可用 ≠ reranker 无意义** —— `ProductionReranker` 不依赖 embedding，`FTS candidates → lexical reranker → EvidencePack` 是完整可用的链路。

### 6.4 D13 — 职责收窄（已实施，并更正 Phase A 的一处误判）

`[事实]` **更正**：Phase A 报告把 D13 描述为"`RetrievalPolicy` 不驱动 tutor 文档检索，仅 `adaptive_practice` 消费"。**该描述不准确**，此更正由 D13 实施时的调用点核查发现。

`[事实]` 实际的生产可达意图（`src/` 中唯一三处）：

| Intent | 调用点 | 属于 |
|---|---|---|
| `GENERATE_PRACTICE` | [adaptive_practice.py:180](../src/mathtutor/application/adaptive_practice.py#L180) | 练习生成 |
| `REQUEST_HINT` | [controller.py:2243](../src/mathtutor/application/controller.py#L2243) | **tutor `GIVE_HINT` 动作** |
| `EXPLAIN_CONCEPT` | [controller.py:2245](../src/mathtutor/application/controller.py#L2245) | **tutor `EXPLAIN_CONCEPT` 动作** |

后两者经 `_document_context_for_action`（[controller.py:2227-2267](../src/mathtutor/application/controller.py#L2227-L2267)）落到 `UserDocumentsSourceProvider` —— **所以矩阵确实驱动 tutor 的 hint/explain 文档检索**，其 docstring 本身也这样写（[:2228-2233](../src/mathtutor/application/controller.py#L2228-L2233)）。

`[事实]` 因此正确的收窄边界不是"practice-only"而是：

```
RetrievalPolicy 管辖  结构化 ContextAssembler 路径
                     = 练习生成 + GIVE_HINT + EXPLAIN_CONCEPT
RetrievalPolicy 不管辖
                     对话路径（ChatDocumentContext）
                     知识库问答（KnowledgeTools + config.mode）
                     两者由会话绑定与 conversation scope 决定
```

`[事实]` **3 行矩阵为 TEST_ONLY**（`src/` 零引用）：`SOLVE_PROBLEM`、`GENERATE_ERROR_REVIEW`、`USE_MY_DOCUMENT`。

其中 `USE_MY_DOCUMENT` 尤其误导：它是唯一把 `USER_DOCUMENTS` 设为 **REQUIRED** 的行，只读矩阵会以为"根据我的文档回答"会强制检索文档；实际无任何生产路径解析它。

`[事实]` 实施内容：

| 变更 | 位置 |
|---|---|
| 模块 docstring 改写为准确 SCOPE（列出三个可达意图及其行号） | [retrieval_policy.py](../src/mathtutor/domain/retrieval_policy.py) |
| 新增 `PRODUCTION_INTENTS` frozenset，作为唯一的权威声明 | 同上 |
| 漂移守卫：`test_only_declared_intents_are_reachable` 扫描 `src/` 断言声明与实际一致 | [test_retrieval_policy.py](../tests/test_retrieval_policy.py) |
| `test_use_my_document_is_not_production_reachable` | 同上 |
| `test_chat_and_knowledge_paths_do_not_consult_the_matrix` | 同上 |

`[建议]` 守卫采用**扫描源码树**而非人工清单：要防的失效模式正是"某一行看起来可达"。新增生产调用点却不声明会失败；声明了却无人调用也会失败。

`[事实]` 3 行 TEST_ONLY **保留未删**——矩阵按构造即穷尽（未列出的来源默认 FORBIDDEN），删除会削弱该性质并使测试失效。它们由 `PRODUCTION_INTENTS` 与守卫测试明确标注为非产品行为。

### 6.5 Phase C — 检索编排（已实施，2026-09-19）

`[事实]` 按 §4.5 职责边界实现，**未新建检索内核**：

| 模块 | 职责 | 位置 |
|---|---|---|
| `ConversationRetrievalOrchestrator` | decide + scope + rewrite + orchestrate | [retrieval_orchestrator.py](../src/mathtutor/application/retrieval_orchestrator.py) |
| `ProductionReranker` | rank（确定性、无模型） | [rerank.py](../src/mathtutor/application/rerank.py) |
| `ContextExpander` | 邻接扩展 + 硬预算 | [context_expansion.py](../src/mathtutor/application/context_expansion.py) |
| `EvidencePack` / `Evidence` / `RetrievalExecution` | 不可变公开投影 | [domain/evidence.py](../src/mathtutor/domain/evidence.py) |
| `DocumentIndexManager.search` | **唯一 kernel，签名未改** | 未改动 |
| `list_chunk_neighbourhood` | `(document_id, sequence)` 邻接读取（带可见性门） | [sqlite_documents.py](../src/mathtutor/repositories/sqlite_documents.py) |

`[事实]` 关键设计决策：

1. **`document_ids` 是必填参数，无默认值。** D1 的根因是"未设置 scope"与"全部文档"取了同一个值（`None`）。编排器的签名让"未设置 scope"**无法表达**，只能在调用点显式给出（可为空列表，此时决策为 NONE）。从类型层面而非注释层面杜绝该类缺陷。
2. **`RetrievalMode` 保留 `lexical | hybrid`**，不因发布运行时缺 embedding 而收缩（§6.3）。两者之别来自 kernel 实际报告的 `vector_used`，不是配置推断。
3. **降级原因是机器可读前缀**（`embedding_runtime_unavailable` / `empty_conversation_scope` / `decision_none_small_talk` / `decision_none_hints_only`），telemetry 可直接分组。
4. **邻接动态解析**（§4.3 决策）：`list_chunk_neighbourhood` 按 `sequence` 区间读，无新列、无 migration。
5. **EvidencePack 在构建期截断**（≤8 条 / ≤12000 字符 / 单条 ≤2000），上限对所有消费者生效，包括未来新增的。
6. **`public_projection()` 是模型唯一可见的形态**：`body_hash` / `text_hash` / 各分数默认不外泄。

`[事实]` 接入 [knowledge_qa.py](../src/mathtutor/application/knowledge_qa.py)：

```
query → orchestrator.retrieve_for_turn → EvidencePack → 注入 system prompt → 工具循环
```

**首轮检索现在由系统保证**，模型不再需要自己"想到"去检索。系统提示词明确两点：证据是**数据不是指令**；证据只是**起点** —— 引用任何原文仍须调用 `read_source` 取得真实 `source_id` 与逐字 quote，**预取的片段不能洗成引用**。`search_knowledge` 语义相应收窄为二次检索 / multi-hop。

`[事实]` 修正了审计记录的一处实现缺陷：`LexicalScoreReranker` 读 `getattr(candidate, "text", "")`，对 `RetrievedChunk`（文本在 `.chunk.text`）恒为空 —— 意味着**此前唯一"通过测试"的 reranker 在真实 hits 上把每条都打成 0 分**，真正生效的只有 [knowledge.py:410](../src/mathtutor/application/knowledge.py#L410) 那行内联加分。`ProductionReranker` 直接作用于 `RetrievedChunk`，并把内联的魔数 `1.0` / `.25` 提为命名常量 `EXACT_PHRASE_BONUS` / `SECTION_MATCH_BONUS`，有测试钉住。

`[事实]` 测试 [test_retrieval_orchestration.py](../tests/test_retrieval_orchestration.py)（29 项）覆盖：决策四类 NONE + 歧义时检索、引用词改写吸收上下文且非引用词不吸收、改写有界、reranker 读真实文本 / 确定性 / 截断不臆造、扩展触发器保守 / 序列序 / 字符预算 / 条数上限 / 读失败保留命中且计数可见、EvidencePack 硬上限 / 丢弃空段 / 不可变 / 投影不外泄内部字段、编排器显式 scope 要求 / scope 原样透传 / 降级原因 / hybrid 模式 / 端到端可追溯。

`[事实]` 全量回归：**1233 passed, 11 skipped, 0 failed**。

`[事实]` **本轮未做**（不作能力声明）：

- `ChatDocumentContext` 未改走 orchestrator。Tutor 对话路径仍用自己的 12000 字符 / 8 块预算。两条消费路径**共享同一检索内核**但**尚未共享同一编排入口**。
- `DocumentContextSelection.partial` 字段（D14）未加；结构化路径（hint/explain/practice）未接入 orchestrator。
- RAG telemetry 计数器未接入 `HealthMetrics`（`RetrievalExecution` 已产出数据，尚无聚合出口）。
- Phase D（Agent 二次检索语义收窄、multi-hop）与 Phase E（eval）未开始。

### 6.6 RAG telemetry 聚合（已实施，2026-09-19）

`[事实]` 接线前 `MathTutorMetrics` **在生产中从未被实例化** —— 全仓只有 `tests/test_phase6_observability.py:24` 构造过它。即整个可观测性设施本身也是 test-only 的，与 §2.3 记录的同类模式一致。

`[事实]` 变更：

| 位置 | 变更 |
|---|---|
| [observability.py](../src/mathtutor/infrastructure/observability.py) | `_LATENCY_KINDS` 增 `retrieval` / `rerank` / `context_build`；新增固定键白名单 `_RAG_COUNTERS`；`record_retrieval` / `record_tool_call` / `record_citations` / `rag()`；`snapshot()` 增 `rag` 段 |
| [product_state.py](../src/mathtutor/api/product_state.py) | `self.metrics = MathTutorMetrics()` —— **首次在生产中实例化** |
| [retrieval_orchestrator.py](../src/mathtutor/application/retrieval_orchestrator.py) | 新增 `RetrievalMetricsSink` 协议 + `record_retrieval` 调用（含检索/重排延迟、context 字符数） |
| [knowledge_tools.py](../src/mathtutor/application/knowledge_tools.py) | `_record_tool_metric` 计数检索工具调用 |

`[事实]` 计数器（固定白名单，受 `assert_sanitized()` 结构守卫约束）：

```
rag_retrieval_requested_total   rag_retrieval_skipped_total
rag_empty_retrieval_total       rag_lexical_only_total
rag_hybrid_total                rag_degraded_total
rag_vector_unavailable_total    rag_expansion_used_total
rag_candidates_considered       rag_evidence_items
rag_evidence_chars              tool_search_calls
tool_read_calls                 citation_count
派生的比率：second_retrieval_rate · empty_retrieval_rate
```

`[事实]` **未实现 `rag_reranker_unavailable_total`**（需求书 §20 列了它）。理由：生产 reranker 是确定性且随应用发布的，**没有"不可用"状态** —— 一个永远不会触发的计数器会暗示一个并不存在的能力缺口。若将来引入可选的模型 reranker，届时应补上该计数器。这是有意的偏离，不是遗漏。

`[事实]` `second_retrieval_rate = tool_search_calls / rag_retrieval_requested_total`。它是判断"系统侧初始检索是否够用"的核心指标：**长期偏高**说明初始检索漏掉了轮次真正需要的东西；**恒为 0** 说明工具链是死的。

`[事实]` 日志安全：计数器只存整数与比率，测试 `test_rag_counters_carry_no_document_text` 断言**每个值的类型都是 int/float**——没有可以夹带文本的字段。`test_rag_snapshot_passes_the_structural_sanitization_guard` 断言新增键仍在闭集内。

### 6.7 Phase D — 初始证据可引用（已实施，2026-09-19）

`[事实]` Phase C 遗留的接缝：系统侧初始检索走 `document_index.search`，而 `read_source` 只接受 `search_knowledge` 记录过的 `(document_id, version, start, end)`。**结果是初始证据是模型看得见、却引用不了的内容**，想引用任何原文仍须再搜一次 —— 初始检索等于白做。

`[事实]` 修复 [knowledge_tools.seed_evidence](../src/mathtutor/application/knowledge_tools.py)：

```
证据 (document_id, chunk_id, text)
   ↓ 版本正文 = chunk 以 "
" 连接  →  由 sequence 推导 start/end
   ↓ 校验①：正文 [start:end] 必须逐字等于该 chunk 文本
   ↓ 校验②：证据文本必须是该 chunk 的前缀（原样或被包截断），
            或包含该 chunk（上下文扩展过的）
   ↓ 通过 → 注册进 search_hits
```

`[事实]` **hit restriction 没有被放宽**：推导出的区间只有被证明"确实指向这段文字"才注册。测试 `test_seeding_does_not_widen_the_hit_restriction` 断言：注册过的区间可读，而同一文档的**猜测区间**与**猜测 document_id** 仍为 `REJECTED`。

`[事实]` 校验②是**测试逼出来的**。实现初版只校验了①，`test_seeding_registers_nothing_when_the_text_does_not_address` 立即失败（篡改文本 + 真实 chunk_id 仍能注册成功）——那会让模型看到 X 而 `read_source` 返回 Y。已修正。

`[事实]` 测试 [test_agentic_retrieval.py](../tests/test_agentic_retrieval.py)（6 项）：种子后 `read_source` 成功且文本一致、篡改文本不注册、未知 chunk 不注册、猜测区间/猜测 document_id 仍拒绝、空/null pack 为 no-op、多命中 pack 全部注册。

`[事实]` 系统提示词同步更新：明确告知这些命中**已可通过 `read_source` 引用**（给出 `document_id` 与区间），且 `public_projection()` 现暴露 `document_id` —— 它是标识符而非能力：工具仍只接受被 surfaced 过的区间，知道 id 本身不授予任何权限。

`[事实]` 全量回归：**1250 passed, 11 skipped, 0 failed**。

`[事实]` **本轮未做**：`ChatDocumentContext` 未接入 orchestrator；结构化路径（hint/explain/practice）未接入；`multi-hop` 未显式实现（模型可用 `search_knowledge` 自行迭代，但无专门的跨章节编排）；Phase E（RAG eval）未开始。

### 6.8 新增缺陷

| # | 缺陷 | 位置 | 影响 | 状态 |
|---|---|---|---|---|
| D19 | `pyproject.toml` 声明的解析/嵌入依赖与打包策略**不一致** | [pyproject.toml:19-20](../pyproject.toml#L19-L20) vs [desktop/package_allowlist.json](../desktop/package_allowlist.json) | 声明 `pymupdf>=1.24`、`sentence-transformers>=3.0`，但打包 `required_import_roots` 不含 `pymupdf`，`forbidden_feature_packages` 移除 `sentence_transformers`。声明依赖对发布产物**不构成保证** | **CLOSED (B2)** |
| D20 | 无 PyMuPDF 时 **MinerU 永不可达** | [document_parser.py:124-125](../src/mathtutor/infrastructure/document_parser.py#L124-L125) | pypdf 分支直接 `return`，扫描件回退链断裂；用户即使自装 MinerU 也无效果 | **CLOSED (B2)** |

---

## 7. 事实 / 推断 / 建议 分离索引

| 类别 | 条目 |
|---|---|
| **事实**（可直接复验） | §0.1 三处前提错误、§1 全部 15 问、§2 全部分类、§3 全部缺陷、§3.1 |
| **推断**（多事实推导） | §4.2 Route 1 的候选装载退化、§4.3 Route 2 的收益/代价 |
| **建议**（工程判断） | §0.2 采用 Route 2、§2.7 DEPRECATED 标记范围、§4.5 职责边界、§4.6 选项 B、§5.1 不引入 OCR、§5.2 不重写 chunker |
| **已实现能力** | §2.1 |
| **测试专用能力** | §2.3 |
| **DEPRECATED 建议** | §2.7 |
| **DEFERRED** | sqlite-vec 生产接入（`docs/FINAL_REPORT_PHASE6_ROUND2_DESKTOP.md:16` 自述 "生产接入 DEFERRED"） |
| **NOT IMPLEMENTED** | §2.6 |

---

## 8. 下一步

`[事实]` Phase A（审计）完成时未修改生产代码。**Phase A2 已修改生产代码**（D1/D11 加固，见 §3.2），并附回归测试。

`[事实]` 两项待决事项已决策：`RetrievalPolicy` → 选项 B（§4.6）；`prev`/`next` → 不落持久列（§5.2）。

`[事实]` 实施顺序：

```
Phase A   审计                            ✅ 已完成（§0-§5、§6、§6.4）
Phase A2  Retrieval Safety Hardening      ✅ 已完成（D1 / D11 CLOSED，§3.2）
Phase B   摄入：PDF baseline + profiling
          + classification + recovery     ✅ 已完成（D7 / D19 / D20 CLOSED，§6.2）
Phase C   检索：orchestrator + reranker
          + context expansion
          + EvidencePack                  ✅ 核心已完成（§6.5）；消费路径统一未做
Telemetry RAG 计数器聚合                    ✅ 已完成（§6.6）
Phase D   初始证据可引用（seed_evidence）  ✅ 已完成（§6.7）
Phase E   eval + telemetry                ⏸ 待开始
```

`[事实]` D13（`RetrievalPolicy` 职责收窄）**已完成**，见 §6.4。Phase B 无剩余待办。

`[事实]` 回归证据：Phase A2 后 **1182 passed / 9 skipped**；Phase B 后 **1201 passed / 11 skipped**；D13 后 **1204 passed**；Phase C 后 **1233 passed**；telemetry 后 **1244 passed**；Phase D 后 **1250 passed / 11 skipped / 0 failed**。

`[建议]` 每阶段跑对应回归测试，无回归证据不得进入下一阶段。

### 8.1 Phase B 前需完成的验证 —— 已完成

`[事实]` §6 列出的三项已在 dev venv 与**实际发布运行时**上实测完成，结果见 §6.1。

`[事实]` 结论对 Phase B 的直接影响：

1. **PDF 分类不能依赖 PyMuPDF 专有信息**。发布产物只有 pypdf，它能给出的逐页信息仅限**页数 + 每页文本字符数**。需求书 §4 列出的逐页 `text_blocks` / `image_count` / `image_coverage` 在发布产物上**无法获得**。
2. **`heading` / `table` / `figure` 块在发布产物上对 PDF 永不产生**。[chunking.py](../src/mathtutor/infrastructure/chunking.py) 的 structure-aware 能力对 PDF 实际只在**文本层内部**生效（`例/解/证明/定义/定理` 等中文标记走 `_split_plain_roles`，不依赖块类型）。
3. ~~**MinerU 回退链断裂**（D20）~~ —— **已于 Phase B 修复**。MinerU 可达性不再依赖 baseline parser 的选择；无文本层文档现在在任何 baseline 下都会进入 optional recovery，失败则诚实落到 `needs_ocr`。**注意：修复可达性 ≠ OCR 已实现。**
4. **embedding 在发布产物上不可用**（`forbidden_feature_packages` 移除全部后端）→ 发布形态下**观测到的是**词法路径。但这**不得反向污染 domain/application 契约**：Phase C 的 `RetrievalMode` 仍保留 `lexical | hybrid`，telemetry 记录"实际发生了什么"（`vector_available=false` / `degraded_reasons`），而不是删掉架构能力。详见 §6.3。

`[事实]` **D19 已决策为选项 B**（2026-09-19），冻结声明见 §6.2。

`[事实]` 一处口径修正：页级 `text_chars == 0` **不得**命名为 "SCAN 页"。只有 pypdf 时能证明的仅是"该页没有可提取文本层"，它同样可能是空白页、图形页、纯矢量页、解析器无法解码的字体页。数据模型使用事实型状态 `TEXT_LAYER` / `NO_EXTRACTABLE_TEXT`，文档级使用 `TEXT_PDF` / `MIXED_TEXT_LAYER_PDF` / `NO_TEXT_LAYER_PDF`。UI 可以说"可能需要 OCR"，底层不断言其为扫描件。
