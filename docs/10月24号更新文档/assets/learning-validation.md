# 学习证据与打包运行时验收记录

记录时间：2026-10-24 00:40（Asia/Shanghai）。本记录覆盖后端学习证据投影，以及独立复查的备份保留与无嵌入模型 RAG 验收；不替代前端视觉验收记录。

## 发现的问题与实际修复

学习画像的产品定位是：记录学生已经完成的可核验作答，区分独立完成与受助表现，并指向下一次新题验证。

修复前，在真实内存 SQLite 的 `StudentStateService.record_attempt` 中写入一条单技能、正确的选择作答，事件的 `independent_target=False`，但 `evidence_summary` 将其计为一次独立正确，`baseline_prediction` 从 0.5 变为 0.6667。公开画像同时出现 `has_independent_evidence=False` 和独立正确次数为 1。推荐练习结果的另一条投影也未排除选择作答和同题重试。

实际调用与修改路径：

- `src/mathtutor/application/controller.py`：真实选择练习提交保留 `response_format=single_choice`；该入口未修改。
- `src/mathtutor/learning/knowledge_tracing/events.py`：新增只读的 `evidence_category` 分类，汇总总量与逐技能统计共用此分类；独立资格使用既有 `independent_target`。
- `src/mathtutor/application/evidence_projection.py`：公开计数使用相同分类，`unknown` 投影为现有 `ungradable` 字段。
- `src/mathtutor/application/practice_offer_view.py`：推荐结果中的独立正确次数使用 `independent_target`，不再接纳选择作答或同题重试。
- `tests/test_learning_evidence_consistency.py`：新增边界、真实存储、画像一致性、跨会话重试、排除证据与推荐卡回归。
- `tests/test_initial_assessment.py`：在既有 WebSocket 选择练习流程后，验证 HTTP 画像和推荐卡的公开结果。

分类顺序为：非评估或重复响应不计新增观察；未知结果或来源不确定进入未判定；选择题、诊断、错因分析、局部步骤和部分完成进入诊断；其余整题观察再区分看过答案、受助和首次独立自由作答。同题再次独立整题作答保留在原始历史和重复尝试统计，不增加首次独立证据。

补充组合回归明确验证 `assisted + single_choice` 与 `post_solution + subgoal` 都属于诊断，不属于独立作答。组合分类不抹去原始事件中的受助或答案暴露事实。多技能整题仍保留联合证据，不复制成每个技能的独立成功；未改变数据库事件、训练标签规则或 API 字段。

## 后端测试结果

工作目录为 MathTutor 仓库根目录。下列命令使用 Python 3.11 的既有开发环境，无外部模型调用。

```bash
PYTHONPATH=src <USER_HOME>/miniconda3/envs/deeptutor/bin/python -m pytest \
  tests/test_learning_evidence_consistency.py \
  tests/test_production_evidence_contract.py \
  tests/test_main_sync_evidence_contract.py \
  tests/test_stage_review.py tests/test_profile_resume.py -q
```

结果：**46 passed，109 warnings，4.31 秒**。这是新增两个组合参数之前的结果，覆盖真实首次提交、判断失败后的重试、阶段复盘与恢复链路。

```bash
PYTHONPATH=src <USER_HOME>/miniconda3/envs/deeptutor/bin/python -m pytest \
  tests/test_initial_assessment.py tests/test_knowledge_tracking_v2.py \
  tests/test_phase5_e2e_offer_flow.py tests/test_tutor_v2_acceptance.py \
  tests/test_teaching_v2.py tests/test_phase6_data_lifecycle.py -q --disable-warnings
```

结果：**138 passed，561 warnings，22.26 秒**。包含真实 WebSocket 选择练习、HTTP 画像与推荐卡、持久化重启、教学和数据删除链路。

新增两个组合参数后运行：

```bash
PYTHONPATH=src <USER_HOME>/miniconda3/envs/deeptutor/bin/python -m pytest \
  tests/test_learning_evidence_consistency.py -q --disable-warnings
git diff --check
```

结果：**21 passed，0.34 秒**；`git diff --check` 通过。21 项包含前一组已运行的测试，不应重复累加为新的独立用例总数。

已看到的警告包含 FastAPI 生命周期弃用和测试客户端依赖弃用，不影响上述退出码。这里记录的是工程和协议正确性，不是学生学习收益测量。

## 打包运行时 RAG 验收

开发环境安装了 `sentence_transformers`，不满足原用例 `test_e2e5_no_embedding_real_baseline` 明确要求的“该库不存在”前提。没有删库、改断言或伪造 `find_spec` 返回值。

改用仓库已有的 `.runtime/python-mac-arm64-064/bin/python3.11`（Python 3.11.17）。该 runtime 实际没有 `sentence_transformers`，具备产品依赖但没有 pytest。为运行原测试，仅在临时目录软链以下已有纯 Python 测试工具及相应分发元数据：

| 工具 | 版本或归属 |
| --- | --- |
| `pytest`、`_pytest`、`py.py` | pytest 9.1.1；`py.py` 是 pytest 自带兼容 shim |
| `pytest_asyncio` | 1.4.0 |
| `iniconfig` | 2.3.0 |
| `packaging` | 26.2 |
| `pluggy` | 1.6.0 |
| `pygments` | 2.20.0 |

初次 runner 启动缺少 `py.py`，在测试收集前出现 `ModuleNotFoundError`。确认其属于 pytest 后补充该工具文件，再运行原测试文件。没有把完整 Conda `site-packages` 加入路径，也没有安装新依赖或写入打包 runtime。

实测环境探针：

- `importlib.util.find_spec('sentence_transformers') is None` 为真。
- `sqlalchemy` 来源为 `.runtime/python-mac-arm64-064/lib/python3.11/site-packages/sqlalchemy/__init__.py`。
- `sys.path` 不包含开发环境的完整 `site-packages`。
- `PYTHONNOUSERSITE=1` 关闭用户包目录；`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` 关闭第三方插件自动加载，显式启用 `pytest_asyncio.plugin`。

实际通过命令：

```bash
PYTHONNOUSERSITE=1 \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
PYTHONPATH='<TEST_TMP>/mathtutor-clean-pytest-_5rt9khn:src' \
.runtime/python-mac-arm64-064/bin/python3.11 -m pytest \
  -p pytest_asyncio.plugin tests/test_rag_acceptance_e2e.py -q --disable-warnings
```

结果：**8 passed，37 warnings，5.86 秒**。整个文件覆盖 PDF 资料进入辅导、会话隔离、初始引用、多跳检索、无嵌入词法检索、无文字 PDF、停用/删除及未设范围时拒绝扩权。使用 `tests/conftest.py` 的内存密钥存储隔离，未访问个人 keychain。

临时 runner 路径供本次复查；系统清理临时目录后需重建工具软链。此结果只验证 macOS ARM64 的现有打包运行时和该文件的八项测试，未验证 Windows/Linux、完整打包分发或在线模型教学效果。

## 备份最终策略独立复查

只读审查 `backup.py` 与对应回归，未发现本轮新增阻塞。最终保留集合为“最新 N 个实体备份”与“最新 N 个元数据正常候选”的并集，最多 2N；正常目录仍保留 N，孤儿清单不占名额。`status=ok` 只代表清单可读和大小匹配，完整散列与 SQLite 校验仍是独立步骤。

```bash
PYTHONPATH=src <USER_HOME>/miniconda3/envs/deeptutor/bin/python -m pytest \
  tests/test_phase6_backup_policy.py \
  -k 'retention or invalid_manifest_field_types' -q --disable-warnings
```

结果：**17 passed，15 deselected，1.89 秒**。覆盖孤儿、异常清单、大小不符、缺清单、混排和全异常轮转，以及保留文件字节不变和正常候选的完整校验。

## 全量回归失败的 HEAD 基线诊断

2026-10-24 00:42 补充。主执行者的全量日志 `/tmp/mathtutor-iteration-001-full-tests.log` 记录 **4 failed、3208 passed、4 skipped、6697 warnings，235.69 秒**。本记录作者读取了该日志，并独立复核其中三项未修改模块失败；第四项为上文已在真实无嵌入 runtime 通过的环境前提用例。四个跳过项缺少 `/tmp/sqlite_vec_probe` 的本地探测库，未将跳过计为通过。

为判断是否由本轮引入，使用 `git archive HEAD` 将提交 `415b913de666ce5740dc76b8e8b89d25d647f2f5` 导出至临时目录 `/tmp/mathtutor-head-baseline-br5rntjk`。该目录不含本轮未提交修改。在该目录使用相同 Conda Python 与依赖运行：

```bash
PYTHONPATH=src <USER_HOME>/miniconda3/envs/deeptutor/bin/python -m pytest \
  tests/test_community_fetch.py::test_tls_uses_the_original_hostname_with_public_pinned_socket \
  tests/test_pdf_classification.py::test_page_profile_does_not_fabricate_measurements \
  tests/test_pdf_classification.py::test_optional_rich_parser_emits_heading_blocks \
  -q --disable-warnings
```

结果：**3 failed、5 warnings，0.40 秒，退出码 1**。三项失败位置和原因与本轮全量日志一致，确认在本轮修改前已经存在；没有改动断言、基线源码或正式源码。

| 原测试 | HEAD 基线实际失败原因 | 诊断边界 |
| --- | --- | --- |
| `test_tls_uses_the_original_hostname_with_public_pinned_socket` | 测试将 `ssl.create_default_context` 替换为只有 `wrap_socket` 的 `Context`，Python 3.11 的 `http.client.HTTPSConnection.__init__` 读取其 `verify_mode` 时触发 `AttributeError`。 | 测试替身与当前标准库契约不完整；这次未验证其后原本要检查的 TLS/SNI 行为。 |
| `test_page_profile_does_not_fabricate_measurements` | 当前 Conda 环境包含 PyMuPDF 1.28.2，`LocalDocumentParser` 优先选用 rich parser，得到 `image_count=0`；测试断言要求 baseline parser 的 `None`。 | 该断言的 baseline 前提在当前开发环境不成立，不能将此失败改记为通过。 |
| `test_optional_rich_parser_emits_heading_blocks` | 夹具产生两条字体跨度，字号分别为 24 和 10。`_page_median_size` 取排序后的上中位数 24，标题的 24 不满足 `median × 1.35` 阈值，两个块均分类为 `paragraph`。 | 属于既有可选 rich 解析启发式/夹具边界，需后续处理；不能仅归因为 baseline 环境。 |

第三项另做了只读夹具探针：默认 PDF 字体把标题“ 一元二次方程 ”和正文中的中文提取成中点，标题实际文本为 `······`。探针输出页面中位字号 `24.0`，标题和正文分类均为 `('paragraph', None)`。这些事实说明当前用例还包含中文字体夹具问题；本轮未修复或绕过它，也未宣称 rich PDF 标题能力已通过。

基线复现证明这三项不是本轮新增回归，但**全量套件仍未全绿**。后续应分别完善 TLS 测试替身、明确 PDF baseline 环境与可选 rich 能力的测试边界，并针对真实字体与字号分布验证标题识别。

## 研究启示与范围

已阅读 2026-09-23 发布的 [StudentBench 预印本全文](https://arxiv.org/html/2609.28470v1) 的方法、练习指标与局限。其学习测量使用不同题的独立后测，辅导器不能看到后测题；练习指标按不同题的首次答对计算。本文只提供“练习过程与独立新题表现分开测量”的评测原则，不能证明选择题无效，也不能代替 MathTutor 的学习效果研究。论文仅测即时增益，样本为英语成人，且无单独做题对照；本轮未宣称长期迁移或模型教学质量提升。
