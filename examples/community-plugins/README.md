# 可导入的声明式插件示例

- `exam-builder.plugin.json`：按知识点均衡组卷，相同出题顺序设置可再次生成同一份试卷。
- `mistake-review.plugin.json`：从真实作答判定生成错题复盘清单。
- `learning-report.plugin.json`：输出真实独立观察的趋势和技能计数。

普通用户可以在社区选择“导入文件”，安装后逐项同意所需权限并明确启用，再运行；也可以直接使用项目示例。

开发者复制模板后，应先更换自己的 ID 和作者信息，再编写默认参数与教学指导。裸清单是 UTF-8 JSON 数据，不包含可执行代码；升级需提高版本号。以下命令只面向源码开发者，不是普通用户安装步骤：

```bash
python -m pip install -e .
python examples/community-plugins/build_bundle.py your-plugin.json -o your-plugin-1.0.0.mathtutor
```

`build_bundle.py` 严格校验清单，计算规范化内容哈希，并生成能直接导入的分享包；不联网、不安装、不覆盖已有输出。`.mathtutor` 和 `.mtplugin` 都支持，内容不是压缩包。不要以 `mathtutor.*` 的项目示例标识发布自己的修改版。

完整开发、调试和发布流程见 [插件开发者指南](../../docs/PLUGIN_DEVELOPMENT.md)；权限边界见 [社区插件说明](../../docs/COMMUNITY_PLUGINS.md)。
