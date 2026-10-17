# MathTutor 0.7.0 正式版更新说明

正式名称：**MathTutor——基于学习过程追踪与可验证解题的开源数学智能辅导系统**。

## 2026-10-17 r3：普通数学提问与失败提示修复

两个平台的当前下载为 [Mac Apple Silicon DMG（r3）](https://github.com/coscatld/MathTutor/releases/download/v0.7.0/MathTutor-0.7.0-mac-arm64-r3.dmg)和 [Windows x64 EXE（r3）](https://github.com/coscatld/MathTutor/releases/download/v0.7.0/MathTutor-0.7.0-win-x64-r3.exe)，应用版本仍为 **0.7.0**。均来自修复提交 `d4ad9a08362c1d23f14240669c669bd455d755b0`；原 v0.7.0 标签保持不变。

普通数学问题曾被无关的作图说明和工具定义占满内部预算，请求在模型调用前就失败，随后却显示“结构化求解器不支持”的兜底文案。r3 按当前问题决定是否提供作图工具，精简与原生 schema 重复的说明，保留调用、长度、数学核验和插件授权限制；模型、超时和长度失败会明确提示，不伪装成已完成回答。

- 本地相关回归测试 250 项通过，涵盖原始集合题、图形、会话资料、记忆、图片、工具预算、失败状态与重放；使用本地传输桩，没有付费模型调用。
- Mac 使用安装包内 Python 与源代码，在独立临时数据目录复现集合题、真实画布工具、请求重放、服务失败提示和新请求重试，5 项通过；应用和只读 DMG 业务流程分别 17/17，无模型配置 9/9，可写中文目录启动及运行后验签通过。
- [Windows 构建与实际安装验收](https://github.com/coscatld/MathTutor/actions/runs/39044624636)覆盖中文路径全新安装、重启、023 + 024 迁移恢复、未知迁移拒绝，以及随附 Python/TypeScript 插件执行与幂等重放。[三平台源码 CI](https://github.com/coscatld/MathTutor/actions/runs/39044625096)对应同一修复提交，发布前核对其最终结果。
- Mac 仍无 Developer ID、未公证，Gatekeeper 默认拒绝；按 [Mac 安装说明](MACOS_INSTALLATION.md)核验并明确允许。Windows 仍无 Authenticode 发行证书签名。
- 无新增数据库迁移、无历史基准重评、无模型质量得分变更。r2 文件保留作历史追溯，下方早期记录对应各自当时的产物。

发布页提供 [Mac 分项验收](https://github.com/coscatld/MathTutor/releases/download/v0.7.0/macos-r3-verification.json)与 [Windows 分项验收](https://github.com/coscatld/MathTutor/releases/download/v0.7.0/windows-r3-verification.json)。官网的下载卡片与中英文安装文档均使用 r3，简化了文件摘要展示。

## 2026-10-17 Windows r2 安装包

Windows 请下载 [`MathTutor-0.7.0-win-x64-r2.exe`](https://github.com/coscatld/MathTutor/releases/download/v0.7.0/MathTutor-0.7.0-win-x64-r2.exe)，应用版本仍为 0.7.0。来自源码 `90d8a04` 的新构建，包含知识库“社区资源”快捷入口与导入说明的删除、左右空态卡片对齐，以及随包运行时缓存写入修复。

[Windows 构建与实际安装启动验收](https://github.com/coscatld/MathTutor/actions/runs/39033272713)通过，覆盖全新中文路径、重启、`023 + 024` 迁移恢复、未知迁移拒绝，以及包内 Python/TypeScript 插件真实执行和幂等重放；测试 GUI 只使用系统 PATH，不依赖用户另装 Python 或 Node。对应[三平台完整源码 CI](https://github.com/coscatld/MathTutor/actions/runs/39009508363)也已通过。

新 EXE 在下载后仅改名增加 r2 标记，字节保持 Windows runner 的原产物；没有发行证书签名。原 Windows 安装包标为 `PREVIOUS`，保留历史追溯，不再作为当前入口。Mac r2 继续使用已发布文件，没有重新打包或改变其校验值。

| 当前安装包 | SHA-256 |
|---|---|
| `MathTutor-0.7.0-win-x64-r2.exe` | `5f8246456f26069b81b2bc0265ee71a75ce9550d4b312420345a05d5a9e2a4ec` |
| `MathTutor-0.7.0-mac-arm64-r2.dmg` | `b12cc6983eb45f52ca9d7f0ccf167f4764b1fbec8ad11af0108362c9b408642f` |

发布页同时提供 [Windows r2 校验文件](https://github.com/coscatld/MathTutor/releases/download/v0.7.0/SHA256SUMS-0.7.0-win-r2.txt)和[脱敏验收记录](https://github.com/coscatld/MathTutor/releases/download/v0.7.0/windows-r2-verification.json)。本次只有应用构建和验收，没有新模型调用、基准重评或数据库迁移。Mac 构建来源为 `a8b8d45`，Windows 为 `90d8a04`；v0.7.0 原标签保持不变，后续文档提交不冒充安装包构建来源。

## 2026-10-17 Mac r2 修复

Mac 请改用 [`MathTutor-0.7.0-mac-arm64-r2.dmg`](https://github.com/coscatld/MathTutor/releases/download/v0.7.0/MathTutor-0.7.0-mac-arm64-r2.dmg)。原始 Mac 包的 DMG 校验正确，但应用资源签名不完整，已撤回使用；下方原始摘要仅保留作问题追溯。r2 应用版本仍为 0.7.0，包含本次知识库界面精简与卡片对齐。Windows 当前下载见上方 r2 安装包。

r2 为应用、Python 与原生模块完成本地 ad-hoc 签名，打包新增应用签名检查与最终只读 DMG 检查。它仍无 Developer ID、未公证，Gatekeeper 默认评估仍为拒绝，不能将业务启动通过当作默认下载放行。具体核验与首次打开见 [Mac 安装说明](MACOS_INSTALLATION.md)；最新摘要和分项结果随附 [`SHA256SUMS-0.7.0-mac-r2.txt`](https://github.com/coscatld/MathTutor/releases/download/v0.7.0/SHA256SUMS-0.7.0-mac-r2.txt) 与 `macos-r2-verification.json`。

Windows 源码 CI 上一轮有 3122 项通过、1 项失败：恢复备份并发测试等待总流程的 10 秒期限超时。此次修正测试暂停释放与总等待预算，保留原全部功能断言，并在超时时输出生命周期阶段。新的 [CI 运行](https://github.com/coscatld/MathTutor/actions)结果单独记录，不用上一轮或旧版本绿灯代替。

0.7.0 以非预发布的 GitHub Release 发行，提供 Windows x64 EXE 与 macOS Apple Silicon DMG。[正式发布页](https://github.com/coscatld/MathTutor/releases/tag/v0.7.0)包含安装包、校验文件和可直接导入的社区示例。两个安装包未使用发行证书签名，Mac 未公证；正式版标记不代表签名、公证或 Gatekeeper 门禁通过，原签名发布构建门仍保留。

## 对话资料与知识库

回答可以参考哪些资料统一在“对话资料”选择，先预览再应用；保存范围不会隐式切换到资料问答模式。知识库管理文件夹、题库与 Markdown 笔记，支持正文编辑、版本、标签和双向链接。共享题库 JSON 和资料库 ZIP 可导入为个人资料，再导出当前编辑内容；导入不自动加入当前会话的参考范围。

题目、作者参考答案和本地步骤核验能力分开标记。导入题库不会把参考答案变成已验证事实，不会为学生增加作答证据、掌握度或 DKT 观察。格式和示例见[共享题库](SHARED_QUESTION_PACKS.md)。

## 社区与普通用户插件

社区提供“发现资源”和“我的插件”两个独立导入入口。“发现资源”导入个人文件夹、Markdown、TXT 或题库，“我的插件”只接收插件文件；界面聚焦用户自己导入的内容。题库导入后为可编辑的个人副本，保留自己的修改。

开发者可按独立指南编写、调试与打包插件，用户直接导入文件即可使用。社区提供三类教学功能，设置通过表单调整，并在本地执行：

- **智能组卷**：读取实际课程题库，按年级、知识点和确定性随机种子选题，按配置附参考答案；参考答案不标为学生过程已自动核验。
- **错题复盘**：读取当前用户真实的有效作答记录，分清独立、受助、看答案后的作答与自我报告；没有记录时返回空结果。
- **学情可视化**：展示有分子、分母和时间依据的正确率与技能统计。重复、排除或不确定观察不冒充独立测评；趋势不是 DKT 预测概率，也不是基准成绩。

安装后默认停用；启用前需逐插件确认题库或学习记录权限。升级保留用户配置并重新停用，新增权限不会自动获得同意；停用或卸载会阻止后续调用。上述声明式包不执行外部代码；Python / TypeScript 代码插件使用独立协议和代码执行同意。开发者编写、调试和打包步骤见[插件开发指南](PLUGIN_DEVELOPMENT.md)，普通使用与分享流程见[社区使用与发布](COMMUNITY.md)。

## Python / TypeScript 与斜杠命令

“我的插件”可导入 `.py`、`.ts` 单文件及受限代码 ZIP。默认停用，使用者明确确认本地代码信任后才能启用。代码按本机账户权限在子进程运行，限制文件类型、输入输出、时间和重放，不提供操作系统沙盒，也不自动安装依赖。

输入 `/命令 参数` 后，宿主解析本轮原始请求并实际运行一次，再把有界结果提供给当前模型。原生和非原生模型使用同一回执流程；没有模型配置时显示实际插件结果。历史、检索资料与数学修复中的命令不会触发执行，也不会自动更新学习判定或 DKT。安装包使用内置 Python / Node，无需用户另装运行时。具体协议、可信边界与可运行示例见[代码插件开发说明](CODE_PLUGINS.md)。

## 开发者接口文档

知识库提供资料和教学技能界面；扩展接口与目录授权用法集中在独立开发者文档中。开发者可以在可信应用启动配置中注册版本化技能、工具 schema 和真实处理器。注册后的工具接入实际辅导循环，撤销后从后续可用工具中消失；宿主检查参数、JSON 输出、超时、结果大小和调用预算。声明式技能正文与工具权限分开，普通 Markdown 文件不会自动执行为技能。

SDK 处理器运行于可信应用进程，**不是代码沙盒**。SDK 处理器由可信启动代码注册；用户导入的受限代码插件走独立的导入、信任与显式命令执行流程。可离线运行的例子见[创作者接口](CREATOR_EXTENSIONS.md)。

文件工具只有在用户显式授权目录后才可使用，默认只读、可撤销，重启后需要重新选择。模型只获得目录名、授权 ID 和权限，不获得绝对根路径；只能访问授权内的有界 UTF-8 文本文件，拒绝绝对路径、向上越界、符号链接和设备文件。写入还需当前原始用户请求明确要求保存、创建或修改文件，资料内容和插件指导不能代替用户授权；覆盖现有文件需提供当前内容哈希。专用文件任务保留固定调用和总 token 预算，普通聊天与原数学核验预算不扩大。

## 数据与评测边界

社区页面运行这些确定性工作流不触发模型调用，也不把学习记录上传到资源源。用户在当前对话调用插件或文件工具时，其有界结果会提供给所配置的对话模型。导出的报告是否分享由用户决定。

三类声明式教学插件只读学习证据，不写入掌握度、DKT 观察或数学核验凭据。删除学习记录后，报告读取实时剩余记录；没有记录时不会编造统计。代码插件拥有前述本机账户权限，宿主不会将其输出自动采纳为学习证据。

本轮没有付费模型调用、模型权重更新或历史基准重评。已有 README 分数和折线图继续对应原评测条件，不能据此宣称 0.7.0 的数学或教学质量已经提升。自动化测试与模型传输桩验证工具调用、权限和数据流，不等同于在线模型质量评测。

数据库 migration head 保持 **024**，没有新增结构迁移；现有备份格式仍仅覆盖 SQLite。社区源与插件设置是独立本地配置，换机前需单独导出资源或重新订阅、导入。成功恢复数据库后所有插件停用并清除数据同意；目录授权也须重新授予，不会随数据库备份转移访问权限。

## 开源贡献与下一阶段

新增贡献指南、行为准则、安全政策、Issue/PR 模板和二次函数题库、声明式组卷、Python 顶点计算插件示例。文件直接位于仓库根目录及其 `docs/`、`examples/`、`tests/`、`.github/`，没有额外的 `overlay/` 层。开发者入口见[代码导航](OPEN_SOURCE_REPOSITORY_MAP.md)和[插件快速入门](PLUGIN_QUICKSTART.md)。

下一阶段建设 GitHub 开源资源索引、插件版本管理与社区贡献审核，详见[路线图](COMMUNITY_ROADMAP.md)。这些是后续建设目标；当前用户仍主动导入文件，代码插件仍需明确授权，审核不等于安全沙盒或教学效果认证。

## 原始安装包与验收（历史记录）

下面保留首次发布的文件摘要与来源，当前安装请使用上方 r2 入口。

- Windows x64：`MathTutor-0.7.0-win-x64.exe`。
- macOS Apple Silicon（M 系列）：`MathTutor-0.7.0-mac-arm64.dmg`；本轮不承诺 Intel Mac 包。
- 技术文件名和应用包名继续使用 `MathTutor`，正式中文名称用于 README、网页标题和桌面窗口标题。
- 打包使用随附 Python 与前端运行时，终端用户不需要另装 Python、Node.js 或开发环境；配置在线模型仍需相应服务账户和网络。

| 文件 | SHA-256 |
|---|---|
| `MathTutor-0.7.0-mac-arm64.dmg` | `cd5fec8a0fcf9835451aaad96446a694c2109ea9c28fb0a6025034a1a14cb0e6` |
| `MathTutor-0.7.0-win-x64.exe` | `d70aa7e315b2228fb1daf325d9d32366d6737f4920515ae153543a2af3a155fc` |

核心代码在[三平台 CI](https://github.com/coscatld/MathTutor/actions/runs/38925151778)通过。Windows 的[安装包构建与实际安装验收](https://github.com/coscatld/MathTutor/actions/runs/38923923503)覆盖全新中文路径、重复启动、迁移恢复与未知迁移拒绝，以及包内 Python/TypeScript 的真实执行和重放；Mac 完成应用与只读 DMG 启动、无模型配置、凭据清理和业务检查，并通过真实 WebSocket 验证插件斜杠命令。安装包包含随附运行时，用户无需另装 Python 或 Node。

原始 Mac 构建提交为 `bce1d77`，Windows 为 `d0bcf85`，其后的源码资格提交为 `8a66bf7`。此次开源文件与发布文档合并不修改包内应用代码；保留原构建来源与逐文件一致性证明，不将文档提交冒充重新构建。发布页随附精简验收记录和校验文件。
