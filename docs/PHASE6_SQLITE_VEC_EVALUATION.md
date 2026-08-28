# Phase 6 — sqlite-vec 便携性评估（只评估，不安装）

- 评估日期：2026-08-20
- 状态：**PARTIAL / DEFERRED**（结论见文末）
- 本文件只做评估记录；未安装、未引入任何依赖。

## 1. 背景与约束

- MathTutor 的 Embedding Distribution Strategy 为 **DEFERRED**（规格 §19/§9.2）：
  最终后端（bundled installer / first-run download / Ollama / ONNX / resource pack /
  用户自选本地模型）未定，且**禁止** bundled installer / first-run download /
  Ollama / ONNX / resource pack / remote embedding 进入本轮实现。
- 规格 §19 禁止为 MathTutor 引入新外部依赖；sqlite-vec 只能「评估、不得安装」。
- 现有架构里向量存储已被仓库 Protocol 隐藏：`document_chunk_vectors` 表以 JSON
  列保存向量，上层只依赖 `EmbeddingBackend`（domain protocol）。sqlite-vec 若接入，
  只会是 Phase 6 检索基础设施里的一个可选 adapter，不影响 domain/application 契约。

## 2. 检查了什么（已核实的事实）

| 项 | 结果 | 核实方式 |
|---|---|---|
| 本地平台 | macOS arm64（Darwin 25.5.0），Python 3.11.15 | `platform.machine()` |
| 本地 SQLite | 3.53.2（conda Python 自带） | `sqlite3.sqlite_version` |
| sqlite3 可加载扩展支持 | **ENABLED**（`enable_load_extension` 可用） | 本机实测 |
| sqlite-vec 是否已安装 | 未安装（import 失败） | 本机实测 |
| PyPI 最新版本 | 0.1.9 | `pypi.org/pypi/sqlite-vec/json`（2026-08-20） |
| wheel 覆盖矩阵（0.1.9） | macOS x86_64（10_6）、macOS arm64（11_0）、manylinux2014 x86_64、manylinux2014 aarch64、Windows amd64；均为 `py3-none-*`（纯 Python 包装 + 随包编译扩展） | PyPI JSON |
| 离线安装可行性 | **结构性可行**：wheel 是自包含二进制（.so 内嵌），`pip download` / 预取 wheel / 内嵌 wheel 后可在无网机器安装（与 DEFERRED 分发策略属于同一决策域） | wheel 形态推断，未实装验证 |
| 现有环境相关依赖 | 仓库外层产品已有 `faiss-cpu 1.15.0` + `llama-index-vector-stores-faiss`（非 MathTutor 域） | `pip list` |

## 3. 没有验证什么（诚实记录）

1. **SQLite 版本要求**：PyPI 描述为 "TODO readme" 占位；sqlite-vec 对最低 SQLite
   版本的声称（社区 README 历史上提到 3.41+ 的特性门槛）**未**与 0.1.9 实际二进制核对。
2. **扩展 ABI 兼容性**：SQLite 扩展 ABI 设计为前向兼容（旧头文件编译、新版运行时加载），
   但「0.1.9 的 .so ↔ 本环境 SQLite 3.53.2」**未实装加载验证**（禁止安装）。
3. **离线服务器实装**：Phase 6 验收要求「断网 Linux server 安装、迁移、启动、备份、
   恢复」——manylinux wheel 存在，但完整的离线 pip 流程**未实装演练**。
4. **WAL + 短事务并发行为**：与 `MathTutorUow` 短事务（单写者 + WAL）的叠加行为
   **未集成测试**；若未来接入，SQLAlchemy connect 事件（`create_db_engine` 的
   pragma 监听）是每连接加载扩展的既定挂点，但该挂点未对本扩展演练。
5. **评测面**：ANN 召回质量对 metadata-first 管线的边际收益**未评测**（没有向量，
   没有数据）。

## 4. 与 DEFERRED 分发策略的关系

- 当前生产路径**没有任何向量产生**（EmbeddingRuntime backend 为 None 时，
  `MetadataFirstRetriever` 直接降级为 metadata/词法结果并标注 `vector: "unavailable"`）。
- 没有向量 ⇒ 向量索引无事可做 ⇒ sqlite-vec 集成在现阶段没有数据面收益，只有
  引入外部二进制依赖的运维面成本。
- sqlite-vec 若未来接入，其「模型/索引文件的获取方式」与 Embedding Distribution
  Strategy 是**同一个决策**：bundled wheel 属于「bundled installer / resource pack」
  家族，与当前 DEFERRED 状态冲突。

## 5. 结论与建议

- **结论：PARTIAL / DEFERRED** —— 评估可行（本机与目标平台均有匹配 wheel，离线
  分发结构性可行，扩展加载能力已具备），但**暂不集成**：
  - 规格 §19 禁止新增外部依赖，且本轮没有向量数据可索引；
  - 集成决策应延后到 Embedding Distribution Strategy 定稿时一并做出。
- 保留本评估记录；复评触发条件：Embedding Distribution Strategy 定稿、或
  metadata/词法检索评测暴露出需要 ANN 的明确缺口。
- 若未来集成，推荐路径（供届时评审，非本轮承诺）：
  1. wheel 纳入分发决策（bundled / 预下载），明确离线安装与版本固定方式；
  2. 在 `create_db_engine` 的 connect 事件挂点按连接 `load_extension`（每连接加载，
     与 pragma 同位置），并在 `domain`/`application` 零改动的前提下由
     `document_chunk_vectors` 的仓库实现切换 adapter；
  3. 先过 Phase 6 验收线（离线安装/迁移/备份/恢复 + 评测导出），再做召回评测。

---

# 第二轮实测（2026-08-21）

- 状态：**macOS arm64 gate PASS**（ABI 实测加载成功）；生产接入仍 **DEFERRED**
- 方法：只评估。`pip download --no-deps` 到 /tmp（评估 artifact，未安装、
  未向 deeptutor 环境 pip install 任何东西），解包后一次性 `python -c`
  做 `load_extension` + 功能探针。

## 1. 实测命令与原始输出（本机真实平台）

| 项 | 输出 |
|---|---|
| `sqlite3.sqlite_version` | 3.53.2 |
| `platform.machine()` | arm64（macOS，Darwin） |
| `pragma compile_options` 中的 LOAD_EXTENSION 项 | 既无 `ENABLE_LOAD_EXTENSION` 也无 `OMIT_LOAD_EXTENSION`；但 `enable_load_extension(True)` 实际可用（API 存在） |
| PyPI 最新版本 | 0.1.9（requires_python 未声明） |
| 0.1.9 wheel 矩阵 | macosx_10_6_x86_64、macosx_11_0_arm64、manylinux_2_17_x86_64/aarch64、win_amd64（均为 py3-none-*） |
| wheel 内容 | `sqlite_vec/vec0.dylib` + 薄 Python 包装（165 KB） |
| dylib 架构/链接 | Mach-O arm64；只链接 `/usr/lib/libSystem.B.dylib`（无第三方运行时依赖） |
| **ABI 加载实测** | `enable_load_extension(True)` + `load_extension(vec0.dylib)` **成功**；`select vec_version()` → **`v0.1.9`**（本机 SQLite 3.53.2） |
| **功能探针实测** | `vec0` 虚拟表 create/insert/KNN 全部可用；`distance_metric=cosine` **受支持**，且 distance = 1 − 余弦（与手算 1−cos 在 float32 精度内一致，实测样例 0.0100505063310 vs 手算 0.0100505063388） |

探针样例输出：

```
vec_version() = v0.1.9
sqlite_version() = 3.53.2
knn hits (rowid, distance): [(2, 0.17320504784584045), (3, 1.407124638557434), (1, 1.4594519138336182)]
FUNCTIONAL PROBE: OK
```

## 2. 平台矩阵（诚实标注验证方式）

| 平台 | 结果 | 验证方式 |
|---|---|---|
| macOS arm64 | **PASS（实测）** | 本机 load_extension + vec_version + KNN 全链路 |
| macOS x86_64 | 未实测（UNVERIFIED） | PyPI 矩阵有 macosx_10_6_x86_64 wheel，未在目标机验证 |
| Windows x64 | UNVERIFIED | PyPI 矩阵有 win_amd64 wheel；无 Windows 目标机 |
| Linux x64 | UNVERIFIED | PyPI 矩阵有 manylinux_2_17_x86_64 wheel；无 Linux 目标机 |

## 3. 结论与产出

1. **gate 判定：PASS（macOS arm64 实测）** → 允许写入可选适配器
   `deeptutor/math_tutor/infrastructure/sqlite_vec_index.py`
   （`SqliteVecVectorIndex`）：
   - 构造时**显式传入扩展路径**（dylib/so），构造即加载并校验
     `vec_version()`，失败抛 `SqliteVecUnavailableError`；`try_open`
     提供干净 DEGRADED（返回 None）；
   - 只做 metadata 过滤之后的 (标识, 向量) ANN top-k（vec0 cosine），
     与 `fuse_retrieval_scores`/`cosine_similarity` 契约一致，等价于
     full-scan 融合的可替换实现；
   - **绝不接入 ProductState 默认路径、绝不出现在生产默认接线里**；
     测试全部 `pytest.mark.skipif`（扩展文件存在才跑），只从
     /tmp/sqlite_vec_probe 探测产物加载。
2. 生产接入保持 DEFERRED：嵌入分发策略（bundled / first-run download
   / resource pack …）未定（docs/ADR_EMBEDDING_DISTRIBUTION_DRAFT.md，
   PROPOSED / DEFERRED），离线安装/迁移/备份/恢复演练仍未实装。
3. 复评触发条件不变：Embedding Distribution Strategy 定稿后，再评审
   「每连接 load_extension 挂点 + 仓库 adapter 切换 + Phase 6 验收线」。
