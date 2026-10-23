# 社区插件接入与验证记录

- 时间：2026-10-24，北京时间 00:27–00:42。
- 范围：社区 Python / TypeScript 插件的开发、打包、导入与显式运行链路。
- 本记录不包含官网和产品页面改动，也不代表安装包已经重新发布。

## 发现的问题与实际实现

MathTutor 已有真实代码插件运行时、受限 ZIP 格式及独立的本地代码信任机制，但开发入口依赖仓库中的 `examples/code-plugins/build_bundle.py`。开发者需要自行拼装清单、寻找示例路径，缺少随 Python 包提供的创建和离线验包入口。

新增 `python -m mathtutor.extensions.developer`，提供以下三个命令：

| 命令 | 实际行为 |
| --- | --- |
| `init` | 校验作者填写的 ID、命令、许可和元数据，在新目录创建 `plugin.json`、Python 或 TypeScript 入口及 README。已有目录不覆盖。 |
| `build` | 自动纳入入口，其他源码或资源须逐个 `--include`；使用原有路径、体积、编码和包校验，重新计算源码哈希，输出新的 ZIP。已有输出不覆盖。 |
| `check` | 使用应用导入时的同一校验器检查 ZIP 或单文件，返回插件身份、版本、命令、权限及文件清单，不返回源码，不安装或执行代码。 |

旧脚本保留原命令行参数，内部转调新的公共实现。生成的模板回显本次输入并统计 Unicode 字符数；用户仍须在社区导入、明确同意本地代码执行并启用，再发送斜杠命令。包检查通过只说明格式与相关校验值有效，不证明作者代码安全或功能正确。

## 修改文件

| 文件 | 改动 |
| --- | --- |
| `src/mathtutor/extensions/developer.py` | 新增离线开发 CLI、Python/TS 模板和统一打包函数。 |
| `examples/code-plugins/build_bundle.py` | 改为兼容包装，避免两套打包逻辑。 |
| `tests/test_plugin_developer_cli.py` | 增加真实包、权限拒绝、解释器执行及文件边界回归。 |
| `docs/CODE_PLUGINS.md` | 补充完整创建、打包、检查与导入步骤及检查范围。 |
| `docs/PLUGIN_QUICKSTART.md` | 增加无需寻找示例脚本的标准开发入口。 |

## Harness 参考证据

在线读取了 [DeepSeek Harness 官方仓库](https://github.com/deepseek-ai/deepseek-harness)及其[最小插件教程](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/cordis-tutorial/01-first-plugin.md)。本地参考仓库为同级 `deepseek-harness`，读取时 `git rev-parse HEAD` 返回 `b150a551b8d465e31e418e1b2eaf5e79bbb7d28e`，`git status --short` 为空。本轮没有修改该参考仓库。

实际读取的规范和实现如下；源码链接固定到上述本地 revision，便于复核：

| 文件 / 方法 | 观察与本轮采用方式 |
| --- | --- |
| `AGENTS.md`、`packages/AGENTS.md`、`docs/AGENTS.md` | 阅读包导出约定、可运行示例与真实组合测试要求，作为参考项目的约束。 |
| `docs/cordis-tutorial/01-first-plugin.md` | 插件以单独入口声明能力，通过配置组合；开发者有最小运行示例和明确失败提示。采用“入口清晰、示例可运行”的开发体验。 |
| [agent-spine-demo/src/index.ts — `apply(ctx, config)`](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/packages/examples/agent-spine-demo/src/index.ts#L212) | 示例用 `ctx.plugin` 装配能力并明确转发配置。MathTutor 本轮只补充独立插件开发入口，没有更换应用装配系统。 |
| [cordis-host-runner/src/index.ts — `define`](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/packages/extensions/cordis-host-runner/src/index.ts#L151) | 校验元数据和代码，保存插件与包身份；定义和运行分离。MathTutor 的构建、验包同样不执行作者代码。 |
| [cordis-host-runner/src/index.ts — `run`](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/packages/extensions/cordis-host-runner/src/index.ts#L248) | 运行处理取消、正在切换的状态及适用的客户端授权。未移植其动态代码激活和跨版本授权语义。 |
| [inspect-registry.ts — `register`](https://github.com/deepseek-ai/deepseek-harness/blob/b150a551b8d465e31e418e1b2eaf5e79bbb7d28e/packages/extensions/cordis-host-runner/src/inspect-registry.ts#L62) | 校验声明、拒绝重复 ID，并返回与注册身份绑定的撤销函数。用于理解注册生命周期；未新增 MathTutor 热重载功能。 |
| `docs/cookbook/extension-cookbook.md`、`docs/subsystems/extensions.md`、`packages/extensions/README.md` | 核对工具、生命周期与宿主/客户端扩展职责。未宣称 MathTutor 兼容 Cordis ABI。 |
| `LICENSE` | 本地所读版本标注 MIT、Copyright (c) 2026 DeepSeek。此处记录实际许可文本，不替代后续引入第三方源码时的许可审查。 |

本轮借鉴开发流程，未复制或打包 Harness 代码，未增加 Cordis、npm/pip 依赖、外部服务或模型。MathTutor 继续使用 `mathtutor.code-plugin.v1` 和现有 Python/TS 子进程机制；声明式教学插件与可信启动期 Python SDK 仍各有独立入口。

## 真实测试结果

运行目录：MathTutor 仓库根目录。运行环境：当前 macOS，本地 Python 3.11.15；TypeScript 使用测试夹具探测到的原生类型擦除运行时。

```bash
PYTHONPATH=src <USER_HOME>/miniconda3/envs/deeptutor/bin/python -m pytest \
  tests/test_plugin_developer_cli.py \
  tests/test_code_plugin_bundle_cli.py \
  tests/test_code_plugins.py \
  tests/test_plugin_commands.py \
  tests/test_community_plugins.py \
  tests/test_community_plugins_api.py \
  tests/test_creator_extensions.py -q --tb=short
```

实际结果：**132 passed, 265 warnings in 10.19s**。没有跳过项。警告来自现有 FastAPI `on_event` 及 Starlette TestClient 弃用提示，未为使测试通过而新增依赖或关闭警告。`git diff --check` 通过。

验证覆盖：

- Python 和 TypeScript 模板均创建真实 ZIP，经过应用解析及真实 `CommunityPluginService` 导入；默认停用，缺失同意时拒绝启用和运行，明确授权后由本机解释器执行并返回中文及 emoji 结果。
- 未选中的私有文件不会进入 ZIP；父目录路径、符号链接、被修改的 ZIP 哈希会被拒绝；已有项目和输出不会覆盖。
- 带顶层文件写入代码的作者模块在 `build`、`check` 时未执行，测试标记文件始终不存在。
- CLI 在仓库外工作目录通过 `python -m` 启动，无需 `examples/` 路径；旧示例脚本的既有测试继续通过。
- 相关社区 API、斜杠命令、结果重放、可信 SDK、权限与用户隔离回归通过。

首次新增测试曾错误假定未启用插件不会出现在 `commands()` 清单中，得到 1 failed / 15 passed。复核真实接口后，改为检查清单内 `enabled=False` 并实际验证执行拒绝；未放宽既有权限测试或修改运行时来迎合测试。随后加入 TypeScript 模板的真实执行验证，最终获得上述 132 项通过结果。

## 执行、许可与验证边界

`init` 要求作者显式填写 `--license`，不替作者决定已有源码的授权。示例命令中的 MIT 仅为新插件作者可选择的示例值。新 CLI 不安装第三方依赖、不联网、不执行安装脚本，不读取学生数据或模型凭据。

实际插件仍按本机账户权限运行，子进程预算不是操作系统沙盒；开启插件继续要求独立的 `execute_local_code` 同意。升级后重新信任、owner 隔离、文件限制、重放保护及 `reference_only` 结果属性保持原有机制。构建和静态检查不能替代源码审查或真实运行测试。

本轮没有验证 Windows/Linux，没有生成或安装新的桌面发行包，也没有运行模型效果评测。上面的通过结果证明当前主机上的接入与权限行为，不代表跨平台发布验收或教学效果提升。

## 00:44 后追加：Harness 工具接口兼容子集

按用户后续要求，实现 `adapt-harness` 源码适配命令。新增 `src/mathtutor/extensions/harness_compat.py`、`tests/test_harness_plugin_compat.py` 和 `examples/code-plugins/harness-double/`，并扩展开发 CLI 与开发文档。未修改既有包 schema 或运行器，避免旧包默认字段变化导致哈希或信任记录失效。

追加阅读同一固定 revision 的 `packages/core/tools/README.md` 和 `packages/core/tools/tests/scoped.spec.ts` 中的原始 `ToolDefinition` 注册及 `execute(args, exec)` 调用。实现只覆盖 `apply(ctx, config)`、`ctx.tools.register`、有限原始 JSON Schema 和文本输出；不支持的服务、schema 关键字和输出能力拒绝，不引入 Cordis 或 npm 依赖。支持范围与可复制命令见 `docs/CODE_PLUGINS.md` 的兼容子集章节。

适配将原入口和新包装入口纳入普通 TypeScript 代码插件 ZIP；正常导入、独立本地代码信任、owner 隔离、执行预算、重放和参考结果约束继续生效。构建、检查不执行原始 `apply`。这不是完整 Harness/Cordis 插件生态兼容。

首次追加回归命令：

```bash
PYTHONPATH=src <USER_HOME>/miniconda3/envs/deeptutor/bin/python -m pytest \
  tests/test_harness_plugin_compat.py tests/test_plugin_developer_cli.py \
  tests/test_code_plugin_bundle_cli.py -q --tb=short
```

第一轮结果为 **27 passed, 1 warning in 2.12s**。独立审查随后发现合法入口名 `__TOOL__.ts` 会触发适配模板的二次占位符替换，已修正替换次序并加入实际 TypeScript 执行回归，得到 **28 passed, 1 warning in 2.24s**。另一次审查发现注册后动态添加未知 schema 关键字可能被忽略，已在参数执行前及结果返回后重新验证 schema，并加入两项实际进程拒绝回归。修复后同一命令结果为 **30 passed, 1 warning in 2.29s**，无跳过项，随后 `git diff --check` 通过。原有 132 项通过记录对应新增兼容层之前，不能替代其最终验证。

## 根代理最终联合回归

兼容层与两项审查修复稳定后，根代理运行以下八个文件：`test_harness_plugin_compat.py`、`test_plugin_developer_cli.py`、`test_code_plugin_bundle_cli.py`、`test_code_plugins.py`、`test_plugin_commands.py`、`test_community_plugins.py`、`test_community_plugins_api.py`、`test_creator_extensions.py`。命令前缀为 `PYTHONPATH=src <USER_HOME>/miniconda3/envs/deeptutor/bin/python -m pytest`，选项 `-q --tb=short`。

**145 passed，265 warnings，10.58 秒**，没有跳过项。完整日志：[plugins-final-tests.log](plugins-final-tests.log)。此组覆盖前文的132项，因此不相加计数。另一位子代理对兼容、CLI、code_plugins独立复跑57项通过。
