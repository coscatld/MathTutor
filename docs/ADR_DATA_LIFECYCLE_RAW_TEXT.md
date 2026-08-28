# ADR: 数据生命周期与 raw_text 明文落盘审计（数据隐私）

- 状态：**PARTIAL**（部分实施，2026-08-21，Phase 6 第二轮 / SUBAGENT D §7）
- 关联 ADR：`desktop/ADR-DESKTOP.md`（桌面壳）、`docs/ADR_EMBEDDING_DISTRIBUTION_DRAFT.md`（不变式 G）、设计文档 §6.1 / §14 / §19

> PARTIAL 的含义：本 ADR 所辖的**删除/清理/导出/日志路径已实施并有测试覆盖**；
> **静态加密（encryption at rest）未实施**——它需要新依赖或新密钥管理面，
> 按「本轮不新增依赖、不自研密码学」的硬约束，只做审计 + 决策矩阵 +
> 部署要求，实现在后续轮次落地。

## 背景与问题

K12 MathTutor 是本地优先产品，SQLite 数据库、导入文档与备份文件全部落在
用户机器上。隐私评审（设计文档 §6.1、风险 P2）确认：学生**作答原文**与
**导入文档原文**目前以明文写入数据库和文件系统，需要：

1. 明确五类数据分类，让删除/导出/日志有单一的、覆盖全部业务表的依据；
2. 让「删除文档 / 删除教育历史 / 清空导出」真正删干净（不留 chunk/向量/文件残余）；
3. 回答「raw_text 是否加密落盘」——本轮只审计、不实现。

## 现状审计发现（file:line，Phase 6 第二轮开始时的事实）

| # | 发现 | 位置 |
|---|------|------|
| A1 | `problem_submissions.raw_text` / `attempt_submissions.raw_text` 明文 Text 列；schema 注释明言「encryption at rest lands with the privacy hardening step (§6.1)」 | `deeptutor/math_tutor/infrastructure/schema.py:110`、`:165` |
| A2 | `document_chunks.text` 学生导入文档的 chunk 原文，明文 Text 列 | `schema.py:472` |
| A3 | `personal_memory_nodes.object_json` 用户自述内容，明文 JSON 列 | `schema.py:418` |
| A4 | 导入文件以原文落盘：`<data_root>/uploads/<student>/<doc>/<safe-name>`，路径可控但字节明文 | `deeptutor/math_tutor/infrastructure/document_storage.py:26-28` |
| A5 | SQLite WAL 模式：写入期间的页镜像含明文（`-wal` 边车文件），直至 checkpoint | `deeptutor/math_tutor/infrastructure/db.py:51` |
| A6 | 在线备份 `*.backup-*.db` 为数据库完整明文副本（manifest 仅存 sha256，不加密） | `deeptutor/math_tutor/infrastructure/backup.py:67` |
| A7 | 日志禁区清单（observability）覆盖 api_key/secret/password/reasoning/attestation/payload/document，**未覆盖 raw_text / object_json / chunk 文本**——存在把学生原文写进日志的缺口 | `deeptutor/math_tutor/infrastructure/observability.py:27-45` |
| A8 | 既有文档删除只软删行 + 删存储文件，**chunks / 向量 / index 构建行残留**（墓碑行背后的内容未清） | `deeptutor/math_tutor/application/document_ingestion.py:188-196` |
| A9 | 教育结果行无软删字段；删除教育历史需要整学生硬删 + 重放投影，且不得与 Personal Memory CRUD 共入口 | `schema.py:221-267`、`repositories/sqlite_education.py` |

## 本轮已实施的缓解（PARTIAL 的「已实施」半边）

- `deeptutor/math_tutor/application/data_lifecycle.py`：五类分类（31 表全覆盖，
  字段级 SECRET 规则）、`delete_document`（保持软删语义 + 真实清理 chunks/向量/
  索引行/存储文件）、`purge_user_documents` / `purge_personal_memory`、
  `rebuild_derived_indexes`（无 backend 时诚实报 unavailable，绝不伪造）、
  `delete_educational_history`（硬删结果事实 + `project_student_state` 重放投影，
  绝不手写 mastery 值）。
- `deeptutor/math_tutor/application/data_export.py`：导出白名单
  `EXPORT_ALLOWED_FIELDS` 逐字段校验（fail closed），复用既有投影函数，绝不复刻逻辑。
- 日志：生命周期与导出路径只记 sanitize 后的计数摘要
  （`data_lifecycle.sanitize_summary` 在 observability 禁区之上补
  raw_text/object_json/text/path/hash 等片段——堵上 A7 的缺口，属于结构性的
  「第二道闸」，不改动 observability.py）。

## 选项矩阵（raw_text 加密落盘，≥3 选项）

| 选项 | 做法 | 优点 | 缺点 / 代价 | 判定 |
|------|------|------|-------------|------|
| O1 全库加密（SQLCipher） | SQLite 换 SQLCipher，整库页级 AES-256，密钥来自 OS Keychain | 覆盖 A1–A6 全部明文面；成熟方案 | **新增依赖**（sqlcipher 二进制/驱动），WAL/备份/迁移全链路需重验 | 推迟（后续轮次首选） |
| O2 字段级应用层加密 | 应用层对 raw_text/text/object_json 逐列加解密 | 不动存储引擎 | **自研密钥管理与加解密编排 = 自研密码学的滑梯**，违反本轮硬约束；密钥轮换/索引/检索全被破坏 | 否决 |
| O3 OS 全盘加密（部署要求） | FileVault (macOS) / BitLocker (Windows) / LUKS (Linux) + 每用户数据目录权限收紧 | 零代码、零依赖、覆盖库文件/上传/备份/WAL 全部落盘面 | 不是产品内控制；依赖用户与部署环境开启 | **现在采用（部署要求，写入发行版清单）** |
| O4 保持明文 | 不动作 | 零成本 | 隐私风险不关闭，与 §6.1 承诺冲突 | 否决（仅开发环境可接受） |

> 未列入的变体（如独立加密容器、目录级加密）视为 O3 的部署形态，不单列。
> 硬约束重申：**不自研密码学、本轮不新增依赖**——任何加密方案只允许使用
> 成熟库（如 SQLCipher）并由 OS Keychain/凭据存储持有密钥，绝不出现
> 应用内自定义加解密函数。

## 决策

- **现在（PARTIAL 已实施）**：删除/清空/导出/日志四条数据出口全部走
  `DataLifecycleService` 与导出白名单；桌面发行版清单把 O3（OS 全盘加密 +
  数据目录权限）列为部署要求；`keychain_secret_store.py` 已是 API key
  唯一落点（key 从不在 DB/安装包）。
- **推迟（本 ADR 的未实施半边）**：O1 SQLCipher 全库加密，独立 ADR 立项时
  评估；O2 永久否决。

## 后果与已知风险（诚实声明）

- raw_text / chunk 原文 / 上传文件 / 备份在**本阶段仍是明文落盘**，依赖 O3
  部署要求兜底；这是明确的 PARTIAL 缺口，验收口径为「出口已收紧 + 静态加密
  已立项」，而非「静态加密已完成」。
- `delete_personal_memory` / `purge_personal_memory` 保持既有节点软删语义；
  仓储协议无 edge 删除路径（节点是检索面，边不独立进入检索）——如需物理抹除
  KG 边需后续仓储协议扩展，本轮不做。
- `rebuild_derived_indexes` 在无 embedding backend 时返回 unavailable 而非报错
  ——退化模式是特性不是失败（不变式 G：Embedding 分发 DEFERRED）。
- 导出白名单是结构保证（`validate_export` 拒绝越界字段），而非「字段名审查」：
  未来新增投影字段必须同步更新 `EXPORT_ALLOWED_FIELDS`，否则导出整体失败
  （fail closed）。
