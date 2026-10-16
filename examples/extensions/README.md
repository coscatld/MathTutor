# 创作者接口示例

运行真实目录读写示例，不调用模型、不需要 API Key：

```bash
python -m pip install -e .
python examples/extensions/workspace_demo.py
```

示例显式创建临时工作目录，依次新建 Markdown、读取、凭内容哈希更新、撤销授权，再验证读取被拒绝。退出时删除临时目录。

完整接口和应用启动注册方式见 [创作者开发说明](../../docs/CREATOR_EXTENSIONS.md)。
