# DKT 主体接入研究：Mac main 0.3.3 合并后

## Material Passport

- Origin Skill: academic-research-suite / experiment-agent
- Origin Mode: run（工程合并、兼容性探针与接入设计；非新训练）
- Origin Date: 2026-09-16
- Version Label: week02_main_sync_v1 / EXP-W02-002
- Verification Status: PARTIAL；本机工程核验与远端 main CI 分开，目标效果未验证
- 产品基线：`133d49e884cef0e9526b0d53dc38c839696e6109`，版本 0.3.3
- 研究约束：工作区 `mathtutor_rnd_pack/AGENT_EXECUTION_BRIEF.md`，EXP-W02-001；严格门禁不因截止日期改变

## 1. 结论

保留 M1 的 EvidenceTracker 教学与画像，下一步先做“版本化模型包＋只读影子预测＋三平台契约”，不直接把来源 `.pt` 或 JSON 放进现有 `model.npz` 路径。目标技能/任务映射和校准未获验证之前，MathTutor 目标输出继续为 `null/unsupported_target`，不把目标事件推进来源 h/c，也不接管推荐或判题。

`.pt` 是研究与复现交付物；桌面请求路径使用经训练侧数值对齐的 NumPy 运行时。源权重、事件特征、查询特征、词表、标签政策、校准与回退必须作为一个版本接入，不能只迁移权重数组。

本报告是开始接入的设计与证据，不是宣称 DKT 已在目标产品上线。本轮没有新增正式训练、替换正式模型或打开生产开关；既有单元测试中的合成训练不构成效果实验。

## 2. 同步结果与保护范围（OBSERVED）

从 `0a6f334cda686c4fb38309a5f3f39d3b15887731` 快进至 `133d49e...`，保留 Mac 新增的学习画像、冻结推荐依据、资料作用域、会话回收站、018 学习画像迁移、来源适配器及发布证据。两份 CI/CD 工作流保持上游原样。

合并前 13 个本地改动文件逐字节备份于工作区 `research-runs/week02-main-sync-20260916/before-merge/`，另保留 stash `36f882506039943618e9feb9e869d75bfc8745ee`。恢复过程中 4 个冲突文件已按语义协调：

| 位置 | 合并后的约束 |
| --- | --- |
| `application/controller.py` | 题目向 HTTP/WS 发布前持久化预测；原始提交先于解析/判题；保留 Mac 资料上下文和冻结推荐依据 |
| `knowledge_tracing/events.py` | 首次位置在排除前派生；原始提交与其唯一判题只占一个位置；判题失败、未知及步骤提交均不使后续整题成功变成首次 |
| `knowledge_tracing/service.py` | 预测内容保持冻结；整题标签只关联一次；保留排除标签标记、删除代次与重放 CAS；原始提交不递推 h/c |
| `tests/test_knowledge_tracking_v2.py` | 保留 student-disjoint 主协议与显式联合留出压力测试；重复作答不能增加独立证据 |

新派生政策明确为 `first_content_submission_v1`。旧事件的物理 payload、已冻结的预测不原位重写；查询视图按新政策派生资格，历史预测须按各自保存的政策解释。旧数据缺少原始提交事实时不能虚构未记录的提交。

新增 `tests/test_main_sync_evidence_contract.py` 覆盖 8 项跨版本契约，并保留第二周 13 项生产证据回归。测试总量与执行状态在同目录交付记录中回填，未运行不写 PASS。

## 3. 接口差异：已检查实际代码与冻结包

| 维度 | 产品现有 LSTMTracker | 正式来源模型 SourceModel | 接入决策 |
| --- | --- | --- | --- |
| 权重字段 | `weights`、`prediction.weight`，要求 trained/training_steps | `state_dict`、`head.weight`，格式 `tutor_model_dkt_v1` | 分版本识别；不得补一个 trained 标志冒充兼容 |
| 查询/事件 | `structured_kt_v1`；产品技能、题族、难度及事件枚举 | `source_skill_query_observation_v1`；来源技能及 23 个观察字段 | 显式适配，不按数组下标或相同维度猜测语义 |
| ASSIST09 维度 | 随产品训练词表变化 | 122 来源技能；query=124，event=147，h/c=64 | 不等于 Mac 审计的全数据 123 个技能；训练词表范围不同 |
| ASSIST2012 维度 | 同上 | 264 来源技能；query=266，event=289，h/c=64 | 与 ASSIST09、产品状态均不能互换 |
| 生命周期 | 多会话、父子练习；数据库保存多条呈现 | 每个 owner state 只允许一个 pending presentation | 不能把 SourceModel 的单槽状态机直接当产品会话服务 |
| 状态边界 | 现有事件跟踪状态及 last_event_seq | state_cutoff、last_completed_seq、visible_event_boundary 分离 | 新模型状态单独版本绑定，不能复用旧快照 |
| 模型入口 | `data_dir/models/dkt/model.npz`，实际读取 JSON | 清单绑定 runtime、词表、校准、先验、模型哈希 | 新 registry 替代含混默认路径；保留有说明的旧格式兼容 |
| 发布资源 | 桌面 extraResources 尚无 student-model/base | 工作区外独立冻结包 | 显式资源清单和打包验收，不能依赖开发者 Desktop |
| 运行依赖 | NumPy 在推理代码中使用；项目未直接声明 NumPy | `numpy==2.2.6`；接口无 torch import | 在集成 PR 中显式声明并验证目标 runtime，不靠传递依赖碰巧安装 |

诊断实测：两个来源包都被现有加载器拒绝（错误 `untrained models cannot enter runtime`，原因是协议字段不兼容，并非来源模型没训练）。父任务未完成时呈现子任务均报 `Pending presentation conflict`。两个来源的 MathTutor 查询均返回 null，目标完成后 h/c 不变，诊断进程没有导入 torch。

证据：工作区 `research-runs/week02-main-sync-20260916/dkt-compatibility-20260916T153842Z.json`；脚本 `probe_dkt_compatibility.py`。仅用合成任务，不读取目标学生或隔离测试标签。

## 4. 推荐接入边界（INFERENCE / TO_VERIFY）

```text
已核验任务 → 呈现前查询（无答案/当前帮助结果）
                 ↓
        StudentStateService / 版本化适配层
                 ↓
        registry → 可信运行时代码＋已验模型资源
                 ↓
      本人历史状态 → 只读预测 → 持久化冻结记录 → 显示题目

原始提交 → 首次占位 → 判题 → 已完成观察 → 本人状态重放/CAS
                         └→ 合法标签另行关联；不反写历史预测

EvidenceTracker → 画像/推荐（现行生产）；DKT shadow 无教学控制权
```

建议新增职责而非并行建立另一套产品数据库：

1. `model_package.py`：验证清单、发布信任、允许文件/大小、路径逃逸、dtype/形状/有限值、特征顺序、校准、覆盖与完整数值自检。只使用应用内可信运行时代码，不执行导入包提供的 Python/pickle。
2. `model_registry.py`：解析用户显式选定兼容版本→随包兼容版本→EvidenceTracker；版本切换与回滚均需重放。包不能自授生产权限。
3. `source_adapter.py` / 后续目标适配器：分开“来源研究回放”和“产品目标查询”。未经批准的主题代理映射不得产生目标概率。
4. 产品协调层：预测采用冻结的个人状态快照，pending 按 `(owner, presentation_id)` 持久化，不锁住其他会话。已完成观察以 owner 的事实序号顺序重放，唯一事件去重；迟到判题触发相应重放，不能倒序追加 h/c。
5. 状态身份至少绑定 owner、model/runtime/feature/map/calibration/policy identity、learning_generation 与 cutoff；重放提交复用 M1 `learning_generation`＋最新事件序号＋模型身份 CAS，不绕过“删除后旧任务不得写回”。

若新增状态存储表或字段，迁移编号应在届时最新版本后分配；当前最新为 018，不预先占号覆盖 Mac 迁移。共享模型权重只读；个人 h/c、冻结预测、排除/删除事实继续留在 owner 隔离的 SQLite 中，不写进公共模型包。

现有 `frozen_forecast.state_scope=existing_product_event_tracker` 不是先进研究的“仅本人合法已完成观察 h/c”认证。接入时必须新增明确 ABI/状态版本，禁止用字段重命名混同二者。

## 5. 跨平台与 CI/CD

路径延续已有 `desktop/runtime/paths.js`：只读资源从打包资源根解析；可写模型子目录从 `app.getPath('userData')` 解析；Python 使用 `pathlib`，Node 使用 `path.join/resolve`。不要出现 `C:\\Users\\...`、`/Users/某人/...` 或以当前工作目录定位权重。[Electron 官方路径说明](https://www.electronjs.org/docs/latest/api/app#appgetpathname)

资源目录建议为 `student-model/base/` 和 `userData/models/student-model/<version>/`。清单和运行时代码哈希绑定实际字节；跨平台检出/换行转换不可悄悄改变已接受资产。macOS arm64、Windows x64 必须使用相应平台 NumPy 二进制；Linux 保留源码测试。

CI 继续由 `python scripts/check.py` 统一入口运行 pytest、前端测试/生产构建及桌面契约。矩阵保留 ubuntu-latest、macos-latest、windows-latest，不添加排除，不以 Windows 专属命令替代统一入口。[GitHub 官方矩阵机制](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/run-job-variations)

本轮实际遇到 Next.js 写用户全局遥测配置时报 EXDEV。验证入口现仅对其子进程设置 `NEXT_TELEMETRY_DISABLED=1`，不改全局偏好，也不改变安装包行为；回归测试验证环境变量不会泄漏到调用进程。该开关是跨平台方式。[Next.js 官方遥测说明](https://nextjs.org/telemetry)

后续集成 PR 必须增加的三平台测试：

- 各支持模型格式的已知向量及最终校准/回退对齐；无 torch 进程可推理。
- 中文/空格路径、与启动 cwd 无关、只读资源目录与可写用户目录隔离。
- 不合法/损坏/超大/逃逸/不兼容资源拒绝；回退仍可判题、浏览画像和接受练习。
- 呈现前冻结、重复请求、同时多会话、嵌套练习、未知/帮助/迟到判题、模型版本切换、删除与旧重放竞争。
- release runtime 实际包含 NumPy；包内不夹带来源 CSV、学生数据、个人状态、训练依赖或任意模型 Python 文件。

CD 保留 `release-packaging.yml` 的手动发布、真实可搬移 Python、macOS archive SHA256、Mac/Windows 签名和 Mac 已打包 smoke 门禁。源码检查因未提供 runtime 而 SKIPPED 不等于发行包成功。本轮不触发部署、签名或修改 secrets；不能把旧 Mac DMG 的验收绑定到本地未提交代码。

## 6. 数据和协议不能自动拼接

Mac 的 `STUDENT_DATA_AVAILABILITY.md` 是 9 月 13 日的来源审计：6/13 是主题代理覆盖，不是目标任务等价证明；原始数据位于 Mac 仓库外，Windows 没有由这次 pull 获得它们。

研究仓库另有 2 名参与者、23 条已批准开发标签的先导记录，与 Mac 报告“该侧目标训练数据为 0”并不矛盾。不得把两个时点/命名空间直接汇总为独立训练/测试队列。本轮没有再次打开这些个人记录。

任务书是本次先进研究协议的约束源：5 seeds `17/29/43/71/101`；0/1/3/5/10/20 已完成主问题前缀；主要终点 k=1/3/5 学生等权 LL；2000 次学生级配对 bootstrap；相对 B2 的 LL 改善、Brier ≤0.002 劣化等门禁不变。Mac 实施计划里的 3 seeds、Brier 0.005 等历史候选值不得覆盖该冻结协议；也不将既有 3-seed 来源结果重新命名为 5-seed 先进模型结果。

## 7. 建议实施顺序与 9 月 30 日边界

| 顺序 | 独立交付 | 验收与失败时处理 |
| --- | --- | --- |
| A：模型包适配 | 格式判别、完整模型身份、资源路径、NumPy 依赖、自检向量 | 三平台全部通过；损坏/缺包仍回退；尚不向真实目标输出概率 |
| B：只读影子接入 | 多呈现协调、冻结预测、本人状态和删除 CAS、持久化版本切换 | 测试恢复/并发/删除/迟到；10,000 产品故障序列按任务书另验，不挪用来源接口的 10,000 合成案例 |
| C：目标效果与生产批准 | 合法目标映射、数据划分、校准、对照与门禁报告 | 未通过继续 EvidenceTracker；通过后另行批准策略试点与正式模型资源包 |
| D：发行 | 本次准确 commit 的 Windows/Mac 安装器、升级/回滚、README evaluate/benchmark | 本机推理耗时不冒充真实安装端到端性能；签名/许可未就绪不称公开生产发行 |

9 月 30 日前优先保证可演示 M1、冻结来源模型材料与可复核报告。时间不足不能开启未经验证的目标概率。正式模型原目录维持冻结；这次报告和新版合并补丁存于新工作票目录，旧基线 0.3.1 的交接补丁不应再直接应用到 0.3.3。

公开主张仍为 `NOT_APPROVED`；本报告不替代目标效果、数据许可、赛事资格、签名发行或知识产权的人类批准。
