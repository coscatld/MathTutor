# 教学提示、对话资料与知识库范围

本页是既有 `MASTER.md` 的学习支持页面补充，保留纸墨、冷蓝、语义颜色、Lucide 图标及离线系统字体。

## 信息层级

- 教学提示：本轮目标与支持策略在冷蓝目标卡中呈现；可用操作、可跳过的诊断、真实作答证据按任务分组。已展示内容描述帮助记录，不显示能力进度或虚构分数。
- 对话资料：添加资料是首要动作，其后是文档 / 图片 / 对话记录计数、资料处理与检索状态、图片、导出与范围管理入口。扫描件、解析失败、已停用与已就绪不混为同一种状态。上传前后保留原有会话归属与导出端点。
- 学习记忆：完整列出保存的条目，展示 `object_json` 正文、来源、启用开关和待确认操作；旧的谓词正文记录仍可读。启用表示允许相关时参考，不声称本轮已使用，也不等同于掌握度。未确认 AI 推测不参与回答，离线基础辅导暂不按任意文字偏好调整。
- 知识库与问答范围：先展示当前对话的资料选择与范围预览，其后是库列表、资料管理及笔记编辑。库创建、兼容设置、导出与删除等次要操作逐层展示。范围读取、未保存、已保存与读取失败使用明确文案；尚未加载的范围不标为已保存。正文与范围修改在刷新和返回时均保留离开提示。

## 交互与布局

- 删除顶栏重复的“收起右侧工具”按钮。原工具按钮仍可切换或关闭，面板保留带可访问名称的关闭按钮与 Escape。
- 打开面板将焦点移至面板标题；显式关闭返回原触发器。它是非模态辅助面板，不设置错误的对话框角色、不锁住键盘焦点。
- 工具面板常规宽 360px，在工作区宽不超过 1200px 时浮于右侧。浮层底部按输入组件实际高度留空，内容独立滚动。若键盘焦点移到面板外并被浮层遮住，自动关闭浮层且保留新焦点。
- 知识库在桌面使用资料范围 / 预览双栏和库列表 / 主内容双栏；800px 以下顺序排成单列。标签与资料名允许换行，来源哈希与笔记正文不会撑出容器。
- 图标按钮均有名称、装饰图标隐藏于辅助技术。颜色只传达有文字说明的状态；各主题沿用语义令牌，减少动画偏好沿用全局规则。

## 依据与验证

- 已读 ui-ux-pro-max、其 `quick-reference.md` 与 `pro-rules.md`，以及当前安装 Next.js 的 Client Components、CSS 与 accessibility 文档。
- `progressive disclosure` 的数据库查询两次误命中标题换行，不将该结果作为面板设计依据；此项使用内置优先级规则。`component state --stack react` 命中局部状态及用户行为测试规则。
- `focus not obscured --domain ux` 命中 Web 焦点不被覆盖规范，由主代理复核后采用。
- 验证命令：`cd web && npm test`，`cd web && npm run build`；真实浏览器行为与布局检查为 `node scripts/smoke-learning-support.mjs`、`node scripts/smoke-workspace-layout.mjs`（启动隔离端口的开发服务后运行）。
- 浏览器测试使用模拟资料、记忆、知识库和会话，不读取用户数据、不调用模型；实际记忆进入模型提示的验证由后端独立测试负责。

## 本轮验收（2026-10-16）

- 后端完整回归：2760 通过、11 跳过；记忆接入不改变检索策略矩阵的适用范围。首次全量检查发现的策略范围引用问题已通过独立的记忆读取入口修复，并重新完成整套回归。
- 前端：217 通过；生产编译、TypeScript 与静态页面生成通过。桌面源码契约：48 通过、2 个产物级检查跳过，界面开发阶段未构建安装包或运行 Windows CI；0.6.5 发布阶段的打包验收另见[发布说明](../../../docs/RELEASE_0.6.5.md)。
- 三套真实 Chrome 检查通过：`smoke-workspace-layout.mjs`、`smoke-learning-support.mjs`、`smoke-question-bank.mjs`。后两者使用生产 standalone 前端，覆盖 375px、桌面、横屏、夜读、减少动画、23 条记忆完整展示及开关确认、范围保存/离开取消、年级筛选、默认隐藏答案，以及只发送题干的讲解入口。
- 题库页面夹具直接从当前 `QuestionBankService` 导出，不手工重写课程题或答案。可设置 `MATHTUTOR_TEST_PYTHON` 指向项目 Python，`PLAYWRIGHT_MODULE` / `CHROME_EXECUTABLE` 指向已有浏览器运行时；`LAYOUT_URL` 可指定隔离的前端端口。
- 题库的数量、独立数学复核与自动核验边界见[课程覆盖报告](../../../docs/QUESTION_BANK_COVERAGE.md)；学习记忆的真实 API / SQLite / WebSocket 证据见[记忆链路检查](../../../docs/LEARNING_MEMORY_AUDIT_20261016.md)。本轮没有模型调用或基准成绩变更。

以下截图来自隔离测试资料，展示界面与交互，不是学生真实数据或模型质量评测。

### 教学提示

![教学提示](../../../docs/images/learning-support/teaching-desktop.png)

### 对话资料

![对话资料](../../../docs/images/learning-support/documents-desktop.png)

### 知识库与问答范围

![知识库与问答范围](../../../docs/images/learning-support/knowledge-desktop.png)

### 学习记忆与课程参考题

![学习记忆](../../../docs/images/learning-support/memory-desktop.png)

![课程参考题](../../../docs/images/learning-support/question-bank.png)
