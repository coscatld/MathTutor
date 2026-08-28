# CURRENT STATE — DEFERRED

RC 仍使用 lexical-first；没有 concrete embedding model 被安装、下载、
bundle 或设为默认。Optional signed resource pack 只是推荐的候选分发
形态，未通过模型质量、许可、跨平台和人工批准门。sqlite-vec
也是独立的 optional decision，不在生产默认路径。

# ADR: MathTutor Embedding 分发策略

- 状态：**PROPOSED / DEFERRED**
- 日期：2026-08-26
- 范围：embedding 模型获取、本地/远程运行与桌面分发；同时记录但不捆绑 sqlite-vec 索引决策
- 前身：docs/ADR_EMBEDDING_DISTRIBUTION_DRAFT.md（本文取代该草稿作为当前决策记录）
- 本轮权限：仅评估和 ADR；未安装、下载、打包或切换任何 production embedding backend

## 1. Decision summary

**决策仍为 DEFERRED。** 当前没有足以支持模型级选型的真实中文数学质量、资源占用、跨平台打包和许可实测证据。

1. RC 默认保持 EmbeddingRuntime(None)，metadata-first + lexical + LexicalScoreReranker 是永久可用底座。
2. 不选定具体模型、推理格式或供应商，不改变默认 backend。
3. 分发形态的**推荐选项**是 B（用户主动安装的签名可选资源包），但只有具体模型通过本文决策门后才可接受和实施。
4. sqlite-vec 是**独立决策**：可与任意 A–F backend 搭配，也可完全不用。本轮仅确认 macOS arm64 可选 adapter 探针仍通过，生产接线仍 DEFERRED。

PROPOSED / DEFERRED 只提出后续决策顺序和门槛，不授权实施。改为 ACCEPTED 需要明确产品批准与实测证据。

## 2. Context

- deeptutor/math_tutor/domain/embedding.py 定义 EmbeddingBackend / EmbeddingDescriptor；具体 adapter 只能位于 infrastructure。
- infrastructure/embedding_runtime.py 接受一个 backend 或 None。FakeEmbeddingBackend 是确定性 64 维测试替身，**不是产品模型，也不能作为质量候选**。
- api/product_state.py 默认无 backend。无向量时产品仍可启动、解题、验证和教学，文档检索诚实退化为词法路径。
- DocumentIndexManager 从既有 chunks 产生向量；向量与 index build record 是 derived projection。换模型时从 chunks 重建，不重新导入原文件。
- infrastructure/sqlite_vec_index.py 是显式扩展路径的可选 ANN adapter，不在生产默认接线中。
- 产品是本地优先的 macOS / Windows / Linux 桌面应用；学生导入的 chunk 可能包含未成年人个人数据。

## 3. Constraints

1. domain/application 的 Protocol 与可退化语义不变；embedding 不是启动或数学权威链的前置条件。
2. metadata、owner、retrieval_enabled 过滤必须先于 embedding 和 ANN；禁用或跨 owner 文本不得进入本地模型或远程 API。
3. 模型质量与向量索引引擎分别验收；ANN 加速不能替代 Recall/MRR/nDCG 质量评测。
4. 未实测指标必须写 NOT TESTED，不以宣传数据代替产品实测。
5. 可分发产物必须版本固定、完整性校验、来源可追溯，并存档模型卡、许可文本和 third-party notices。
6. 未具备用户/监护人同意、数据最小化、TLS、供应商保留/训练/删除契约时，不得将学生 chunk 发给远程服务。
7. 每个具体模型必须在目标 macOS arm64、Windows x64、Linux x64 上分别评估；单平台通过不代表其他平台通过。

## 4. Candidates A–F

| 编号 | 候选 | 主要优点 | 主要代价/风险 | 本 ADR 判定 |
|---|---|---|---|---|
| A | bundled local model | 安装后立即离线、UX 简单、版本由产品控制 | 所有用户承担体积；许可/再分发是硬门；应用更新与重建绑定 | **拒绝作为 RC 默认**；有证据后可复评 |
| B | optional signed resource pack | 主包小；可预取后离线；版本可独立；用户知情 | 需签名、兼容 manifest、原子安装/回滚、配额和 UI | **RECOMMENDED；仍 PROPOSED / DEFERRED** |
| C | first-run downloaded model | 初始安装包小，模型可独立更新 | 首启网络失败、下载供应链、带宽/缓存；离线首启不可用 | **拒绝作为 RC 默认** |
| D | user-provided local model | 资产选择留给用户；可离线 | 格式/维度/归一化不可预测；客服复杂；恶意文件/自定义代码风险 | **专家模式候选，不作默认** |
| E | existing local inference runtime | 应用不打包权重，可复用本地加速 | 安装/版本/模型不受控；IPC；端口误配与跨用户暴露 | **高级可选，不作默认** |
| F | remote embedding API | 本地 RAM/CPU/权重体积小 | 学生文本出机；网络/费用/限流/模型漂移 | **拒绝作为 K12 默认**；另行隐私批准后才可复评 |

## 5. Complete evaluation matrix

下表评估的是**分发/运行形态**，不是尚未选定模型的实测得分。model-specific 表示必须到具体模型才能判定。

| 评估维度 | A bundled | B resource pack | C first-run | D user model | E local runtime | F remote API |
|---|---|---|---|---|---|---|
| Chinese math retrieval quality | model-specific | model-specific | model-specific | runtime/model-specific | user/model-specific | provider/model-specific |
| model size | 进主安装包 | 进可选包 | 进首启缓存 | 产品包不含 | 产品包不含 | 本地无权重 |
| RAM peak | 本地，model-specific | 本地，model-specific | 本地，model-specific | 不可预测 | 外部进程 | 本地低；服务端不透明 |
| CPU latency | 本地，model/runtime-specific | 同 A | 同 A | 不可预测 | IPC + 本地推理 | 网络 + 服务延迟 |
| startup latency | 安装后可预热 | 装包后可预热 | 首次含下载 | 每模型不同 | 依赖外部 runtime | DNS/TLS/网络 |
| batch throughput | model/runtime-specific | 同 A | 同 A | 不可预测 | 取决于外部 API | 受限流/批上限约束 |
| embedding dimension | 版本固定 | pack manifest 固定 | download manifest 固定 | 加载前校验 | 响应必须校验 | 响应必须校验 |
| license | 产品方全责 | 产品方全责 | 仍须审查使用权 | 用户提供不免除安全义务 | runtime+模型分别审查 | ToS/DPA |
| redistribution permission | **硬门** | **硬门** | 代下载仍须确认权利 | 通常不再分发 | 不得假设无需许可 | 权重不适用；受 ToS 约束 |
| offline usability | 安装即用 | 可预取后离线安装 | 首次不离线 | 用户已备才可 | runtime 已装才可 | 不可 |
| installation size | 最大且强制 | 主包小、选装后增大 | 主包小、缓存增大 | 主包小、不可预测 | 主包小、系统总占用可大 | 最小 |
| macOS packaging | 权重进签名/公证资源 | 独立签名 pack + manifest | 安全下载与 quarantine | 文件选择与 sandbox 权限 | loopback/runtime 发现 | HTTPS/API key |
| Windows packaging | 权重进签名 installer | 签名 pack + 原子更新 | 签名与 Defender 兼容 | 路径、权限、DLL/runtime 差异 | service/firewall 兼容 | HTTPS/Credential Manager |
| Linux packaging | 区分 AppImage/deb、libc/CPU | 分架构 pack + 签名/校验 | 下载、权限、发行版兼容 | 格式与 libc/CPU 不可预测 | runtime/包管理差异 | HTTPS/secret-tool |
| update strategy | 随应用发布；更新大 | pack 独立版本，易回滚 | manifest 独立更新 | 用户自管 | 外部升级不受控 | provider 可静默升级 |
| index rebuild cost | 模型/版本/维度变更即全量 chunks→vectors | 同 A | 同 A | 同 A | 同 A；外部漂移难发现 | 同 A；provider 漂移可能隐性发生 |
| user complexity | 最低 | 中：选装/更新/卸载 | 低，但需处理下载失败 | 最高 | 高 | 中：endpoint/key/费用 |
| security/privacy | 本地最小暴露；包内供应链 | 本地推理；pack 需签名 | 本地推理；新增下载供应链 | 恶意文件/任意代码风险最高 | loopback/IPC 与多用户风险 | 文本出机、未成年人隐私风险最高 |
| network dependency | 无 | 获取时有，运行时无 | 安装/更新时有 | 无 | 通常无外网 | 持续依赖 |

## 6. Measured Evidence

### 6.1 Environment and regression run

本轮实测环境：macOS 26.5.2 arm64，Python 3.11.15，SQLite 3.53.2。未访问网络，未安装或下载新依赖/模型。

复用现有 benchmark fixtures、embedding 生命周期和 sqlite-vec adapter tests：

    python -m pytest -q -s \
      deeptutor/math_tutor/tests/test_phase6_retrieval_benchmark.py \
      deeptutor/math_tutor/tests/test_embedding.py \
      deeptutor/math_tutor/tests/test_phase6_retrieval_metadata_first.py

结果：**29 passed, 4 warnings in 0.29s**；/usr/bin/time -l 外层实测 0.50 s wall time、88,866,816 bytes maximum resident set size。该 RSS 是 pytest + Python + 三组测试整体资源数，**不是某个 embedding 模型的 RAM/latency**。

### 6.2 Existing corpus/fixture audit

The current benchmark is a deterministic regression fixture, not a model-selection corpus:

| Required evidence category | Current coverage | Audit result |
|---|---|---|
| Chinese concept queries | 加法交换律、分数、方程、判别式 | **COVERED, SMALL** |
| formula-heavy text | 求根公式、判别式各一条，使用 Unicode 数学符号 | **PARTIAL** |
| mixed Chinese/LaTeX | 没有反斜线 LaTeX、环境、分式或转义命令 query | **NOT COVERED** |
| short chunks | 所有条目均为短句/单段 | **COVERED, NARROW** |
| multiple similar concepts | 交换律/结合律、分数运算/历史、一次/二次方程 | **COVERED, SMALL** |
| uploaded textbook-style text | user_document 仅有禁用/跨-owner 的单句阻断条目，不是解析后的教材段落 | **NOT COVERED** |
| User Documents relevance | 只验证阻断，不验证用户教材语义召回 | **NOT COVERED** |
| Personal Memory relevance | fixture 无 Personal Memory item/query | **NOT COVERED** |

Inventory: 11 items（9 个 owner 可见候选 + 1 禁用 + 1 跨 owner）、7 queries、二元相关、K=3/5。当前 lexical+reranker 已满分，区分度不足以比较真实模型。因此本轮不扩写或替换既有 fixture；在没有 production candidate 的情况下，新增 ground truth 也不会产生候选模型证据。未来 hard set 必须复用相同 BenchmarkQuery/RetrievalItem/metrics 契约。

### 6.3 Retrieval metrics on the existing fixture

语料：现有 11 个中文数学 RetrievalItem、7 个 query、二元相关、K=3/5；覆盖同义表达、共享关键词干扰、禁用文档、跨 owner 和 stage 过滤。

| 实际运行链路 | Recall@3 | Recall@5 | MRR@3 | MRR@5 | nDCG@3 | nDCG@5 |
|---|---:|---:|---:|---:|---:|---:|
| lexical（生产无 backend 退化形态） | 1.000000 | 1.000000 | 1.000000 | 1.000000 | 1.000000 | 1.000000 |
| lexical + FakeEmbeddingBackend | 0.500000 | 0.785714 | 0.380952 | 0.452381 | 0.428571 | 0.561714 |
| lexical + fake + LexicalScoreReranker | 1.000000 | 1.000000 | 1.000000 | 1.000000 | 1.000000 | 1.000000 |

FakeEmbeddingBackend 是 hash 伪随机向量。该结果只证明 benchmark、过滤、退化和 reranker 回归契约可运行，不证明任何 A–F 的语义质量。fixture 很小且 lexical 基线已饱和，不能支持“向量无收益”的产品结论。

### 6.4 Candidate-level evidence

本机没有已批准的 production embedding 模型、权重、本地 runtime 或远程测试凭据。因此不作估算：

| 候选 | Quality | query / batch latency | model index build | peak RAM | disk / dimension | package / cold start |
|---|---|---|---|---|---|---|
| A bundled local | **NOT TESTED** | **NOT TESTED** | **NOT TESTED** | **NOT TESTED** | **NOT TESTED** | **NOT TESTED** |
| B optional resource pack | **NOT TESTED** | **NOT TESTED** | **NOT TESTED** | **NOT TESTED** | **NOT TESTED** | **NOT TESTED** |
| C first-run download | **NOT TESTED** | **NOT TESTED** | **NOT TESTED** | **NOT TESTED** | **NOT TESTED** | **NOT TESTED** |
| D user-provided model | **NOT TESTED** | **NOT TESTED** | **NOT TESTED** | **NOT TESTED** | **NOT TESTED** | **NOT TESTED** |
| E existing local runtime | **NOT TESTED** | **NOT TESTED** | **NOT TESTED** | **NOT TESTED** | **NOT TESTED** | **NOT TESTED** |
| F remote API | **NOT TESTED** | **NOT TESTED** | **NOT TESTED** | **NOT TESTED** | **NOT TESTED** | **NOT TESTED** |

Read-only environment audit found no executable production candidate:

- product env has llama-index-embeddings-openai 0.6.0, which is a client adapter, not local model weights; no candidate endpoint/credential was authorized for this evaluation;
- no Ollama executable/running process was found;
- local Hugging Face cache contained Qwen instruction/generative models, not an approved embedding model;
- generic DeepTutor config references nomic-embed-text, bge-m3 and jina-embeddings-v3, but MathTutor does not wire them, corresponding weights/runtime/credentials were absent, and none was nominated as an approved candidate.

Therefore query/batch embedding latency, embedding-driven index build, model RSS/size/dimension, desktop package delta and cold-start impact remain NOT TESTED. The FakeEmbeddingBackend metrics above are test-harness evidence only.

### 6.5 Discovered model leads — not nominated or runnable

These names are present in the broader repository configuration. They are **not recommendations** and no online benchmark or license claim is imported:

| Lead | Local evidence | Model license | Weights redistribution | Commercial / competition use | Attribution | Packaging constraints |
|---|---|---|---|---|---|---|
| nomic-embed-text | generic Ollama preset only; runtime/weights absent | **LEGAL/LICENSING REVIEW REQUIRED** | **LEGAL/LICENSING REVIEW REQUIRED** | **LEGAL/LICENSING REVIEW REQUIRED** | **LEGAL/LICENSING REVIEW REQUIRED** | **NOT TESTED** |
| bge-m3 | generic provider keywords only; weights absent | **LEGAL/LICENSING REVIEW REQUIRED** | **LEGAL/LICENSING REVIEW REQUIRED** | **LEGAL/LICENSING REVIEW REQUIRED** | **LEGAL/LICENSING REVIEW REQUIRED** | **NOT TESTED** |
| jina-embeddings-v3 | remote provider preset only; no credential authorized | **LEGAL/LICENSING REVIEW REQUIRED** | n/a for API weights; ToS review required | **LEGAL/LICENSING REVIEW REQUIRED** | **LEGAL/LICENSING REVIEW REQUIRED** | remote API/DPA/privacy review required |

An actual candidate enters the measured table only after exact upstream revision, artifact hash, runtime and authoritative license files are captured locally.

### 6.6 sqlite-vec evidence (separate from model evidence)

本轮对已存在的 /tmp 评估 artifact 重跑，未下载、安装或改动产品：

| 项 | 实测结果 |
|---|---|
| artifact | sqlite-vec 0.1.9 macOS arm64 wheel 165,434 bytes；vec0.dylib 161,896 bytes |
| hashes | wheel SHA-256 1d52e30513bae4cc9778ddbf6145610434081be4c3afe57cd877893bad9f6b6c；dylib SHA-256 193e480c50b59a55977d166f4aaf0e1bc8832d6963516e5950f39e4d2ce0b793 |
| binary / linkage | Mach-O 64-bit arm64；除自身 install name 外仅链接 /usr/lib/libSystem.B.dylib |
| load / ABI | load_extension + vec_version() 成功；adapter correctness tests 通过 |
| dimension | 本轮用 64 维实测；adapter 由构造时 schema 固定并 fail closed 校验 |
| cold extension load | p50 0.584396 ms，p95 0.623875 ms，n=30 |
| rebuild | 11 items × 64 维：p50 0.363501 ms，p95 0.378333 ms，n=100 |
| KNN query | k=5，11 items × 64 维：p50 0.035375 ms，p95 0.035834 ms，n=1000 |
| probe process memory | 62,291,968 bytes max RSS；包含 Python、fake 向量生成和微基准，不是 sqlite-vec 增量 RSS |
| Windows / Linux / macOS x64 ABI | **NOT TESTED** |

这些数据只是小 fixture 上的 adapter 功能/延迟探针，不是大规模 ANN 容量评测，也不包含 embedding 推理时间。

### 6.7 Full local cosine vs sqlite-vec scale probe

Reproducible evaluation-only command:

    python scripts/math_tutor_vector_index_benchmark.py

The script runs each case in a fresh process, generates deterministic L2-normalized synthetic vectors, and compares the current Python cosine_similarity kernel with the existing optional adapter **after metadata filtering**. It does not use or simulate an embedding model. Defaults: sizes 100/1,000/5,000; dimensions 64/384/768; 10 queries per case; k=5.

| Items | Dim | full cosine query p50/p95 ms | sqlite-vec query p50/p95 ms | sqlite build ms | case max RSS | exact top-k match |
|---:|---:|---:|---:|---:|---:|---|
| 100 | 64 | 0.165708 / 0.179166 | 0.036708 / 0.057583 | 2.469584 | 61,669,376 B | yes |
| 100 | 384 | 0.839499 / 0.868791 | 0.177541 / 0.317459 | 12.058834 | 66,535,424 B | yes |
| 100 | 768 | 1.624563 / 1.676292 | 0.468730 / 0.614417 | 23.578500 | 72,302,592 B | yes |
| 1,000 | 64 | 1.627395 / 1.682750 | 0.059916 / 0.095667 | 22.719167 | 65,110,016 B | yes |
| 1,000 | 384 | 8.242770 / 8.343083 | 0.333604 / 0.481208 | 118.983875 | 90,259,456 B | yes |
| 1,000 | 768 | 16.151958 / 16.340291 | 0.836292 / 1.220833 | 235.941667 | 120,061,952 B | yes |
| 5,000 | 64 | 8.096521 / 8.227125 | 0.184188 / 0.231625 | 112.201500 | 84,115,456 B | yes |
| 5,000 | 384 | 41.549479 / 41.747625 | 1.250854 / 1.361500 | 597.963208 | 198,803,456 B | yes |
| 5,000 | 768 | 80.209583 / 83.033042 | 3.007312 / 4.285917 | 1,240.900167 | 324,534,272 B | yes |

Method limits:

- full-scan “build” is only tuple materialization (0.000292–0.026333 ms) because both kernels receive already generated, metadata-filtered in-memory vectors; it excludes SQLite row fetch/JSON decode;
- sqlite build includes JSON serialization and insertion into the adapter's private in-memory vec0 table;
- max RSS includes Python object vectors and sqlite-vec; it is not an incremental extension-only figure;
- synthetic-vector ranking equivalence and kernel speed do not establish Chinese retrieval quality or persistent production integration.

**Measured conclusion:** sqlite-vec provides a clear query-kernel speedup at every tested case, becoming material at 1,000–5,000 vectors and 384–768 dimensions. However, full cosine remains 0.17–1.62 ms at 100 items and 1.63–16.15 ms at 1,000 items. Actual per-user visible chunk counts, query concurrency, persistent-index lifecycle and non-macOS distribution are not yet measured. The evidence supports retaining sqlite-vec as an optional optimization and defining a data-volume/latency activation gate; it does **not** justify enabling it by default.

## 7. Security and privacy

### Local candidates (A–E)

- 资产必须来自固定源；manifest 含 model ID/version、dimension、normalization、runtime compatibility、size 和 SHA-256。签名/散列失配时 fail closed，不覆盖当前可用 pack。
- 安装先写临时目录，完成完整性/兼容性校验后原子激活；保留上一版直到新索引成功。
- 加载器不得执行资产中的任意代码、插件、脚本或 trust_remote_code 类能力。E 仅接受 allowlist 的纯数据格式和受控 runtime。
- E 只允许显式 loopback/IPC 目标，需 endpoint allowlist、版本/维度探针和超时；不使用学生输入作为 endpoint，不扫描局域网。
- 向量仍是用户文档的 derived personal data，须 owner 隔离；删除文档时一并删除向量/索引。

### Remote candidate (F)

- 只发送 metadata-first 过滤后的最小文本；不发送 student ID、文件路径、API key、mastery、Personal Memory 或无关 chunks。
- 必须有用户/监护人明示 opt-in，展示供应商、数据类别、保留/训练/删除政策与成本；opt-out 后停止发送新文本。
- 需 TLS、SecretStore、有界超时/重试/限流，日志禁止原文和向量。provider 失效退化为 lexical，不阻断教学。
- provider 静默升级会破坏索引语义；必须获得稳定 model/version 标识，否则 F 不可接受。

### User Documents / Personal Memory data movement

| Shape | User Documents leave device? | Personal Memory leave device? | Required control |
|---|---|---|---|
| A bundled local | no | no | local owner filtering; no telemetry payloads |
| B optional resource pack | no; only signed model artifacts enter device | no | pack download must never upload corpus/fingerprints |
| C first-run download | no; only model artifacts should enter device | no | downloader separated from retrieval data path |
| D user-provided local | no | no | file allowlist; no arbitrary model code |
| E existing local runtime | no if strictly loopback/IPC | no if strictly loopback/IPC | endpoint allowlist and same-user access control |
| F remote API | **yes, selected chunks/queries** | **yes if enabled; therefore default must forbid it** | guardian/user opt-in, purpose limitation, DPA/retention/deletion review |

The current MathTutor metadata-first filter remains mandatory before either User Documents or Personal Memory could reach any embedding backend. For F, the safe initial policy would be User Documents opt-in and Personal Memory FORBIDDEN until a separate privacy decision approves it; this is a policy recommendation, not implementation.

## 8. Packaging and license gates

每个具体“模型 + runtime + tokenizer + 可选 sqlite-vec”组合须完成 SBOM 级清单：上游 URL/revision/hash、SPDX/许可原文、商业使用、修改、再分发、归属/NOTICE、用途限制和出口限制。“开源代码许可”不自动等于“模型权重可再分发”。

本轮未指定模型，故 A–F 的模型许可与再分发权均为 **NOT TESTED**。该列为 NOT TESTED 时不得生成对外发行物。

sqlite-vec 本地 wheel metadata 标记“MIT License, Apache License, Version 2.0”，但 metadata 同时含 TODO 主页/说明；这只是本地包 metadata 读数，**不是完成的法务/NOTICE 审查**。若分发二进制，须从上游固定 tag 核对完整 LICENSE/NOTICE 并纳入 third-party notices。

| Shape | Model/runtime license | Weights redistribution | Commercial/competition use | Attribution | Packaging constraint |
|---|---|---|---|---|---|
| A bundled | **LEGAL/LICENSING REVIEW REQUIRED** | explicit permission required | **LEGAL/LICENSING REVIEW REQUIRED** | preserve all required notices | installer, SBOM and notices carry all assets |
| B resource pack | **LEGAL/LICENSING REVIEW REQUIRED** | explicit permission required | **LEGAL/LICENSING REVIEW REQUIRED** | pack-local plus product notice | signed, versioned pack is still product redistribution |
| C first-run | **LEGAL/LICENSING REVIEW REQUIRED** | product-mediated download rights must be confirmed | **LEGAL/LICENSING REVIEW REQUIRED** | downloader must surface required notices | pinned source/hash; cache and removal policy |
| D user model | **LEGAL/LICENSING REVIEW REQUIRED** | product does not redistribute weights, but loader/runtime terms still apply | **LEGAL/LICENSING REVIEW REQUIRED** | user and product obligations unresolved | allowlisted data-only formats; no arbitrary code |
| E local runtime | runtime and selected model both **LEGAL/LICENSING REVIEW REQUIRED** | depends on who installed/provisions the model | **LEGAL/LICENSING REVIEW REQUIRED** | runtime/model notices separate | supported version/API matrix |
| F remote API | provider ToS/DPA **LEGAL REVIEW REQUIRED** | n/a for weights | **LEGAL/LICENSING REVIEW REQUIRED** | provider branding/citation terms unresolved | endpoint/version stability and data-processing contract |

## 9. Optional model pack manifest prototype

This is a documentation-only schema sketch. It is explicitly:

**NOT DEFAULT / NOT PRODUCTION / NOT BUNDLED INTO RC**

    {
      "schema_version": "1",
      "status": "NOT_PRODUCTION",
      "pack_version": "0.0.0-evaluation",
      "backend_id": "candidate-backend-id",
      "model_id": "candidate-model-id",
      "model_version": "exact-upstream-revision",
      "dimension": 0,
      "normalization": "l2",
      "sha256": "REQUIRED_EXACT_ARTIFACT_HASH",
      "license_id": "LEGAL_REVIEW_REQUIRED",
      "min_app_version": "REQUIRED",
      "platform_arch": ["macos-arm64"],
      "index_compatibility": {
        "signature_version": "REQUIRED",
        "chunker_version": "REQUIRED",
        "parser_version": "REQUIRED"
      },
      "distribution_flags": {
        "default": false,
        "production": false,
        "bundled_into_rc": false
      }
    }

Before implementation, the final manifest also needs artifact byte size/path list, signature/key ID, runtime/tokenizer revisions, commercial/redistribution/attribution fields, supported app-version upper bounds or migration policy, CPU feature requirements and an atomic rollback target. A zero dimension, placeholder hash or unresolved license must fail validation.

## 10. Performance acceptance plan

不凭感觉冻结 SLO。每个具体模型、每个平台都要用同一 fixture 接口记录：

- 质量：Recall@3/5、MRR@3/5、nDCG@3/5 和逐 query ranking；可增加兼容的中文 K12 hard set，但不替换现有回归 fixture。
- 延迟：冷启动/首 query、热 query p50/p95，以及 1/8/32 文本批处理 p50/p95。
- 吞吐：texts/s 和 tokens/s，并记录文本长度、批大小、CPU、线程数。
- 资源：权重/tokenizer/runtime 字节数、安装增量、空载/冷启动/稳态峰值 RSS。
- 稳定性：断网启动、损坏/不完整 pack、磁盘不足、runtime 崩溃、API 限流/超时和用户取消。

质量 gate 先于性能 gate。当前 fixture 的 lexical+reranker 已满分，因此决策前需要更有区分度的兼容 hard set。

## 11. Migration and index rebuild

1. 启用新 backend 前先安装、校验、健康探针和小批 embedding；失败时保留旧 backend 或 lexical。
2. IndexBuildRecord 当前以 backend ID、model ID/version、dimension、chunker version、parser version 判断 stale。任一改变即从已有 chunks 重算，index_version + 1；不重新解析原文件。
3. 重建完成前不激活新 backend。实现时应使用临时 generation 或可回滚机制，避免混用新旧向量。
4. 重建是有界、可取消、可恢复、可观测的 derived job；失败不删 chunks，检索退化到 lexical。
5. 用户删除/禁用文档优先于重建任务；任务开始和提交前均须重查 owner/可检索状态。
6. 重建成本不能只看 ANN build，主要成本通常是 embedding。A–E 记录 CPU/RAM；F 记录请求数、限流、费用和出机数据量。

已知契约空白：EmbeddingDescriptor.index_signature() 含 normalization，但 IndexBuildRecord.matches_signature()/schema 不持久化 normalization 或 runtime version。production 实施前必须决定并测试两者是否进入 persisted rebuild signature；本文不授权修改 schema。

## 12. sqlite-vec decision (independent)

sqlite-vec 只决定“向量生成后如何查找近邻”，不生成 embedding、不决定中文质量、不替代 metadata-first 过滤和 reranker。

当前结果：

- macOS arm64 + Python 3.11.15 + SQLite 3.53.2 + sqlite-vec 0.1.9：load/version/KNN/rebuild tests 通过。
- 二进制分发、Windows/Linux/macOS x64 ABI、打包后扩展路径、签名/公证、备份/恢复和大规模容量：**NOT TESTED**。
- 现有 adapter 使用实例私有 :memory: 连接，不是持久化生产索引接线。

**推荐仍为 PROPOSED / DEFERRED**：保留 adapter 与 lexical/full-scan fallback，不进入 RC 默认接线。只有真实 corpus 证明 full scan 不足，且目标平台二进制门全部通过时才接入。

推荐 B 不意味着必须选 sqlite-vec；选 sqlite-vec 也不意味着必须选 B。sqlite-vec 二进制可随应用或独立 index pack 分发，那是其自身 packaging 决策。

## 13. Recommendation

1. 保持 RC lexical-first 默认，不把 embedding 当 RC blocker。
2. 在不改 Protocol 的前提下，选择少量许可清晰的中文/多语数学模型，仅做可重复 offline evaluation。
3. 若有模型通过质量、资源、许可和三平台 gate，推荐 **B: signed optional resource pack** 试点；告知体积，装后完全离线，卸载后回到 lexical。
4. D/E 保留为高级可选适配，不转嫁给默认 K12 用户。
5. F 另起隐私/合规决策；未通过前不实施。
6. 模型通过后再以真实向量数量评估 full scan 与 sqlite-vec，不预设 ANN 是必需依赖。

## 14. Rejected alternatives (current RC)

- 拒绝 A 作为 RC 默认：无质量/体积/RAM/许可/三平台证据，不应让全部用户承担强制资产。
- 拒绝 C 作为 RC 默认：首启网络依赖与本地优先/学校网络冲突，并新增下载供应链。
- 拒绝 D/E 作为主产品路径：安装、格式、版本和支持复杂度不适合默认 K12 UX。
- 拒绝 F 作为 K12 默认：不能为未证明的收益默认让学生文本出机。
- 拒绝“选模型 = 选 sqlite-vec”：两者分别解决向量生成和近邻查找。
- 拒绝用 FakeEmbeddingBackend 代表生产质量：它只服务确定性测试。
- 拒绝从 11-item fixture 的满分宣称“embedding 无用”：它是回归钉，不是充分的产品样本。

## 15. Open questions

1. 哪些具体模型在中文 K12 数学同义、公式、中英混排和 OCR 噪声上优于 lexical+reranker？
2. 如何扩展兼容 hard set，使其足以区分模型又不破坏既有 benchmark 契约？
3. 目标低配 CPU/RAM/磁盘预算和可接受冷启动时间是多少，应在哪些真实设备冻结？
4. resource pack 的签名格式、manifest schema、安装目录、配额、原子激活和回滚机制是什么？
5. 模型/runtime/tokenizer 的商业使用与权重再分发条款是否全部通过审查？
6. normalization 和 runtime version 是否必须纳入持久化 index signature/schema migration？
7. 多文档重建是否需要可恢复 job table，还是单用户规模可由现有 build record 幂等重跑？
8. 什么样本量/延迟拐点才证明 sqlite-vec 相对 Python full scan 有净收益？
9. sqlite-vec 在 Windows x64、Linux x64、macOS x64 的 ABI、打包路径、签名/公证和备份/恢复是否通过？
10. F 需要什么法律/隐私基础，如何实现监护人同意、删除和 provider 不训练保证？

## 16. Decision gate and future acceptance checklist

Current gate:

| Gate | Current value | Reason |
|---|---|---|
| MEASURED_EVIDENCE_COMPLETE | **false** | no runnable production model candidate; corpus gaps remain |
| LICENSE_REVIEW_COMPLETE | **false** | all concrete model leads require authoritative license review |
| CROSS_PLATFORM_PLAN_COMPLETE | **false** | model/runtime and sqlite-vec Windows/Linux evidence absent |
| HUMAN_APPROVAL | **false** | no explicit manual approval was provided |

Therefore the decision status is and must remain **PROPOSED / DEFERRED**. Recommendation B does not authorize a dependency, download, resource pack, production backend, vector default or sqlite-vec default.

- [ ] 固定 model/runtime revision 与 artifact hash
- [ ] 中文 K12 Recall/MRR/nDCG 及逐 query 结果
- [ ] 三平台冷/热延迟、批吞吐、峰值 RAM、产物/安装体积
- [ ] 断网、损坏资产、磁盘不足、升级、回滚和卸载 smoke
- [ ] 许可、权重再分发、NOTICE/SBOM 和模型卡审查
- [ ] 隐私/安全威胁建模；F 另需合规和明示 opt-in
- [ ] index signature/migration/rebuild 与 lexical fallback 回归
- [ ] sqlite-vec 若启用，单独提供三平台 ABI/packaging/容量证据；若不启用，记录 full-scan 容量证据
