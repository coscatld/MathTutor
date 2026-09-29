# MathTutor

**面向 K12 数学学习的桌面辅导应用：围绕题目提供分级提示、练习反馈与可追溯的资料问答。**

MathTutor 将本地求解与验证、学习记录和模型辅助讲解结合在一个工作台中。你可以提交题目、尝试作答，也可以导入自己的学习资料，查看回答所引用的原文。应用由 Electron 桌面壳、Next.js 前端和 Python 服务组成，运行与打包不依赖 DeepTutor 源码仓库。

[快速开始](#快速开始) · [资料问答与能力边界](#资料问答与能力边界) · [开发与测试](#开发与测试) · [构建安装包](#构建安装包) · [文档导航](#文档导航)

## 可以做什么

| 场景 | 功能 |
|---|---|
| 数学辅导 | 对受支持的题型解析、求解和验证，结合学生作答提供分级提示与反馈 |
| 初次使用 | 配置模型服务；通过可跳过的 10 道选择题初评获得暂定练习起点 |
| 练习与学习记录 | 保存会话、作答与学习状态，提供练习邀请和个人学习档案 |
| 自有资料问答 | 导入文本、Markdown 和可提取文字的 PDF，检索相关片段并查看引用原文 |
| 知识库管理 | 管理资料与检索状态，区分当前证据和历史引用凭证 |
| 本地数据管理 | 管理个人记忆、聊天历史、资料和备份，支持已有的备份验证与恢复流程 |

未配置模型服务时，受支持的本地求解、验证与模板辅导仍可使用；生成式讲解能力会降级。初评采用可解释规则，**不是已经完成目标域校准的 DKT 能力定级**。

## 版本与发布状态

当前源码版本为 **0.4.2**。源码版本、安装包工程验证和真实回答质量分别记录。

以下为 **2026-09-20 已留存的 0.4.2 集成与发布记录**，不是对后续发布状态的自动更新：

- [PR #2](https://github.com/coscatld/MathTutor/pull/2) 已合并，Windows、macOS、Ubuntu 的源码 CI 通过。
- Windows x64 包已完成仓库外工程验证，共享发行 smoke 的 19 项断言通过。
- 该 Windows 包未签名，当时仅建立 Release 草稿，未完成正式发布或部署；实际安装/卸载尚未验证。
- 真实语义质量仍有历史失败项和待人工复核项。离线回放通过不等于真实模型质量通过。

下载与发布状态请查看 [GitHub Releases](https://github.com/coscatld/MathTutor/releases)。旧版本安装包不能代表当前源码功能或当前版本验证结果。

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

## 资料问答与能力边界

资料问答的基础路径为：**导入资料 → 本地解析与切片 → 检索与上下文组装 → 读取证据 → 回答与引用**。检索由共享 orchestrator 组织，工具读取受会话权限、资料版本和原文区间约束。

| 能力 | 当前边界 |
|---|---|
| 文档解析 | 保证文本、Markdown 与 pypdf 可读取 PDF 的基础解析；扫描件 OCR 未实现 |
| 检索 | 默认可用基线为词法检索；Embedding 是可选依赖，不是桌面包保证包含的能力 |
| PDF 增强解析 | `pdf-rich` 为可选依赖；未安装时使用基础解析路径 |
| 引用与来源 | 可读取合法范围的来源及历史引用凭证；来源合法不等于内容支持回答 |
| Knowledge 摘要 | 产品工具路径包含证据读取与支持检查；生产支持检查不能替代独立评审 |
| 数学验证 | 仅覆盖受限求解器和验证器支持的表达式、条件与步骤；超出能力不能视为已验证 |
| 自动续写 | 对受支持的接缝保留连续正文；真实截断、不确定拼接等仍可能返回 PARTIAL，可按界面继续处理 |

需要增强依赖时，可在源码环境中按需安装：

```bash
python -m pip install -e ".[embedding]"
python -m pip install -e ".[pdf-rich]"
```

安装额外依赖不等于模型已配置、向量索引已建立或对应质量已通过验证。模型正常停止、引用操作通过，以及部分算式被标为 `VERIFIED`，都不能扩大解释为整篇自然语言回答数学正确。来源本身含错时，也必须区分“来源支持”和“数学正确”。

## 数据、模型配置与备份

应用的数据库、上传资料和备份保存在本机。**使用外部模型服务时，请求中的问题、上下文和相关资料片段仍可能发送给所配置的服务商**，不能将本地存储理解为全程离线。

- 源码后端默认使用当前目录下的 `data/`；可通过 `MATHTUTOR_DATA_ROOT` 指定数据目录，或通过 `MATHTUTOR_DB_PATH` 指定数据库路径。
- 桌面版使用独立的用户数据目录，退出应用会停止本地子进程，并保留学习资料和历史。
- API Key 通过 `SecretStore` 管理；macOS 使用 Keychain，Windows 使用 Credential Manager。不要把凭据、私人配置、用户数据库或原始模型请求日志提交到仓库。
- 0.4.2 的数据库 migration head 为 **023**。升级前使用应用内备份功能创建并验证备份，再正常退出应用。
- 恢复旧备份可能缺少之后产生的新资料和聊天，请先保存当前数据。代码回滚不会自动恢复数据库；不要手动删除活跃数据库的 WAL/SHM 文件。

## 开发与测试

安装 Python 开发依赖，以及 `web`、`desktop` 的 npm 依赖后，在项目根目录运行：

```bash
python scripts/check.py
```

该入口执行后端与 Python 桌面测试、Web 测试、前端生产构建和 Node.js 桌面契约测试。没有准备目标平台的独立 Python 运行时时，发行运行时验证会显示跳过，不能据此宣布安装包验证通过。

评测分别记录检索、可见上下文、引用权限、语义支持、数学正确性、任务完成和性能成本。`PROVISIONAL_AI` 表示 AI 初审，不能写成人工验收；`BUDGET_BLOCKED` 表示真实调用未执行，不是质量通过。具体口径与结果见 [RAG 评测报告](docs/RAG_EVALUATION.md)。

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

### Windows x64

在 Windows PowerShell 中，从项目根目录执行：

```powershell
Set-Location web
npm ci
Set-Location ..\desktop
npm ci
npm run package:win
```

现有脚本构建 Next.js standalone 前端，准备并验证独立 Python 运行时，然后生成 NSIS 安装器。0.4.2 产物路径为：

```text
desktop/dist/MathTutor-0.4.2-win-x64.exe
```

本地构建默认未签名。公开发行需满足现有工作流的 Authenticode 签名要求，并对最终产物重新进行包外验证；构建成功不等于正式发布。下载后可用 PowerShell 检查摘要，与对应发行记录比较：

```powershell
Get-FileHash -Algorithm SHA256 .\MathTutor-0.4.2-win-x64.exe
```

macOS 与 Linux 使用仓库已有平台打包流程，参考 [桌面发行设计](docs/ADR_DESKTOP_DISTRIBUTION.md)。三平台源码 CI 通过不能替代各平台安装包的启动、迁移、签名或安装/卸载验证。

## 文档导航

| 文档 | 内容 |
|---|---|
| [初评与选择题](docs/INITIAL_ASSESSMENT.md) | 首次评估、跳过与恢复、练习起点的含义 |
| [RAG 架构](docs/RAG_ARCHITECTURE.md) | 共享检索、上下文与证据工具路径 |
| [知识工作台](docs/KNOWLEDGE_WORKBENCH_DELIVERY.md) | 资料管理、问答与引用功能 |
| [RAG 实施报告](docs/RAG_IMPLEMENTATION_REPORT.md) | 实现范围、工程证据与遗留事项 |
| [RAG 评测报告](docs/RAG_EVALUATION.md) | 指标口径、测试结果和验收限制 |
| [0.4.2 离线数学修复](docs/OFFLINE_MATH_REPAIR_042.md) | 数学条件、退化情况与保存响应回放 |
| [桌面发行设计](docs/ADR_DESKTOP_DISTRIBUTION.md) | 平台运行时、打包和交付约束 |

## 许可证

项目采用 [Apache License 2.0](LICENSE)。第三方组件说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
