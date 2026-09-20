# 知识库、受控工具与阶段复盘交付

执行日期：2026-09-17 至 2026-09-18。基线：`9754808783bb9b531794835c7b675ab6363244f7`；开始时工作树干净。本次不修改 DKT 权重、目标映射、判题事实或正式模型包，不合并 main、不发布安装包。

## 可以实际操作的路径

1. 左侧 **知识库**（`/math-tutor/knowledge`）新建个人库或课程库，导入两份 `.md`。也可在对话顶部进入知识库，创建仅属于该会话的资料空间。
2. 在对话 A 的知识库页面勾选库，选“知识库问答”，点击“保存挂载与范围”。“仅所选资料”在空选择时保持空范围。
3. 返回对话提问；回答的来源链接打开真实版本、字符区间、行号和正文。没有 Provider 时只显示真实词法检索原文，不模拟 AI 综合。
4. 从同一库“新建会话并显式挂载此库”进入 B；选择“整理笔记保存到”的目标库，再要求“跨资料整理并保存笔记”。原生 tools 不支持的 Provider 可在“工具兼容与仅提示”选择结构化 JSON 协议。
5. 实际工具依次执行章节检索、原文读取、草稿与保存；知识库出现新笔记。新会话 C 显式挂载后可检索它。未明确要求保存时，草稿在知识库预览后手动保存。
6. 编辑页支持 Markdown 预览、标签、`[[笔记标题]]` 正反向链接及 ZIP 导出。首次新建不重复确认；编辑已有笔记、重复导入有外部修改的同一路径、删除均保留确认及版本 CAS。文件夹导入只读取选中的 Markdown，不扫描磁盘、不执行插件。单次最多 100 文件、单篇 Markdown 最多 1 MiB；导出最多 1000 笔记/64 MiB 正文。
7. 左侧 **学习画像**（`/math-tutor/profile`）→“阶段学习复盘”：保存明确目标/讲解偏好，查看变化、依据、未确定事项、下一观察任务，或主动复盘新观察。

## 实际主链与安全边界

- 原 Controller 保留，显式知识问答分支不自动进入苏格拉底教学/练习。仍处于未结束练习的会话不能用知识问答绕过答案披露；仅提示请求在检索/Provider 之前隔离。知识模式图片不能绕回旧图片聊天取得答案。
- 原 Gateway 增加原生调用的透传；原 Tutor Runtime 增加真实应用工具循环。每次工具执行结果作为原生 `tool` 消息或明确的 JSON 兼容结果回传，然后继续调用模型。最多 10 次模型调用、20 个工具调用、32768 共享 token 预算、120 秒总期限、20 秒工具超时、一次证据修订；证据检查也计入共享调用预算。
- 输入 Schema 禁止额外参数；输出收据有 Schema；未知工具、错误参数、权限变化、超时均为错误收据。无 shell/Python/SQL/任意 MCP/联网能力。数学验证和练习提案复用原验证器及 ReleaseGate；练习提案单轮缓存，保存使用持久幂等键。新的授权见 ADR_APPLICATION_TOOLS.md。
- 检索复用原 Document Repository/DocumentIndexManager：owner、启用状态和显式文档集合在候选检索前限制；先上下文/范围解析及保守查询改写，再词法/已有真实向量混合、轻量重排、区间读取。没有真实 embedding 或装载 FakeEmbeddingBackend 时走实际词法检索。
- 原文摘录必须逐字存在于真实读取区间；总结需逐项独立证据覆盖检查，失败不能发布，不能把词面相似当支持。引用固定实际版本/区间，不只引用检索标题。模型检查本身仍有误判风险，不能宣称已通过真实模型质量评测。
- 新知识空间、绑定、版本、草稿、保存收据均按 owner 隔离。旧附件仍只在原会话可见；仅保留原先用户已显式设为全局的授权，不自动迁移为全局库。删除会话不删除个人/课程库资料；删除资料真实清除版本、草稿及派生索引，并推进删除代次。历史引用在资料删除/禁用后不能继续读取。
- 取消后已完成的真实保存不会回滚或隐藏，固定的保存/草稿回执可保留；已有请求日志继续负责重启恢复，旧请求不重复执行。**不支持进程重启后从任意工具中间步骤自动续跑**：保留笔记/草稿，按原请求日志标记中断，再由用户继续。

## 阶段复盘的真实能力与限制

复用 StudentStateService 的可信学习事件，在同一事实事务更新复盘投影、写入原 Outbox。累计 3 条新作答观察、整题正确作答结束、显式结束题目、目标切换、证据撤销或主动操作触发。没有新证据/偏好变更时复用已有结果；复盘本身不产生学习事件。

本版是 **evidence_rules_v1 规则复盘，不是画像 LLM**。可信作答事实、明确用户偏好、待验证假设分开存储/展示；不凭空生成假设。展示独立成功/失败、变化、依据、限制、合法教学偏好及下一观察任务。用户“懂了”、阅读、收藏、选择题结果不增加原有独立自由作答成功计数。没有支持的 DKT 目标仍为 null，来源概率不解释为掌握度。

讲解偏好只能进入原 Writer 的措辞上下文，不能改变判题、证据、答案披露或练习发布。Outbox 消费在短事务之外，提交投影前检查原 `learning_generations` 删除代次与证据版本；删除教育历史同时清除复盘/偏好，旧任务不能恢复。模型生成的个性化复盘、有效性及教学收益 **未实现/未验证**，不能称为已上线的智能画像质量成果。

## 基线与同材料比较

原始归档、实验票、脚本、截图、JSON 报告位于工作区 `research-runs/knowledge-workbench-20260917/`。冻结归档 SHA256：`1176defdfacbd5a7fdee44ab94ccb704873cba1a4d6ea31e18f15c51a723324f`；两篇笔记的 fixture SHA256：`0b0ed829328a2cd04a355791160f158c57823d4bcb5dfc9ad28d41f3ce76be6a`。

| 指标 | 冻结旧链 | 新链原生 tools | 新链 JSON 兼容 |
| --- | --- | --- | --- |
| 相同 5 查询有命中 | 4/5 | 4/5 | 4/5 |
| 脚本化整理保存任务 | 不执行工具 | 实际完成 | 实际完成 |
| 实际读取来源 | 工具探针 0 | 2 | 2 |
| 重复保存后的新增笔记 | 0 | 1 | 1 |
| 脚本 Provider 调用 | 1（拒绝即止） | 5 | 5 |
| 实际模型回答质量/任务成功率 | NOT_RUN | NOT_RUN | NOT_RUN |
| 真实模型调用与费用 | 0 / 未测费用 | 0 / 未测费用 | 0 / 未测费用 |

命中数不是语义准确率；脚本 Provider 的固定 token 返回值不是实际 token 成本，5 次完成任务与旧链一次拒绝也不是等效工作的效率比较。未发现可用项目 Provider 配置，未调用真实模型；没有学生学习效果、生产模型质量或语义向量质量提升声明。

## 迁移

新增 Alembic `020`（上版 `019`），共增加 9 张 owner 隔离表，既有附件绑定原样保留。应用启动走现有 `upgrade_db()`：升级前自动保存数据库备份，然后幂等迁移。手动使用当前产品 Python 执行 `python -m mathtutor.infrastructure.migrate`，数据库路径沿用 `MATHTUTOR_DB_PATH` / `MATHTUTOR_DATA_ROOT`；**先确认指向所需数据库**。本次测试只迁移临时测试数据库，没有迁移用户日常数据库。

历史附件首次被知识问答读取时惰性建立不可变提取文本版本，不扩大授权。Markdown 编辑保留旧版本；原重解析/重命名入口对版本化 Markdown 拒绝操作并引导知识库编辑，避免绕过版本确认。回退应用需使用升级前备份；直接 downgrade 会删除新知识库/复盘表，不建议对有新数据的库执行。

## 验证命令

在 MathTutor 项目目录，使用已安装项目依赖的 Python；Windows 可以把 `python` 换为 `.venv/Scripts/python.exe`，macOS/Linux 为 `.venv/bin/python`。

```text
python -m pytest tests desktop/tests -q --disable-warnings --tb=short
python -m pytest tests/test_knowledge_workbench.py tests/test_knowledge_safety.py tests/test_knowledge_gateway.py tests/test_stage_review.py -q
npm --prefix web test
npm --prefix web run build
npm --prefix desktop run test:contracts
python scripts/math_tutor_knowledge_benchmark.py --baseline ../research-runs/knowledge-workbench-20260917/baseline-result.json --output ../research-runs/knowledge-workbench-20260917/comparison.json
```

完整跨平台源代码门禁仍为 `python scripts/check.py`，未加入 Windows 专用产品路径或依赖。浏览器脚本 `research-runs/knowledge-workbench-20260917/browser_qa.py` 连接端口 3191 的已构建 Web 页面，通过真实 FastAPI/SQLite/WS 和脚本 Provider 进行页面操作；不是 mock 掉知识库后端。最终命令结果记录见同目录 validation.json。

跳过项目包括未安装的 PyMuPDF、PyTorch 及不适用于当前 Windows 环境的 sqlite-vec dylib 探针。桌面契约测试不等于目标机器安装包运行；本次未运行 macOS/Linux 真机、安装器、签名/公证或远程 CI，未推送本轮改动。真实 Provider 质量、真实向量质量、复杂冲突/长文综合质量和真实费用仍为 NOT_RUN。

首版边界：课程库仍是当前 owner 的课程资料组织，不是班级共享/协作权限系统；双向链接只支持基本 `[[标题]]`，不运行 Obsidian 插件。变更挂载/禁用/删除会推进 owner 范围代次并使旧草稿失效；需要保留的草稿应先保存为正式笔记。查询改写及重排是透明的轻量规则，并非另一个已评测的学习排序模型。

## 实际改动文件索引

- API/装配：`src/mathtutor/api/{knowledge_api,desktop_api,math_tutor_ws,product_app,product_state}.py`
- 主链：`src/mathtutor/application/{knowledge,knowledge_qa,knowledge_tools,stage_review,tutor_runtime,controller,outbox_relay,conversation_trash,data_lifecycle}.py`
- 网关/数据：`src/mathtutor/infrastructure/{generative_gateway,knowledge_schema,schema,migrate}.py`、`infrastructure/migrations/versions/020_knowledge_workbench.py`、`repositories/sqlite_documents.py`
- 学习与表达：`src/mathtutor/learning/knowledge_tracing/service.py`、`src/mathtutor/pedagogy/tutor_writer.py`
- UI：`web/app/(workspace)/math-tutor/knowledge/page.tsx`、`web/features/math-tutor/knowledge/{api.ts,KnowledgeWorkbench.tsx,StageReviewPanel.tsx}`、原 `MathTutorPage.tsx`、`DesktopShell.tsx`、`LearningProfilePanel.tsx`、`web/components/common/MarkdownRenderer.tsx`
- 测试：`tests/test_knowledge_{workbench,safety,gateway}.py`、`tests/test_stage_review.py`；更新原路由、迁移、生命周期和发布契约断言。
- 平台探针：`desktop/main.js`、`desktop/scripts/{macos-upgrade-probe.py,run-packaged-smoke.js}`，只同步 schema head。
- 基准与决策：`scripts/math_tutor_knowledge_benchmark.py`、`docs/ADR_APPLICATION_TOOLS.md`、本文及工作区实验 artifacts。

前端实现遵循已读取的 frontend-design / ui-ux-pro-max / webapp-testing 技能：复用产品设计变量，突出版本引用与来源区间，检查暗色、375px、键盘标签、减少动画和页面运行错误；没有另建全功能 Obsidian 或工作流画布。
