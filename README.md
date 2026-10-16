# MathTutor

**一个把“数学教学闭环”和“可追溯资料问答”放进本地桌面端的 K12 数学学习助手。**

MathTutor 不是把大模型套进聊天框。它把题目解析、受限求解与验证、分级提示、作答证据、学习画像、个人资料检索和引用追踪连接成一个可恢复的产品流程。学生可以先尝试、再逐级获得帮助；模型负责表达和整理，应用负责权限、证据、预算、答案披露与数据生命周期。

**0.6.3 Windows x64** [发布页](https://github.com/coscatld/MathTutor/releases/tag/v0.6.3) · [下载安装包](https://github.com/coscatld/MathTutor/releases/download/v0.6.3/MathTutor-0.6.3-win-x64.exe) · [SHA-256 校验文件](https://github.com/coscatld/MathTutor/releases/download/v0.6.3/SHA256SUMS-windows.txt) · [更新说明](docs/RELEASE_0.6.3.md)

[项目定位](#项目定位) · [核心功能](#核心功能) · [差异化亮点](#差异化亮点) · [Benchmark](#benchmark-与当前结果) · [快速开始](#快速开始) · [能力说明](#资料问答与能力说明)

## 项目定位

MathTutor 面向希望“学会过程”而不只是“拿到答案”的学生，也面向需要检查资料来源、教学行为和学习依据的家长、教师与开发者。它由 Electron 桌面壳、Next.js 前端和 Python 产品服务组成，运行与打包不依赖 DeepTutor 源码仓库。

```mermaid
flowchart LR
    A[题目与学生作答] --> B[解析 / 求解 / 验证]
    B --> C[教学策略与答案披露]
    C --> D[模型表达或本地模板]
    D --> E[输出守卫与完成性协议]
    F[个人资料] --> G[解析 / 切片 / 作用域检索]
    G --> H[原文读取 / 支持检查 / 引用]
    H --> D
    A --> I[学习证据]
    I --> J[学习画像 / 阶段复盘 / 后续练习]
```

模型服务可以替换或不配置。未配置模型时，受支持的本地求解、验证、学习记录和模板辅导仍可使用；生成式讲解与知识综合会降级。

## 核心功能

| 场景 | 功能 |
|---|---|
| 数学辅导 | 对受支持的算术、整式、一元一次/二次方程、二元一次方程组、一元一次不等式和根为有理数的一元二次不等式解析、求解和验证，结合学生作答提供分级提示与反馈；未解决的题目先看过一次提示才能查看完整答案 |
| 函数图像与数形结合 | 说「画出 y = x^2 - 2x - 3 的图像」或在题目下点「看图像」；也能画隐式曲线（椭圆、双曲线、圆等）、参数与极坐标曲线、不等式区域、点、线段、多边形、切线，参数带滑块和播放，动点留轨迹，距离 / 角度 / 面积等读数实时更新（如「演示椭圆 x^2/4+y^2/3=1 上的动点 P(2cos t, √3 sin t) 到焦点 F(1,0) 的距离」）。表达式由白名单解析器编译，坐标由应用计算；配置模型后，复杂描述可由模型提出定义，标注为未核验的示意图 |
| 题库 | 按人教版教材顺序整理一年级上册到高三下的知识点（高中为人教A版 2019 必修与选择性必修），在设置里选好学段后只显示该学段的册目；知识点下有经本地验证器核验的练习题（一键开始辅导）和数形结合演示 |
| 初次使用 | 配置模型服务；通过可跳过的 10 道选择题初评获得暂定练习起点 |
| 练习与学习记录 | 保存会话、作答与可信学习事件，提供练习邀请、学习画像（含诊断出的错误概念）和阶段复盘 |
| 自有资料问答 | 导入文本、Markdown 和可提取文字的 PDF，检索相关片段并查看引用原文 |
| 知识库管理 | 管理资料空间、版本、标签、双向链接、检索范围、草稿与笔记，区分当前证据和历史引用凭证 |
| 受控模型工具 | 知识模式下允许检索、读取、验证、草拟、保存笔记和提出练习；普通数学提问时模型可自行调用 `verify_math` 核对结论，并按「画图技能」调用 `draw_scene` 在画布上配图；所有工具均由应用授权并执行 |
| 画图技能 | 模型配图一律通过 `draw_scene` 交给应用在 canvas 上绘制，约束写在 `skills/canvas_drawing/SKILL.md`；字符画、Markdown 图片、Mermaid / TikZ / SVG / 绘图代码会被移除并改为画布作图 |
| 回答交付 | 讲解中可解析的算式经 `verify_math` 核对；条件受限或超出语法范围的推理标为未核验，被反驳时让模型改正一次，仍错则原处标出；记录停止原因、token、费用与 PARTIAL 状态 |
| 运行诊断 | 每轮留下不含原文的结构化记录，重启不丢；诊断接口给出失败率、延迟、费用、算式核验与 DKT 调节等指标和告警阈值；可在隔离库中回放失败的对话 |
| 费用与预算 | 按自填单价估算每轮费用，可设每日费用或 token 预算，超出后当天改用本地模板教学 |
| 本地数据管理 | 管理个人记忆、聊天历史、资料和备份，支持已有的备份验证与恢复流程 |

初评采用可解释的规则题组给出练习起点。学习画像以已记录的学习证据为主：独立、受助、看答案后的作答分开统计，阅读、收藏或一句“懂了”只作为自我报告。

## 差异化亮点

下面这些机制都在同一个可运行产品中实现，每一项都有对应的源码、自动化测试和评测记录。

| 差异化设计 | 实际实现 | 对用户的价值 |
|---|---|---|
| 教学与表达分层 | 确定性求解/验证、教学策略、模型表达和输出守卫分开；低提示等级不携带完整答案 | 模型措辞可以变化，答案披露边界仍由产品控制 |
| 先授权、后检索 | owner、会话绑定、启用状态和资料范围在候选检索前进入 SQL/仓储约束 | 不依赖模型“自觉”避开无权读取的资料 |
| 可追溯到原文区间 | 引用绑定资料版本、字符区间、正文哈希和读取凭证；猜测 ID、扩大区间、跨会话读取会被拒绝 | 可以回到模型实际依据的原文，而不是只看到一个文件名 |
| 图像由应用计算 | 函数、曲线、区域、动点等图形的表达式由白名单解析器编译，坐标、交点和读数由应用计算，前端只绘制服务端标记的图像消息 | 图上的交点、顶点和读数来自计算，不来自模型的描述 |
| 区分算式核验范围 | 可解析的算式经 `verify_math` 核对；未绑定原题的条件推理不冒充完整证明；失败改写不能用空洞回退替换原解答 | 区分已核对、无法核对与被反驳的内容，明确可信范围 |
| 应用授权的模型工具 | 只开放固定 schema 的知识与数学工具；没有 shell、任意 Python、SQL、联网或任意 MCP 权限 | 既能完成“查资料—读原文—核验—保存笔记”，又限制模型执行面 |
| 来源支持与数学正确分开 | quote 要逐字存在，summary 要做支持检查；数学条件另由受限验证器或独立复核判断 | 不把“资料里这样写了”误当成“数学上一定正确” |
| 完成性是一等状态 | 保存 `finish_reason`、步骤/token 预算、续写上下文和最终可见正文；截断、不确定拼接、失败模板保持 PARTIAL/FAILED | 用户能分辨完整回答和可继续恢复的部分回答 |
| 证据驱动的学习画像 | 可信作答事实、明确偏好和待验证假设分开；删除证据会更新投影 | 个性化建议能说明依据，也允许纠错和撤销 |
| 本地产品闭环 | SQLite、资料、会话、备份和系统凭据库均由桌面应用管理；升级前自动备份并支持验证/恢复 | 适合个人长期积累资料，不需要另搭 RAG 服务和数据库 |

### 为什么选择 MathTutor

- 你需要的是**循序提示和作答反馈**，而不是默认直接给答案的通用聊天。
- 你想使用自己的讲义和笔记，并要求回答能回到**真实资料版本与原文区间**。
- 你关心本机数据、跨会话权限、删除语义、备份恢复和模型凭据存放。
- 你希望模型能力可以替换，同时保留本地求解、验证、教学策略和模板降级路径。
- 你看重可复现的工程证据：固定多轮评测、发布门、逐轮诊断记录和失败回放都在仓库里，可以自己跑一遍。
- 你想用图形理解数学：曲线、区域、动点和读数可以直接在对话里拖动和播放。

## Benchmark 与当前结果

### 我们对比的 benchmark 是什么

项目当前**没有**把自己与 ChatGPT、Khanmigo 或其他商业产品做公开的同题 head-to-head，也没有参加外部教育产品排行榜。因此 README 不使用“优于某竞品”的结论。现有 benchmark 比较的是本项目不同检索/工具链版本，以及当前生产链在固定语料上的回归表现：

1. **Official RAG easy set**：6 份中文数学资料、12 个真实切片、9 个查询，覆盖规范术语、口语改写、公式、中英/LaTeX 混排和近义干扰。
2. **RAG hard set**：17 个切片、5 个查询，强制制造多切片竞争、上下文扩展、同节干扰和跨章节边界。
3. **权限与引用探针**：覆盖未绑定资料、跨 owner、禁用/删除、空 scope、非法区间、跨会话读取和历史引用凭证。
4. **Knowledge 链路对比**：使用相同 5 个查询，对比冻结旧链、新链原生 tools 和新链 JSON 兼容协议，核对真实工具读取与笔记保存，而不是只比较回答措辞。
5. **真实模型开发回归**：固定 Provider、模型、问题、资料与预算，逐声明区分证据支持、数学正确性、引用归属和任务完成；AI 复核始终标为 provisional。

官方检索 benchmark 走真实生产路径，而不是平行 mock：

```text
真实资料 → SQLite 摄入/切片/FTS → DocumentIndexManager
        → ConversationRetrievalOrchestrator → ProductionReranker
        → ContextExpander → EvidencePack
```

### 已记录的结果

| 评测组 | 样本 | 结果 | 应如何解读 |
|---|---:|---|---|
| Easy retrieval | 9 queries | R@5 1.000、MRR@5 1.000、nDCG@5 1.000、Hit@1 1.000 | 作为检索回归的基线 |
| Hard retrieval | 5 queries / 17 chunks | R@5 1.000、MRR@5 0.900、nDCG@5 0.949、Hit@1 0.800 | 更接近真实资料的检索难度 |
| Hard context | 5 queries | Context Precision 0.344、Context Recall 1.000、Noise Ratio 0.656 | 相关内容全部召回，上下文精简是下一步调优方向 |
| Citation attribution | 4 claim cases / 5 links | Precision 0.875、Recall 1.000 | 衡量引用归属到正确来源 |
| Historical receipts | 1 合法 / 4 非法探针 | 合法读取 1/1；未授权拒绝 4/4 | 分别验证可用性与拒绝能力 |
| Knowledge old vs new | 5 queries | 三组命中均为 4/5；旧链读取 0、保存 0，新链两种协议均读取 2 个来源并新增 1 篇笔记 | 新链完成「检索—读原文—保存笔记」完整工具闭环 |
| 固定多轮辅导评测 | 15 个多轮场景 / 184 项检查 | 模板教学 15/15 通过，六个维度（数学正确、目标相关、学生证据、可执行性、适配、连贯）均为 1.0，发布门通过 | 规则与本地验证器自动评分，覆盖答案边界、证据分流、算式核验和状态机；`--mode live` 可对任意模型跑同一套门。见 [评测说明](docs/eval/TUTOR_MULTITURN_EVAL.md) |

Context Redundancy 记录值为 0.913，其中 0.831 来自 hard fixture 资料本身的 4-gram 重复。检索指标、引用合法性、来源支持和数学正确性分四个维度分别评测。

完整定义、分子/分母、语料版本、评分器与复现命令见 [RAG 评测报告](docs/RAG_EVALUATION.md)。

## 版本与发布状态

当前版本为 **0.6.3**，Windows x64 安装包与 SHA-256 校验文件见 [v0.6.3 发布页](https://github.com/coscatld/MathTutor/releases/tag/v0.6.3)。macOS 最近发布的安装包仍为 0.5.0。数据库 migration head 为 **024**（新增逐轮诊断记录表，从 0.5.0 升级时先做备份，再自动迁移）。

### 0.6.3

高中模式粘贴题目后保存原题与讨论记录，Agent 自主选择追问、解释和配图；自然追问保留原题。常规核验范围在正文后折叠，实际错误保持醒目标注。自由辅导不写独立作答或掌握率。详见 [0.6.3 发布说明](docs/RELEASE_0.6.3.md)。

### 0.6.2

「画一个图展示一下双曲线」可直接展示标准示例和参数滑块，未配置模型也能画；「都可以」「你定」会续接前面的作图请求。相关数学概念与追问允许模型主动调用画布，给定的方程和条件仍保留。详见 [0.6.2 发布说明](docs/RELEASE_0.6.2.md)。

### 0.6.1

修复首次并发启动导致的数据库迁移异常：桌面程序增加单实例保护，迁移使用进程锁和完整事务。已出现 `023 + 024` 版本记录的数据库，会先备份并校验完整性及结构，再自动恢复；启动失败会显示具体错误，并写入用户数据目录的 `logs/startup.log`。关闭旧版后安装新版即可，无需删除学习数据或改英文目录。详见 [0.6.1 发布说明](docs/RELEASE_0.6.1.md)。

### 0.6.0

完整更新与升级说明见 [0.6.0 发布说明](docs/RELEASE_0.6.0.md)，三平台验证状态见 [GitHub Actions](https://github.com/coscatld/MathTutor/actions/workflows/cross-platform.yml)。

- **讲解可信**：讲解中的算式逐一经 `verify_math` 核对，未通过时让模型改正一次；普通聊天按句流式显示，只放出已核对的句子；数学提问时模型可自行调用 `verify_math`。
- **数形结合**：函数、隐式曲线（椭圆、双曲线、圆等）、参数与极坐标曲线、不等式区域、点、线段、多边形、切线；参数滑块与播放、动点轨迹，距离 / 角度 / 面积读数实时更新，不配置模型也能从「演示椭圆上的动点 P(2cos t, √3 sin t) 到焦点 F(1,0) 的距离」这类句子直接成图。
- **题型**：新增根为有理数的一元二次不等式，按解集精确比对作答。
- **学生模型**：所有已诊断的错误类型都会影响下一道练习；DKT 只在有技能映射和本人作答时调节一档，可用 `MATHTUTOR_DKT_TEACHING=off` 关闭。
- **评测与诊断**：固定多轮评测与发布门；每轮留下结构化诊断记录，重启不丢，提供失败率、延迟、费用等指标和告警阈值，可在隔离库中回放失败的对话。
- **费用与预算**：按自填单价估算每轮费用，可设每日预算，超出后当天改用本地模板教学。
- **数据加密**：可选的 SQLCipher 整库加密，备份文件加密并提供恢复密钥。
- **题库与学段**：小学到高中 24 册、149 个单元、359 个知识点，按教材顺序排列；68 个知识点配有 449 道已验证练习题，42 个知识点配有数形结合演示；设置 → 学段 决定题库默认显示的册目。
- **画图技能**：模型配图只能通过 `draw_scene` 在画布上绘制，讲解与图一起作为「讲解配图」消息呈现。

### 0.5.0

- 未解决的题目要先看过一次提示，才能查看完整答案；已答对或已看过答案的题目仍可随时回看。
- 学习画像的「活跃错误概念」按作答诊断出的错误规则统计，同一技能之后独立答对即视为解除；数据导出列出同样的错误概念。
- 新增函数图像：服务端计算坐标，前端用 canvas 绘制。题目未完成时不标出零点和交点，看过这道题的图像后再作答记为「受助」。
- 数据库结构不变，从 0.4.5 升级无需数据迁移。完整说明见 [CHANGELOG](CHANGELOG.md)。

### 发布记录

| 版本 | 内容 | 安装包 | SHA-256 |
|---|---|---|---|
| [`v0.6.2`](https://github.com/coscatld/MathTutor/releases/tag/v0.6.2) | 标准曲线示例、作图上下文续接与主动配图 | [`MathTutor-0.6.2-win-x64.exe`](https://github.com/coscatld/MathTutor/releases/download/v0.6.2/MathTutor-0.6.2-win-x64.exe) | [`SHA256SUMS-windows.txt`](https://github.com/coscatld/MathTutor/releases/download/v0.6.2/SHA256SUMS-windows.txt) |
| [`v0.6.1`](https://github.com/coscatld/MathTutor/releases/tag/v0.6.1) | 修复并发启动、迁移异常恢复与启动日志 | [`MathTutor-0.6.1-win-x64.exe`](https://github.com/coscatld/MathTutor/releases/download/v0.6.1/MathTutor-0.6.1-win-x64.exe) | [`SHA256SUMS-windows.txt`](https://github.com/coscatld/MathTutor/releases/download/v0.6.1/SHA256SUMS-windows.txt) |
| [`v0.6.0`](https://github.com/coscatld/MathTutor/releases/tag/v0.6.0) | 讲解公式核验、交互式数形结合、K-12 题库 | [`MathTutor-0.6.0-win-x64.exe`](https://github.com/coscatld/MathTutor/releases/download/v0.6.0/MathTutor-0.6.0-win-x64.exe) | [`SHA256SUMS-windows.txt`](https://github.com/coscatld/MathTutor/releases/download/v0.6.0/SHA256SUMS-windows.txt) |
| [`v0.5.0`](https://github.com/coscatld/MathTutor/releases/tag/v0.5.0) | 先看提示再看答案、错误概念统计、函数图像 | `MathTutor-0.5.0-mac-arm64.dmg` | `3b7cd4da265e7a74a41b7a3a3a4fdbaf2bc0a71c55462e612a9e48dfd9c45861` |
| | | `MathTutor-0.5.0-win-x64.exe` | `ab22ece2ee97b15a861ad81bb15a891c9f0eafadd4cbf9359519249bee27ac3a` |
| [`v0.4.5`](https://github.com/coscatld/MathTutor/releases/tag/v0.4.5) | 页面风格与视觉焕新，不改教学策略 | `MathTutor-0.4.5-mac-arm64.dmg` | `f0f8e7f7c1d37ac57a9143fe59494c29c9433a5ca14cddb3634e119d573003ff` |
| | | `MathTutor-0.4.5-win-x64.exe` | `b20771b1aa7a591d70a77cb122e0bb592d822074dd27844058fcad4abd37c14e` |

macOS 安装包发布前都通过打包后冒烟测试（启动、作答、重启、备份恢复、退出清理）；Windows 安装包由 GitHub Actions 构建。macOS 首次打开时在「系统设置 → 隐私与安全性」中点「仍要打开」，Windows 出现 SmartScreen 提示时选「仍要运行」。

### 更早的版本

- 0.4.4 安装包附带已训练的 DKT（ASSISTments 2009，seed 29）。映射得上的技能用这份权重量出一个概率，并据此调整下一步提示和练习难度。见 [0.4.4 发布说明](docs/RELEASE_0.4.4.md)。
- 0.4.3 是界面版本，[`v0.4.3`](https://github.com/coscatld/MathTutor/releases/tag/v0.4.3) 以 pre-release 发布，附 Windows x64 安装包。见 [0.4.3 发布说明](docs/RELEASE_0.4.3.md)。
- 0.4.2 完成 RAG 集成，见 [PR #2](https://github.com/coscatld/MathTutor/pull/2)。

下载请查看 [GitHub Releases](https://github.com/coscatld/MathTutor/releases)，并用对应版本的 SHA-256 校验文件或上表历史摘要核对。

## 快速开始

### 环境准备

- 开发系统：Windows、macOS 或 Linux。
- Python：建议使用 **3.12**；项目声明支持 `>=3.11,<3.14`。
- Node.js 与 npm：本地 Windows 打包已验证 **Node.js 24.19.0**；现有源码 CI 使用 Node.js 20。安装依赖使用仓库锁文件和 `npm ci`。

在项目根目录创建 Python 虚拟环境：

```bash
python -m venv .venv
```

Windows PowerShell 激活方式：

```powershell
.\.venv\Scripts\Activate.ps1
```

macOS / Linux 激活方式：

```bash
source .venv/bin/activate
```

安装后端开发依赖：

```bash
python -m pip install -e ".[dev]"
```

### 方式一：浏览器开发模式

在已激活虚拟环境的项目根目录启动后端：

```bash
python -m mathtutor
```

另开终端，进入项目的 `web` 目录启动前端：

```bash
cd web
npm ci
npm run dev
```

默认后端地址为 `http://127.0.0.1:8001`，浏览器访问 `http://127.0.0.1:3000`。

本机默认使用 loopback 单用户流程，无需注册或登录。首次进入时配置模型服务商、模型与 API Key，也可跳过模型配置，使用模板教学。配置后按页面引导完成或跳过初评，进入工作台。远程或网络部署的认证边界不等同于本机默认模式。

### 方式二：源码版桌面应用

完成 Python 依赖安装后，从项目根目录执行：

```bash
cd web
npm ci
npm run build
cd ../desktop
npm ci
npm start
```

桌面壳使用项目根目录的 `.venv`，自动启动 Python 服务、Verifier Worker 和 Next.js 前端，并选择本机随机端口。无需同时保留浏览器开发模式的两个服务进程。

## 资料问答与能力说明

资料问答的基础路径为：**导入资料 → 本地解析与切片 → 检索与上下文组装 → 读取证据 → 回答与引用**。检索由共享 orchestrator 组织，工具读取受会话权限、资料版本和原文区间约束。

| 能力 | 说明 |
|---|---|
| 文档解析 | 支持文本、Markdown 和可提取文字的 PDF；安装 `pdf-rich` 后启用增强版式解析 |
| 检索 | 内置词法检索开箱即用；安装 `embedding` 后叠加向量检索 |
| 引用与来源 | 引用绑定资料版本和原文区间，可随时回到原文；来源支持与数学正确分开判断 |
| Knowledge 摘要 | 先读取证据、再做支持检查，原文引用与 AI 摘要分开呈现 |
| 数学验证 | 算术与分数、整式、一元一次 / 二次方程、二元一次方程组、一元一次不等式、一元二次不等式由本地求解器和验证器逐步核验；讲解中的算式逐一核对 |
| 数形结合 | 函数、隐式曲线、参数与极坐标曲线、区域、点线与多边形、切线，带参数滑块、动画、轨迹和实时读数 |
| 自动续写 | 长回答被截断时保留已生成的正文，界面提供「继续讲完」 |

按需安装增强依赖：

```bash
python -m pip install -e ".[embedding]"
python -m pip install -e ".[pdf-rich]"
```

## 数据、模型配置与备份

应用的数据库、上传资料和备份保存在本机。**使用外部模型服务时，请求中的问题、上下文和相关资料片段会发送给你配置的服务商**；只用本地模板教学或本机 Ollama 时，数据不出本机。

- 源码后端默认使用当前目录下的 `data/`；可通过 `MATHTUTOR_DATA_ROOT` 指定数据目录，或通过 `MATHTUTOR_DB_PATH` 指定数据库路径。
- 桌面版使用独立的用户数据目录，退出应用会停止本地子进程，并保留学习资料和历史。
- API Key 通过 `SecretStore` 管理；macOS 使用 Keychain，Windows 使用 Credential Manager。
- 数据库加密可选（默认关闭）：在「设置 → 高级 → 数据加密」开启后，下次启动时把本机数据库转换为 SQLCipher 加密库，转换前后都做完整性和行数校验，失败保持原样。密钥只存在系统钥匙串 / 凭据管理器中。只要系统密钥存储可用，备份文件始终加密；请在同一处「显示恢复密钥」并妥善保存，钥匙串条目丢失时恢复备份需要它。导入的资料原文件保存在数据目录，建议同时开启系统全盘加密（FileVault / BitLocker）。不要把凭据、私人配置、用户数据库或原始模型请求日志提交到仓库。
- 0.5.0 的数据库 migration head 为 **023**（自 0.4.2 起未变）。升级前使用应用内备份功能创建并验证备份，再正常退出应用。
- 恢复旧备份可能缺少之后产生的新资料和聊天，请先保存当前数据。代码回滚不会自动恢复数据库；不要手动删除活跃数据库的 WAL/SHM 文件。

## 开发与测试

安装 Python 开发依赖，以及 `web`、`desktop` 的 npm 依赖后，在项目根目录运行：

```bash
python scripts/check.py
```

该入口执行后端与 Python 桌面测试、Web 测试、前端生产构建和 Node.js 桌面契约测试。发行运行时验证需要目标平台的独立 Python 运行时（见下文「构建安装包」）。

评测分别记录检索、可见上下文、引用权限、语义支持、数学正确性、任务完成和性能成本。`PROVISIONAL_AI` 表示 AI 初审结果，`BUDGET_BLOCKED` 表示该次真实调用因预算限制跳过。具体口径与结果见 [RAG 评测报告](docs/RAG_EVALUATION.md)。

```text
src/mathtutor/   Python 产品服务、教学流程、检索与验证
web/            Next.js 工作台
desktop/        Electron 桌面壳、运行时与打包脚本
tests/          自动化测试与测试夹具
scripts/        工程检查、评测与回放入口
docs/           架构、实现、评测与版本文档
```

测试夹具和评测资料不作为用户知识库的默认教学内容。

## 构建安装包

公开发行时按现有工作流配置签名证书，并对最终产物做包外验证；各平台的运行时、打包与发行约束见 [桌面发行设计](docs/ADR_DESKTOP_DISTRIBUTION.md)。

### Windows x64

Windows 安装包在 Windows 上构建：可以在 GitHub Actions 手动运行 `windows-installer.yml`，从产物 `MathTutor-windows` 下载；也可以在 Windows PowerShell 中从项目根目录执行：

```powershell
Set-Location web
npm ci
Set-Location ..\desktop
npm ci
npm run package:win
```

脚本构建 Next.js standalone 前端，准备并验证独立 Python 运行时，然后生成 NSIS 安装器：

```text
desktop/dist/MathTutor-0.6.3-win-x64.exe
```

使用 Node.js 22 时，项目路径含中文等非 ASCII 字符会让运行时校验中的 `fs.cpSync` 崩溃（无错误输出）。请从纯英文路径构建，或向 `desktop/scripts/build-windows.ps1` 传入英文路径的 `-RuntimePath`，或改用已验证的 Node.js 24.19.0。下载后可检查摘要：

```powershell
Get-FileHash -Algorithm SHA256 .\MathTutor-0.6.3-win-x64.exe
```

### macOS（Apple 芯片）

macOS 安装包需要一个可重定位、带 numpy 的独立 Python 运行时（python-build-standalone CPython 3.11）。用 `desktop/scripts/prepare-macos-python-runtime.py` 准备后，指向它构建并冒烟：

```bash
export MATHTUTOR_PYTHON_RUNTIME=$PWD/.runtime/<python-runtime-dir>
(cd web && npm ci && npm run build)
npm ci --prefix desktop
npm run package:mac:unsigned --prefix desktop
npm run smoke:packaged:mac --prefix desktop
shasum -a 256 desktop/dist/MathTutor-0.6.0-mac-arm64.dmg
```

普通虚拟环境不可重定位，不能作为打包运行时。下载 Electron 较慢时，可设置 `ELECTRON_MIRROR` 与 `ELECTRON_BUILDER_BINARIES_MIRROR` 使用镜像。

## 文档导航

| 文档 | 内容 |
|---|---|
| [CHANGELOG](CHANGELOG.md) | 各版本改动与升级说明 |
| [固定多轮辅导评测](docs/eval/TUTOR_MULTITURN_EVAL.md) | 自动评分的多轮场景、六维度、发布门与最近结果 |
| [初评与选择题](docs/INITIAL_ASSESSMENT.md) | 首次评估、跳过与恢复、练习起点的含义 |
| [RAG 架构](docs/RAG_ARCHITECTURE.md) | 共享检索、上下文与证据工具路径 |
| [知识工作台](docs/KNOWLEDGE_WORKBENCH_DELIVERY.md) | 资料管理、问答与引用功能 |
| [RAG 实施报告](docs/RAG_IMPLEMENTATION_REPORT.md) | 实现范围、工程证据与遗留事项 |
| [RAG 评测报告](docs/RAG_EVALUATION.md) | 指标口径、测试结果和验收限制 |
| [0.4.2 离线数学修复](docs/OFFLINE_MATH_REPAIR_042.md) | 数学条件、退化情况与保存响应回放 |
| [桌面发行设计](docs/ADR_DESKTOP_DISTRIBUTION.md) | 平台运行时、打包和交付约束 |

## 许可证

项目采用 [Apache License 2.0](LICENSE)。第三方组件说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
