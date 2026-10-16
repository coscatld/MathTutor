# 创作者扩展接口 v1

MathTutor 开放一个可运行的 Python 注册接口：创作者编写工具处理器，由应用开发者在启动时注册，模型通过真实工具循环调用它。内置目录工具可浏览、读取和写入用户显式授权文件夹中的文本。

普通用户可使用 [社区 JSON 教学插件](COMMUNITY_PLUGINS.md)，安装已有受控工作流的声明式组合。下面的 Python SDK 面向可信应用开发者：处理器在应用进程内运行，**不是代码沙盒**；用户导入 Python / TypeScript 文件或受限 ZIP 的机制见[代码插件](CODE_PLUGINS.md)；它需要独立的本地代码信任，不通过下面的注册接口偷偷加载。处理器作者对自己的代码权限和副作用负责。

## 工具、教学 Skill 与知识文件

| 类型 | 提供什么 | 激活方式 |
| --- | --- | --- |
| 工具 | 有参数 Schema、真实处理器和结构化结果的能力 | 开发者通过 server-owned registry 注册；文件工具另外要求用户目录授权 |
| 教学 Skill | 有界的表达和教学指导 | 开发者注册，默认停用；启动配置显式启用 |
| 普通知识文件 | 可检索的题目、资料、笔记 | 用户在“对话资料”选择参考范围 |

把 `SKILL.md`、代码或所谓安装说明导入知识库只会得到普通参考文本，不会执行代码、注册工具或改变权限。教学 Skill 不能扩大答案披露范围、覆盖学生当前请求或写入学生掌握事实。应用的数学核验和作图仍走原有受控流程。

## 声明和注册一个真实处理器

```python
from pydantic import Field
from mathtutor.extensions import (
    ExecutionContext, ExtensionManifest, ExtensionRegistry, StrictArguments,
)

class DoubleInput(StrictArguments):
    value: int = Field(ge=-1000, le=1000)

async def double(args: DoubleInput, ctx: ExecutionContext):
    # ctx 只有服务端认证得到的 owner_id 和 conversation_id。
    return {"value": args.value * 2}

registry = ExtensionRegistry()
registry.register_tool(
    ExtensionManifest(
        id="example.double", version="1.0.0", name="乘二",
        description="将一个整数乘以二，返回计算结果。", kind="tool",
    ),
    name="ext_double", input_model=DoubleInput, handler=double,
    timeout_seconds=2, max_result_bytes=4096,
)
```

`api_version` 默认是 `mathtutor.extensions.v1`，未知版本及未知 manifest 字段会被拒绝。工具名必须以 `ext_` 开头；重复工具名、重复扩展 ID 以及保留的应用工具名均不能注册。参数模型必须关闭额外字段，执行时严格校验，字符串 `"2"` 不会被悄悄转换为整数。

开发者可在创建应用时注入注册表：

```python
from mathtutor.api.product_app import create_math_tutor_app

app = create_math_tutor_app(extension_registry=registry)
```

注入会替换默认扩展组合。如果需要保留应用内置目录工具和长度换算，应先按正常方式创建应用，再在开始接收请求前注册到其现有 registry：

```python
from mathtutor.api.product_app import create_math_tutor_app
from mathtutor.api.product_state import get_product_state

app = create_math_tutor_app()
registry = get_product_state().extension_registry
# registry.register_tool(...)
```

这是宿主应用启动代码，不是客户端请求参数。没有根据用户提供的模块名、文件路径或命令执行 import 的机制。此版本扩展进入普通辅导对话的原生 Function Calling 循环；模型供应商不支持原生工具时不会调用这些工具。知识库的严格来源问答循环继续使用其现有工具集合。

## 回执、预算和卸载

处理器必须是可取消的 `async` 函数。默认超时 2 秒，上限 10 秒；这是协作式超时，不会强制终止阻塞的任意 Python 代码。返回值只能是有限 JSON 数据，禁止 NaN、字节、元组和任意对象；默认结果预算 4 KiB，上限 16 KiB，另有 JSON 深度和节点上限。单轮最多 4 次扩展调用，不追加无限重试。

普通对话保留原来的 2 步预算，注册工具本身不会增加步骤。只有当前 owner 已有目录授权，且当前用户请求明确包含文件操作时，宿主给文件任务至多 4 步，以支持“列目录 → 读文件 → 写笔记 → 最终答复”；一轮最多 3 次文件工具。判定使用当前请求，排除明确否定的操作语句，不从历史文件正文里激活。数学核验与画图仍保留原来的数学循环预算；组合任务也不增加原有数学步骤。所有路径共用原有总 token 和费用预算，步骤上限不能由客户端或模型提交。

```json
{"ok":true,"tool":"ext_double","call_id":"opaque-id","authority":"reference_only","result":{"value":4}}
```

参数错误、异常、超时、过大结果和撤销分别返回明确错误回执。普通异常正文不向模型传递，避免夹带路径或凭据；作者主动抛出的 `ExtensionError` 是公开提示，只能使用不含路径、凭据和原文的固定文案。`authority: reference_only` 表示工具结果不会成为数学已验证证明或学生掌握证据。工具回执不会写学习事件、提高 DKT 成绩或绕过练习发布门。

`registry.unregister("example.double")` 撤销扩展。下一次提示组装会移除工具；已经绑定的旧调用也检查注册身份，不会继续接受已卸载处理器的结果。新注册工具不会在已经进行中的一轮对话里突然获得权限。

## 真实工作区文件能力

目录接口供开发者在可信集成中使用，常规知识库聚焦资料与教学技能。开发者须在自己的集成中提供目录选择、明确的只读或可写确认及撤销操作，再通过下方本地管理 API 建立授权。模型没有授予目录的工具，客户端不能通过聊天信封指定身份或工具权限。

授权按认证 owner 隔离，仅在当前服务进程内有效；重启、恢复数据库后必须重新选择，授权不进入数据库或备份。API 和模型的目录回执仅提供目录名称和不透明 ID，不把绝对根路径带入模型上下文。可用文件工具的描述动态附上当前 owner 的目录 ID、名称、可写状态，模型可以实际发现目录，无需用户手抄 UUID。文件正文仅在实际调用读取工具时进入本轮模型输入，因此使用云模型时会发送选中的文本片段。

| 工具 | 参数与行为 |
| --- | --- |
| `ext_workspace_list` | `workspace_id`、目录相对路径；最多 80 条，跳过隐藏文件和链接 |
| `ext_workspace_read_text` | `workspace_id`、文件相对路径、`start` 和 `limit`；返回 UTF-8 文本片段、续读位置、整个文件的 SHA-256 |
| `ext_workspace_write_text` | `workspace_id`、文件相对路径、`content`；默认只新建。修改已有文件必须附上读取所得 `expected_hash` |

支持 `.md`、`.txt`、`.json`、`.csv`、`.tsv`，单文件上限 64 KiB。读取每片最多 2000 字符，工具结果还受字节预算约束。只能操作已存在的子文件夹，不自动创建目录、不删除文件、不读取二进制文件、不访问整个磁盘。

路径拒绝绝对路径、盘符、父目录、隐藏路径和替代数据流。符号链接、Windows 重解析点和被替换的授权根会被拒绝。POSIX 使用不跟随链接的目录描述符固定访问目录；Windows 适配器逐级检查重解析点并重新检查目录边界。授权目录应由当前用户控制，不能把它当成针对同时恶意修改文件系统的其他进程的沙盒。

新建采用原子的“目标必须不存在”操作，避免先检查存在再覆盖的竞态。修改先比较当前内容哈希，再原子替换；外部修改导致哈希不匹配会明确拒绝，要求重新读取。多个应用外进程同时修改同一个文件时，仍应避免竞争写入；本接口不提供跨进程文件事务。

用户开启可写目录后，还必须在原始当前请求中明确要求文件保存、新建或修改，宿主才会向模型展示并执行写入工具；缺少该意图时，直接调用同样被拒绝。纯聊天“写一份讲解”、否定写入及“解释如何保存文件”不会授权落盘。修复反馈、历史消息、文件正文或社区插件教学指导不能提升权限；数学修复重新绑定时仍使用原始 `response_request`。应用不会开放模型授予新目录、运行终端或修改教学数据库的工具。

## 本地管理 API

以下是开发者接口，均要求现有 owner 认证。目录选择只是打开 OS 对话框，不自动授权；集成方仍须取得用户明确的只读或可写选择。

```text
GET    /api/v2/math-tutor/desktop/creator/catalog
GET    /api/v2/math-tutor/desktop/creator/workspaces
POST   /api/v2/math-tutor/desktop/creator/workspaces/pick
POST   /api/v2/math-tutor/desktop/creator/workspaces
DELETE /api/v2/math-tutor/desktop/creator/workspaces/{workspace_id}
```

授权请求示例：`{"path":"/user/selected/folder","writable":false}`。路径只在本地管理链路中传递。目录选择通过现有 Electron loopback picker 的固定 `/native-directory` 路由完成；没有 Electron 时，可信集成可自行提供目录输入与确认流程。这些目录接口不接受任意模块路径、shell 命令或代码；社区代码插件使用独立的导入、信任和显式调用流程。

## 离线示例与验证

```bash
python -m pip install -e .
python examples/extensions/workspace_demo.py
python -m pytest tests/test_creator_extensions.py tests/test_creator_workspaces.py -q
```

示例真实创建、读取、凭哈希更新并撤销一个临时目录的授权；不调用模型。集成测试使用固定模型传输桩走实际普通聊天工具循环，验证处理器执行、服务端 owner/cid、注册和卸载影响模型可见 Schema、Skill 显式开关、文件读写和权限拒绝；它们验证工程行为，不代表回答质量评测分数。

架构参考：[DeepSeek Harness 官方工具接口](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/core/tools/README.md)。MathTutor 保留自己的教学、资料和权限边界，没有引入其完整运行时或声称二进制兼容。
