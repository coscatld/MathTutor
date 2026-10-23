# 002 发布前 PDF 修复与独立验证

时间：2026-10-24 01:06（北京时间）。本附件对应 `002-发布前验收与部署.md`，由 PDF 子任务记录；不代表全项目或部署已经通过。

## 问题证据与修复

此前全量失败中的两项 PDF 用例已在 HEAD 基线复现。本轮针对实际原因修复，没有删除测试或放宽原断言。

1. `tests/test_pdf_classification.py:231` 的 baseline 页面测量测试原来自动选择环境中安装的 PyMuPDF，后者确实提供 `image_count=0`，与测试要求的 pypdf 未测量值 `None` 冲突。现在显式通过现有 `_pymupdf` 接缝选择 pypdf，并新增 parser_id 断言；原有 `image_count is None` 和不伪造版式测量的断言保留。
2. `src/mathtutor/infrastructure/document_parser.py:559` 原页面字号统计按 span 计票、偶数取上中位数。标题和正文各一个 span 时，24/10 的基准错误地取成 24；多个短标题也可以压过占页面大多数文字的正文。现改为按非空白字符数计算中位数，偶数取两个中心值的均值；按权重累计，不为每个字符分配一个字号对象。忽略空白、非正数、NaN/inf 和无法解析的字号。
3. `document_parser.py:278`、`:625` 原先用块中最大的字号判断整个块是否为标题，正文只有一个 24pt 首字、其他内容为 10pt 时也可能误报。现使用块内同样的字符加权中位字号，保留公式优先、单行、80 字符和原有字号比例条件。
4. 原 rich 标题 fixture 用默认 Helvetica 写入中文，实际提取为占位点。现在使用 PyMuPDF 自带的 `china-s` CJK 字体，正文放在有明确边界的文本框中并断言没有溢出；验证完整中文标题和正文确实提取成功。字体选择依据：[PyMuPDF Page 字体文档](https://pymupdf.readthedocs.io/en/latest/page.html#Page.insert_font)。
5. `PARSER_VERSION` 升至 `mt-local-parser-v4`，使新解析结果和发布清单标明新的结构提取语义。没有执行数据迁移或批量重解析。

仅修改生产文件 `src/mathtutor/infrastructure/document_parser.py` 和测试文件 `tests/test_pdf_classification.py`，新增专门 API 回归 `tests/test_pdf_reparse_upgrade.py`。本附件为新增记录文件。

## 回归业务覆盖

新增真实 PDF 回归涵盖不同标题长度和 24/10、18/12、16/11 的字号组合；同字号、差异不足的字号、小号图注、标题文字占多数的稀疏页面不凭字号推断出标题。另覆盖多个短标题与长正文、混合字号的大首字段落，并验证解析出的标题路径能传入现有 `TextChunker`。所有数据均在测试临时目录生成，无真实个人文档、模型调用或云 OCR。

先只加入 fixture/测试修正而保持旧生产算法，实跑 **3 failed、27 passed、7 warnings（0.53s）**，失败分别是 16/11 的两块标题、多个短标题、大首字段落。生产修复后同组实跑 **30 passed、7 warnings（0.47s）**。这表明新断言能捕获真实旧行为，不是只验证函数存在。

## 测试命令与真实结果

rich 环境：macOS arm64、conda Python 3.11.15、PyMuPDF 1.28.2、pypdf 6.15.0。以下命令工作目录均为 MathTutor 仓库。

```sh
PYTHONPATH=src <USER_HOME>/miniconda3/envs/deeptutor/bin/python -m pytest \
  tests/test_pdf_classification.py -q --disable-warnings
```

结果：**30 passed、7 warnings，0.47s**。

```sh
PYTHONPATH=src <USER_HOME>/miniconda3/envs/deeptutor/bin/python -m pytest \
  tests/test_pdf_classification.py tests/test_document_pipeline.py \
  tests/test_embedding.py tests/test_release_config.py \
  tests/test_phase6_retrieval.py tests/test_phase6_retrieval_metadata_first.py \
  tests/test_phase6_retrieval_reranker.py tests/test_retrieval_safety.py \
  tests/test_retrieval_orchestration.py tests/test_agentic_retrieval.py \
  tests/test_rag_acceptance_e2e.py \
  --deselect=tests/test_rag_acceptance_e2e.py::test_e2e5_no_embedding_real_baseline \
  -q --disable-warnings
```

结果：**174 passed、4 skipped、1 deselected、74 warnings，2.91s**。四个跳过项来自 `test_phase6_retrieval_metadata_first.py`，需要此机器当前没有的 `/tmp/sqlite_vec_probe` dylib。一个 deselected 项明确要求环境没有 sentence_transformers，而 conda 环境已安装；该项在下一条打包运行时命令中原样执行通过，未改断言。

打包 runtime：`.runtime/python-mac-arm64-064/bin/python3.11`，Python 3.11.17，无 PyMuPDF 和 sentence_transformers。沿用上一轮独立临时 pytest 工具 shim，仅链接 pytest、pytest_asyncio 及纯 Python 工具依赖，不注入 conda 整个 site-packages；未安装包、修改打包 runtime 或访问用户 Keychain。`tests/conftest.py` 提供测试数据和 secret store 隔离。

```sh
PYTHONNOUSERSITE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
PYTHONPATH='<TEST_TMP>/mathtutor-clean-pytest-_5rt9khn:src' \
.runtime/python-mac-arm64-064/bin/python3.11 -m pytest \
  -p pytest_asyncio.plugin \
  tests/test_pdf_classification.py tests/test_rag_acceptance_e2e.py \
  -q --disable-warnings
```

结果：**27 passed、11 skipped、39 warnings，2.01s**，其中完整 RAG 文件的 8 项全部执行通过；11 项跳过均为明确需要可选 PyMuPDF 的 rich 用例，不能视为打包运行时支持 rich 能力的证据。上述不同命令有重复用例，不相加作为独立覆盖数量。

`git diff --check`：通过。

独立代码复核：`ui_experience` agent 只读检查最终生产/测试差异与新增 HTTP 回归，未发现新增发布阻塞；核对了双中位秩计算、非法字号过滤、按 span 存储权重、分类调用更新、真实中文提取及分块路径断言。该 agent 未重复运行测试，测试数字以上述实际命令为准。

## 旧文档重新解析的实际路径

代码链路核查：`web/features/math-tutor/desktop/lib/desktop-api.ts:399` 的 `reparseDocument` 调用 `PUT /api/v2/math-tutor/desktop/documents/{document_id}`；`src/mathtutor/api/desktop_api.py:1670` 解析身份和 owner 后调用 `DocumentIngestionService.reparse`。服务重新读取已存 PDF 原始字节，执行当前 parser、分块、写入 parser_version，并按现有流程处理可选向量索引。ready PDF 也允许调用，原来禁用检索的状态保留。该路径需要当前用户的有效会话，或产品已允许的本地桌面 loopback 身份，不应绕过认证。

界面边界：`DocumentRow.tsx:85` 当前仅在 `failed` / `needs_ocr` 状态显示“重新解析”。所以已有 ready PDF 目前有后端/客户端方法可用，但没有直接可见按钮。此便利入口留下一轮，本次没有改前端或索引生命周期。

“我的数据 → 重建派生索引”调用 `DataLifecycleService.rebuild_derived_indexes`，只从已存 chunks 重建 vectors，不会重新解析或重新分块。同字节文件重新导入会按 owner + content_hash 返回旧文档，不能替代重新解析。需要升级旧 ready 文档时，可由已有身份上下文显式调用上述 PUT；不要把普通 reindex 或重复导入当作已经更新标题。

为验证上述路径，新增 `tests/test_pdf_reparse_upgrade.py`：真实生成中文 PDF，以 pypdf + v3 身份创建已有文档，然后恢复当前 rich parser + v4；先证明同字节重复导入仍保留旧版本，再通过真实 HTTP PUT 证明 parser_version 更新为 v4、SQLite 分块的 section 变成“配方法”、原禁用检索状态不变。原文件不变，数据库与文件均位于测试临时目录，使用 `tests/conftest.py` 隔离。

```sh
PYTHONPATH=src <USER_HOME>/miniconda3/envs/deeptutor/bin/python -m pytest \
  tests/test_pdf_reparse_upgrade.py -q --disable-warnings
```

最终结果：**1 passed、13 warnings，0.92s**。此项在主联合测试之后新增并单独验证。临时原型首跑的业务断言已通过，但测试自身的 `sqlite3.connect` 上下文没有关闭探测连接，导致应用退出时报告 sidecar 残留；保留版本使用 `contextlib.closing` 正确释放所有探测连接后通过，未修改生产 shutdown 检查。

## 边界与后续

- 修复的是字号统计与代表字号选择，不是通用语义标题识别器。页面文字主要由大标题组成时，无法可靠估计正文基准，按保守策略不凭字号判为标题；已有对应真实 PDF 用例。
- 原有短句以冒号结尾的标题启发式保留。当前页面字号统计仍包含表格文字，密集小字号表格可能影响正文基准；未宣称这些既有边界已经解决。
- 当前索引有效性比较文档已存的 parser_version。提升常量不会自动重解析旧文档；旧 rich 文档需要显式重新解析，之后才记录 v4 并按新签名构建索引。本次没有操作已有用户文档。
- 仅在本机 macOS arm64 运行上述测试；Windows/Linux、外部 OCR、真实模型检索质量、视觉版式识别准确率和部署状态未由本附件验证。
