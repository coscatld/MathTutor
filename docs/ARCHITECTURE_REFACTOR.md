# MathTutor 架构整理与验证记录

日期：2026-11-17。范围：历史产物与死代码、后端职责拆分、SQLite 仓储统一、前端样式与 HTTP 契约。

## 核验后的范围

本轮以实际调用和现有测试为依据实施三个阶段：

- 已退役检索入口实际对应 4 个直接测试文件，不将所有带 `phase6_retrieval` 名称的测试视为死代码。可选 `sqlite-vec` 适配器覆盖迁至 `tests/test_sqlite_vec_adapter.py`。
- 业务仓储共有 8 个手写内存实现。凭据库和文件选择器的测试替身仍有独立用途。
- `tests/compat_deeptutor/` 原有 9 个文件，已被默认 pytest 配置排除；删除它们减少历史维护负担，不计作默认 CI 加速。
- 函数内导入不直接证明循环依赖。本轮将学生协议移至 `tutor_contracts.py`，移除了学生契约反向依赖控制器的实际边。

## 历史代码与产物

删除 `retrieval_router.py`、`lexical_reranker.py`、4 个退役检索测试、旧基准夹具与兼容测试目录。历史实现可从整理前的提交 `54f37d98d6160693bef962835a0527ed0f8a4872` 查询。

RC 检索基准现在调用实际的 `DocumentIngestionService → ConversationRetrievalOrchestrator → DocumentIndexManager → ProductionReranker` 链路。导入在计时范围外，结果记录 `retrieval_pipeline`；旧合成检索器的性能数字与新结果不作直接对比。

本机清理释放约 **3.44 GiB 已分配空间**：历史 Python 运行时、未使用的前端缓存、解包目录与重复或过期安装包。当前公开 macOS / Windows 安装包、校验摘要和验收记录保留。清理不涉及学生数据和仍在使用的验证运行时。

后续构建可以运行：

```bash
python desktop/scripts/clean-build-artifacts.py
python desktop/scripts/clean-build-artifacts.py --apply
```

默认只预览。工具按平台、架构和格式保留最新安装包，同时保护 README 下载链接对应的发布目录；`--protect-build` 可增加保留目录。它只处理顶层及一层构建目录内的 `MathTutor` 安装文件与对应 blockmap，不清理日志、验收记录、源代码或 Python 运行时，也不跟随目录符号链接。删除前再次检查文件大小和修改时间。

## 后端职责

`desktop_api.py` 从 2105 行降到 48 行挂载代码。57 个既有桌面 HTTP 路由保留原路径、方法和所有者依赖，分别放入设置、嵌入设置、学习设置、启动、备份、隐私、资料、记忆、练习、学习摘要和诊断模块。拆路由时逐项比较 OpenAPI 快照；之后增加响应模型的差异属于下文的契约声明。

恢复数据库的编排移至 `application/restore_runtime.py`。公开文档和记忆投影放入 `public_projections.py`，HTTP 与数据导出共用，应用服务不再从 HTTP 端点模块导入投影函数。

控制器从 3379 行降到 2035 行，拆出三个独立服务：

| 服务 | 职责 |
|---|---|
| `AttemptEvaluationService` | 绑定验证、作答评估、辅导程度、诊断推进与学习证据 |
| `TutorIntentDispatcher` | 对话意图分发、普通聊天、提示命令与中断恢复 |
| `PracticeWorkflowService` | 练习推荐、接受、拒绝与关联学习周期 |

服务通过显式存储、策略和跨流程回调协作，不接收整个控制器作为代理。请求、事件与学生命令定义独立放入 `tutor_contracts.py`。控制器仍负责请求边界、题目建立、教学呈现和图形协作；**300–500 行的初始估计未达到**，本轮没有通过继承或通用代理把复杂度隐藏到另一处。

### SQLite 统一

开发、单元测试和持久化模式使用相同仓储 SQL、外键、CAS、FTS5 与事务逻辑。缺省仓储可创建独立的真实内存库；产品运行时显式共享同一引擎。

`create_db_engine(":memory:")` 使用具名 SQLite 内存 URI，并从执行完整 Alembic 迁移的空模板复制 schema。一个锚连接维持数据库生命周期，异步连接池将事务租约串行化，避免共享同一连接时并发任务互相提交或回滚事务。拥有引擎的调用方负责 `await engine.dispose()`；`MathTutorApplicationService.aclose()` 关闭自行创建的库，产品运行时由 `shutdown_runtime()` 关闭。测试结束回收独立仓储创建的临时引擎。

统一过程中发现并修正了三处真实 SQLite 差异：

- 索引构建记录保留输入的 `built_at`，保证保存和读取一致。
- 启动迁移检查复用现有引擎，避免把内存 URI 当作文件路径重新打开。
- 实现按验证记录 ID 查询凭据，并持久化 `policy_id` / `policy_version`；迁移 `026` 给旧表增加字段。已有凭据无法从哈希反推策略，保留空值表示未知，不改写历史证明。

新增验证覆盖独立内存库、真实外键、FTS 表、无磁盘文件、并发事务隔离、回滚与取消，以及旧结构迁移和重启后的策略信息。

### 检索边界

保留现有生产 RAG 分层：编排器负责对话范围、查询重写和证据包，索引层负责存储过滤与召回，重排器负责排序，扩展器同时服务检索和资料问答。显式空文档集合表示不检索，不能变成搜索全部资料。将这些职责合并到索引管理器会让作用域与引用规则向存储层渗透，因此本轮通过删除退役链路和使用生产基准收敛实现，未强行合并仍有独立职责的层。

## 前端与类型契约

主题变量移至 `web/styles/tokens.css`，动画定义放入 `motion.css`，产品组件样式使用 `product.module.css`。全局 CSS 从 1508 行降到 146 行，保留重置、共享基础组件与可访问性规则。`productClass` 在保留自动化使用的稳定类名时附加 CSS Module 类名；仅局部样式需要映射，普通 Tailwind utility 保持直接使用。模块动画通过主题变量引用全局关键帧名称，避免 CSS Module 重命名后失效。

设置页面保留导航壳，模型状态、表单和连接测试各有组件；切换标签页保留未提交表单。隐私页的数据读取、删除、导出和重建由 `usePrivacyData` 处理，摘要与确认控件分别复用。

HTTP 响应模型位于 `api/desktop_contracts.py`，请求模型位于 `api/routers/schemas.py`。导出脚本不启动产品运行时、不打开用户数据库；生成文件为：

- `web/features/math-tutor/desktop/generated/openapi.json`
- `web/features/math-tutor/desktop/generated/api.d.ts`

```bash
npm run api:generate --prefix web
npm run api:check --prefix web
python scripts/check.py
```

`check.py` 将当前 Python 解释器传给生成器，所有 CI 平台都会检查 schema 和类型是否过期。生成器采用 UTF-8，并将具有服务端默认值的请求字段保留为可选。已有桌面 `types.ts` 改为生成类型的别名，首次对齐修正了练习难度、删除历史回执和导出内容等既有字段偏差。

WebSocket 的 `protocol.ts` 仍承担运行时过滤和公开数据投影，不能由 HTTP OpenAPI 替代。初评、概念复查等其他 HTTP 接口的既有前端类型尚未全部改为生成别名；本轮覆盖原桌面公共类型及其对应端点。

## 验证

- 后端与 Python 桌面完整回归：3916 通过，22 因可选依赖缺失跳过；新增安装包保留策略测试另有 3 项通过。
- Web：334 项通过；Next.js 生产构建通过。
- Node 桌面契约：57 项通过，2 项按平台条件跳过。
- 使用隔离数据目录连接真实后端的浏览器检查：未保存的模型表单跨标签保留、中英文切换与重载、四种主题、键盘焦点、隐私页读取、图形绘制，以及桌面 / 平板 / 手机布局。
- RC 基准：生产检索链路 5 次采样，p50 1.285 ms、p95 2.553 ms；仅作当前本机特征记录，未据此声明性能提升或建立 SLO。

公开 Release 与下载链接继续对应此前验收过的安装包。这轮源码架构整理没有覆盖已发布的安装文件。

## 参考

- [SQLite 内存数据库与共享缓存 URI](https://www.sqlite.org/inmemorydb.html)
- [SQLAlchemy SQLite 连接池说明](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html)
- [FastAPI 响应模型](https://fastapi.tiangolo.com/tutorial/response-model/)
- [openapi-typescript](https://openapi-ts.dev/introduction)
