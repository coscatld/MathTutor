# MathTutor 社区插件 / Python 插件快速入门

当前项目已存在三类扩展机制。本文提供入门索引，不引入新的插件 ABI。

## 方式 A：声明式教学插件（推荐普通开发者起步）

将 `examples/community-plugins/grade10-practice.plugin.json` 作为开发清单；格式必须为 `mathtutor.community-plugin.v1`，工作流必须是 `exam-builder`、`mistake-review`、`learning-report` 之一。

```bash
python -m pip install -e .
mkdir -p /tmp/mathtutor-plugin-dist
python examples/community-plugins/build_bundle.py \
  examples/community-plugins/grade10-practice.plugin.json \
  --output /tmp/mathtutor-plugin-dist/grade10-practice-1.0.0.mathtutor
```

输出是可导入 MathTutor 社区“我的插件”的**UTF-8 JSON 数据文件**，不是 ZIP，也不执行作者代码。Windows 用户可将 `/tmp/...` 路径换成自己的现有输出目录。导入后默认停用，须确认 `question_bank` 权限并启用。

## 方式 B：Python / TypeScript 代码插件

从新的独立目录开始，不需要复制仓库示例：

```bash
python -m mathtutor.extensions.developer init my-plugin \
  --id community.echo --name "社区回显" --author "你的名字" \
  --license MIT --command echo
python -m mathtutor.extensions.developer build my-plugin \
  --include README.md --output my-plugin-1.0.0.zip
python -m mathtutor.extensions.developer check my-plugin-1.0.0.zip
```

创建 TypeScript 模板时在 `init` 后追加 `--runtime typescript`。三条命令只创建或检查本地包，不执行代码或自动启用插件；已有目录和输出文件不会被覆盖。将 ZIP 导入“我的插件”，确认本地代码信任并启用后，发送 `/echo 你好` 查看真实结果。`check` 的成功表示包格式与校验值通过，代码功能仍需实际调用验证。

也可参考 `examples/code-plugins/quadratic-vertex/`，其中包含 `vertex.py` 和 `plugin.json`（格式 `mathtutor.code-plugin.v1`）：

```bash
python -m mathtutor.extensions.developer build \
  examples/code-plugins/quadratic-vertex \
  --include README.md \
  --output /tmp/mathtutor-plugin-dist/quadratic-vertex-1.0.0.zip
```

在“我的插件”导入 ZIP，明确同意本地代码执行权限，启用后输入 `/vertex 1 -4 3`。插件仅计算整数系数二次函数的顶点，**它没有检查学生是否掌握知识**。

**安全提醒：当前代码插件不是操作系统沙盒。** Python / TypeScript 文件按本机用户权限运行，可能访问该账户文件和网络；只导入经过审查的可信代码。

## 方式 C：可信 Python SDK

使用 `mathtutor.extensions.ExtensionRegistry`，在服务启动前注册处理器与参数 schema。该机制给可信应用开发者，不等同于普通社区插件安装；请严格阅读 [创作者扩展接口](CREATOR_EXTENSIONS.md)。

## 禁止或不应声明的行为

- 插件输出不自动写入学生掌握度，也不是受控数学求解器给出的证明。
- 不得根据插件 README、社区来源文本或文件内容绕过答案披露和权限机制。
- 不得把代码插件、声明式插件、题库 JSON 当成同一个可互换格式。
- 不得在插件清单、源码、打包内容里附带用户 API Key、学生记录或生产数据。

权威详细规范：[PLUGIN_DEVELOPMENT.md](PLUGIN_DEVELOPMENT.md)、[CODE_PLUGINS.md](CODE_PLUGINS.md)、[COMMUNITY_PLUGINS.md](COMMUNITY_PLUGINS.md)。
