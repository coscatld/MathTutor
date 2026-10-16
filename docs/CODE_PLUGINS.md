# Python / TypeScript 插件与斜杠命令

适用于 **MathTutor——基于学习过程追踪与可验证解题的开源数学智能辅导系统 0.7.0**。

社区“我的插件”支持导入开发者的 Python、TypeScript 单文件和受限 ZIP 代码包。插件导入后默认停用；使用者确认信任并启用后，可以在对话框输入 `/命令 参数`。宿主识别当前请求、实际运行插件一次，再把有界结果交给当前配置的模型组织回答。没有模型配置时，展示真实执行结果，不伪造模型回答。

## 1. 普通用户怎样使用

1. 从自己信任的开发者取得 `.py`、`.ts` 或插件 `.zip` 文件。
2. 打开社区“我的插件”，点击“导入插件”。资料文件夹、Markdown 和 TXT 应在“发现资源”导入。
3. 阅读本地代码权限，勾选信任并启用。卡片会显示可用的 `/命令`。
4. 在对话框输入 `/`，选择已启用且运行时可用的插件命令，补充参数后发送；也可以直接输入完整命令。
5. 查看插件实际结果或由当前模型整理的回答。可以停用、卸载或下载插件包。

代码在**当前本机账户权限**下运行，可以访问该账户允许访问的文件和网络。子进程、运行时限、文件类型检查和清理环境变量**不是操作系统沙盒**。启用代码插件表示使用者信任这份代码；普通声明式教学插件的数据同意不能代替代码执行同意。

安装包内置 Python 与 Electron 的 Node 运行时，无需用户另装 Python、Node.js 或 TypeScript。源码开发模式运行 TS 时，开发者需要设置可信 Node 可执行文件，例如：

```bash
export MATHTUTOR_PLUGIN_NODE_EXECUTABLE=/absolute/path/to/node
```

该值由宿主配置，不能由聊天内容或上传清单指定。使用支持原生类型擦除的 Node 版本；桌面包使用自己的内置版本。

## 2. 最小 Python 插件

保存为 `double.py`，即可直接导入：

```python
def run(request: dict) -> dict:
    value = int(request["text"].strip())
    return {"text": f"结果是 {value * 2}", "data": {"result": value * 2}}
```

启用后输入 `/double 21`。单文件命令从合法文件名生成，命令需为 2–32 个小写字母、数字、下划线或短横线，以字母开头。文件名不适合作为命令时，会生成稳定标识，以应用显示的命令为准。生产插件应自行处理参数缺失和无效输入，完整示例见 [double.py](../examples/code-plugins/double.py)。

输入是 `{"text": "命令后面的文字", "config": {...}}`。宿主只主动传入本次参数与该插件配置，不传入模型密钥、数据库句柄或全量学生资料。`run` 也可以是 `async def`，由宿主等待结果。

返回值必须是有限 JSON 对象，不能包含 NaN、Infinity、字节、任意类实例或无限嵌套。常用返回格式：

```json
{"text": "供用户阅读的结果", "data": {"result": 42}}
```

标准输出用于宿主结果协议，插件应通过返回值提供结果，不要用 `print` 输出调试日志。必要日志可写标准错误，但日志同样受大小限制。运行错误显示失败回执，不能用一段成功文案掩盖失败。

## 3. 最小 TypeScript 插件

保存为 `double-ts.ts`：

```typescript
type Request = { text: string; config: Record<string, unknown> };

export async function run(request: Request): Promise<Record<string, unknown>> {
  const value = Number(request.text);
  if (!Number.isFinite(value)) return { text: "请输入数字。" };
  return { text: `结果是 ${value * 2}`, data: { result: value * 2 } };
}
```

启用后输入 `/double-ts 21`。完整输入检查见 [double-ts.ts](../examples/code-plugins/double-ts.ts)。入口必须导出 `run`，同步函数与返回 Promise 均可。

TS 使用 Node 原生类型擦除：支持类型注解、`type`、`interface` 等可擦除语法，不执行类型检查。需要代码生成的 enum、装饰器、`tsconfig` 路径别名等不属于该运行方式；不自动运行 `npm install`、`pip install` 或构建脚本。可使用语言标准库与包内相对代码模块，插件包不携带 `node_modules`、本机二进制或安装脚本。

## 4. 多文件包和版本更新

推荐目录：

```text
my-plugin/
  plugin.json
  double.py
  helpers.py         # 可选，自行实现并明确纳入包
  README.md          # 可选
```

可复制 [示例 plugin.json](../examples/code-plugins/plugin.json)。它指定自己的 `id`、三段版本、名称、作者、许可、说明、`runtime`、`command`、`entrypoint` 和 `required_permissions: ["execute_local_code"]`。`runtime` 为 `python` 或 `typescript`，入口后缀须与之匹配。命令不含开头的 `/`，同一用户已安装插件的命令不能冲突。

在已安装开发依赖的仓库根目录运行：

```bash
python examples/code-plugins/build_bundle.py /path/to/my-plugin \
  --include helpers.py --include README.md \
  --output /path/to/my-plugin-1.0.0.zip
```

入口文件自动加入，其他文件必须通过 `--include` 明确选择。工具不遍历打包整个项目，不执行插件、不安装依赖，也不覆盖已有输出。它严格校验清单，对选中的 UTF-8 内容计算 `file_hashes`，生成包含根目录 `plugin.json` 的 ZIP；不要手工修改源码却保留旧校验值。

包内最多 32 份源码或资源，每份最多 64 KiB，正文合计最多 256 KiB，上传包最多 512 KiB。支持相应语言的 `.py` 或 `.ts`，以及 `.md`、`.txt`、`.json` 资源；不接受绝对路径、父目录、隐藏配置、符号链接、重复路径、`node_modules` 或可执行安装文件。宿主自己的运行配置文件名保留，不能由包覆盖。

更新时保持插件 ID，明确提升版本，例如 `1.0.0` → `1.0.1`。相同版本不能替换源码；单文件固定为首次导入版本，修改后应改为带明确版本的 ZIP 升级，或由使用者明确卸载旧包后重新导入。升级保留个人配置，停用并清除原代码执行同意，重新信任后才能运行。

## 5. 对话调用与结果边界

命令只从本轮原始消息开头识别。历史对话、资料、网页、插件说明和模型修复文字里的 `/命令` 不会触发代码。前端选择候选仅插入文字，发送后才由服务端执行；前端不会另调用运行接口，避免执行两次。

显式命令执行后，模型获得的是参考结果，不能把它说成应用已经数学核验的答案、学生作答证据或 DKT 更新。宿主不会自动将返回值提交为练习判定、改变解答披露权限或更新学生掌握状态。插件作者也不得绕过宿主直接修改应用数据库。

普通模型工具列表不自动开放代码执行。旧声明式教学工作流仍可通过其受控工具调用；代码插件需要用户的明确斜杠命令或插件页运行操作。

使用云模型时，插件返回结果的有界片段会进入当前模型请求。运行时不会自动把代码或输出发给插件作者；作者代码本身拥有本机账户的网络权限，因此需要在启用前审查、信任作者。

## 6. 超时、重放和中断

每次运行最多 5 秒，标准输出最多 16 KiB，标准错误最多 8 KiB；输入文字最多 8000 字符，配置最多 8 KiB。结果还有结构深度与节点限制。进程环境使用白名单，清除宿主模型密钥及开发路径变量；以参数列表启动进程，不经过 shell。

Windows 使用嵌入式 Python，随包的 `._pth` 明确列出运行路径并启用随包 `site`；验收中观察到 `isolated=1`、`no_site=0`，不要求与 macOS 的 `no_site=1` 相同。验收检查实际可执行文件属于安装包、系统路径中没有外部运行时、中文执行和重复请求结果；这些标志不代表操作系统沙盒。路径机制见 [Python Windows 文档](https://docs.python.org/3.12/using/windows.html#finding-modules)。

同一用户、同一请求标识的重放会检查插件版本、源码、配置与输入。宿主先保存“已开始”记录，完成后保存有界结果；数学修复和网络重试复用已有回执，不重新执行插件。上次状态不明时拒绝自动重跑，避免重复写文件或重复网络操作。

回执按用户保存在独立本地文件中，最多 1000 次、24 MiB，包含结果与输入指纹，不保存原始参数正文；插件若在结果中回显参数，该内容也会保留。卸载插件保留旧回执，避免重新安装后误重放旧请求；清除该用户插件数据时一并删除。SQLite 备份不包含这些插件文件。

插件自身对外部系统产生的副作用和宿主结果记录不属于同一个事务，不能承诺跨进程崩溃的恰好一次执行。开发者应为有副作用的操作设计自身幂等机制。停用、卸载、恢复数据库或撤销同意后，不再接受后续执行；已有结果是历史记录，不代表当前仍启用。

## 7. 开发接口与验证

管理接口沿用当前用户认证；变更和运行检查本地 Origin。常用接口：

```text
POST /api/v2/math-tutor/desktop/community/plugins/import   # multipart file
GET  /api/v2/math-tutor/desktop/community/plugins
GET  /api/v2/math-tutor/desktop/community/plugins/commands
PUT  /api/v2/math-tutor/desktop/community/plugins/{id}/enabled
POST /api/v2/math-tutor/desktop/community/plugins/{id}/run
GET  /api/v2/math-tutor/desktop/community/plugins/{id}/export
```

启用代码插件必须包含 `consent_permissions: ["execute_local_code"]`。运行体包含 `text`，可选 `config` 与 `operation_id`。代码结果会明确标注 `read_only: false`、`sandboxed: false`、`execution_mode: "trusted_local_code"`；`authority` 仍是 `reference_only`。

先在隔离账户和临时目录测试合法输入、参数错误、超时、非有限输出、停用、升级、重放和未知命令，再分享给使用者。仓库的 Python/TS 实例、真实进程测试及 WebSocket 模型传输桩用于验证执行链；模型传输桩不是线上教学质量分数。

## 8. 设计参考和兼容范围

结构参考 [Claude Code 插件](https://code.claude.com/docs/en/plugins)和 [Codex 插件包](https://developers.openai.com/plugins/build/plugins)中的包清单、可启停组件与命令入口。MathTutor 使用上文自己的版本化插件协议；不能把其完整市场包、MCP 配置或生命周期 hooks 当作本格式直接执行。

TypeScript 运行方式依据 [Node.js 原生 TypeScript 文档](https://nodejs.org/api/typescript.html)。需要新增宿主工具或更深的应用集成时，继续阅读[可信扩展 SDK](CREATOR_EXTENSIONS.md)；三类无代码教学插件见[声明式插件指南](PLUGIN_DEVELOPMENT.md)。
