# MathTutor：阅读优先的学习工作台

本轮设计依据：用户实际桌面截图、ui-ux-pro-max 的内容优先 / 渐进披露 / 焦点不被遮挡规则，以及现有 React + Next.js 实现。设计系统检索中的营销首页结构不适用，未采用或保存为项目规范。保留产品标识、现有主题与业务入口，不改教学策略、会话持久化、模型调用或资料算法。

## 空间分配

- 阅读是主任务。顶栏 56px；桌面侧栏 248px，折叠 64px，窄屏折叠 56px。
- 题目 / 小目标来自服务器的 ProblemContext。只在顶栏左侧显示紧凑入口，详情点击展开为浮层，不增加横向分隔栏、不重新挤压正文。长题目在浮层内换行，Escape、外部点击或焦点离开后关闭。
- 解答最大阅读宽度 880px，正文 16px / 1.8 行距。去掉每条解答的白底大卡片；学生消息用浅色背景区分角色。
- 聊天记录只有一个主滚动容器。读者向上翻阅时，新回复不强制拉回末尾；“回到最新”恢复跟随。新发学生消息进入末尾。
- 输入框初始一行，按实际文本增高；上限为 160px 与视口高度 22% 的较小值。粘贴 / 拖入 / 上传图片、预览、移除与失败保留不变。
- 会话区域宽度不超过 1200px 时，工具面板浮在右侧，不压缩解答；更宽窗口允许并排。题目浮层与工具面板均可关闭。

## 全局一致性

- 资料、记忆、练习邀请使用同一 `mt-page` 容器，最大宽度 1040px、统一自适应边距。
- 非聊天页面由 Shell 主区域滚动，长列表不能被 `overflow-hidden` 截断。
- 设置保留分类结构，桌面分类栏 168px，800px 以下改为可横向滚动的分类入口。
- 只使用语义颜色变量（见下节“视觉语言”），不引入网络字体或新增动效依赖。主题类在 Tailwind safelist 中保留，避免运行时深色主题变量被裁剪。
- 图标保持 Lucide；图标按钮提供可访问名称，键盘焦点可见，尊重减少动画设置。

## 视觉语言（面向小初高学生的简洁风格）

参考 DeepSeek 对话界面：白底、单一冷蓝、细边框、大量留白，颜色只出现在“可操作”或“当前位置”上。ui-ux-pro-max 检索给出 Minimalism & Swiss Style 与中文无衬线字体，采用；其营销页结构、紫色配色与 Google Fonts 不适用（桌面离线、用户指定参考风格），未采用。

- 颜色一律来自 `web/app/globals.css` 的变量，组件内不写十六进制或 slate/blue 等色阶。
- `--primary` 是填充色（按钮、选中标记），始终配白字；`--primary-text` 是同色相的文字 / 图标色。深色模式下两者不同：没有一种蓝能同时在白字下和深色底上达到 4.5:1。
- `--primary-soft` / `--primary-border`：选中项、新建对话、提示底色；`--sidebar`：侧栏与工具面板底色；`--user-bubble`：学生消息。
- 红 / 绿 / 琥珀 / 玫红只表达状态（错误、成功、已展示提示、危险操作），不作装饰。
- 字体：系统无衬线（Segoe UI / PingFang SC / 微软雅黑），`--font-serif` 同样指向无衬线，避免中文宋体回退。
- 共用类：`mt-nav-item`、`mt-history-item`、`mt-new-chat`、`mt-icon-button`（`aria-pressed` 显示激活）、`mt-send-button`、`mt-brand-mark`。
- 空对话时 `mt-chat-column[data-empty]` 让欢迎语与输入框居中；首条消息后输入框回到底部。知识库范围入口在顶栏图标，说明文字在空状态中。

## 0.4.5 视觉升级：“草稿纸与墨水”

- 标志：`components/common/BrandMark.tsx`，三级台阶通向终点圆点，寓意“逐步走到答案”；启动页使用描线动画代替转圈。
- 母题：淡网格“草稿纸”（`.mt-paper`、`--paper`、`--grid-line`）只出现在数学发生的地方：展示公式、学生作答卡片、示例题、引导页解题纸条。单独成行的 `$$…$$` 公式（`p.math-line`）与 `.katex-display` 同样处理。
- 字体：界面仍为系统无衬线；题目与示例公式用 KaTeX 自带字体排版（随 `katex` 离线打包，不引入网络字体）。
- 页面风格：`lib/theme.ts` 提供 跟随系统 / 纸墨 / 夜读 / 暖纸 / 星夜，入口在侧栏底部与“设置 → 外观”。偏好存于 localStorage，并由 `app/layout.tsx` 中的启动脚本在首帧前应用；该模块位于 `features/math-tutor/desktop` 之外，不影响“桌面功能不使用浏览器存储”的密钥约束。
- 新增令牌：`--paper`、`--grid-line`、`--highlight`、`--focus-halo`、`--success(-soft)`、`--warning(-soft)`、`--sidebar-border`、`--shadow-xs…xl`、`--ease-out`、`--ease-spring`。
- 共用类：`mt-card`、`mt-btn`（`-primary` / `-ghost` / `-icon`）、`mt-eyebrow`、`mt-section-title`、`mt-input`、`mt-chip`、`mt-choice`、`mt-progress`。`.mt-page > header:first-child` 统一页面标题层级。
- 动效：入场 `mt-rise`（420ms ease-out）、按压缩放 0.92–0.98、悬停上浮 2px、思考点波动、风格切换 380ms 交叉淡入；全部受 `prefers-reduced-motion` 约束。

## 验证

- `cd web && npm test`：包括题目默认折叠、阅读结构、共享页面容器与主题保留测试。
- `cd web && npm run build`：生产编译与类型检查。
- `web/scripts/smoke-workspace-layout.mjs`：真实 Chrome 布局测试，HTTP / WebSocket 使用隔离测试数据，不读取用户聊天与密钥。
- 运行浏览器测试：先启动 `npm run dev -- --port 3197`，然后执行 `node scripts/smoke-workspace-layout.mjs`。环境未安装 Playwright 时，可通过 `PLAYWRIGHT_MODULE` 指向已有模块，`CHROME_EXECUTABLE` 指向本机 Chrome；`LAYOUT_URL` 可更改测试地址。无需把机器特有路径写进仓库。
- 覆盖 1280×800、1024×768、375×812、812×375，长解答、浮层尺寸与关闭、输入框伸缩、消息到达时保留阅读位置、路由间历史、长资料列表滚动、深色与减少动画。

## 本轮边界

本轮调整主工作台与共享页面布局，没有重写登录、首次引导、每一种弹窗或业务表单。浏览器测试使用模拟业务数据，不代表所有真实 Provider 或资料任务的端到端复验。本轮不修改版本、不打包安装、不 commit / push。
