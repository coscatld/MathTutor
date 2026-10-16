# MathTutor 开源代码导航

> 以现有 `coscatld/MathTutor` 仓库为基础，不要求迁移目录。具体文件路径以当前 `main` 为准。

```text
MathTutor/
├── README.md                  # 现有项目说明（保留）
├── LICENSE                    # 现有 Apache-2.0 许可证（保留）
├── pyproject.toml             # Python 3.11–3.13 后端依赖和打包
├── src/mathtutor/             # FastAPI 产品服务 / 数学 / 学习 / 扩展
├── web/                       # Next.js + React 前端（web/package.json）
├── desktop/                   # Electron 桌面壳与打包
├── benchmarks/                # 现有基准测试
├── tests/                     # Python 测试套件
├── docs/                      # 架构、开发、评测和发布文档
├── examples/
│   ├── question-packs/        # mathtutor.question-pack.v1
│   ├── community-plugins/     # mathtutor.community-plugin.v1
│   ├── code-plugins/          # mathtutor.code-plugin.v1
│   └── extensions/            # 可信 Python SDK 示例
├── scripts/                   # 检查、打包与评测脚本
└── .github/workflows/         # 现有跨平台 CI 和发布构建
```

## 贡献入口

- **第一次贡献题库**：阅读 [题库贡献指引](QUESTION_PACK_CONTRIBUTION.md) 和 [共享题库格式](SHARED_QUESTION_PACKS.md)。
- **编写声明式教学插件**：阅读 [插件快速入门](PLUGIN_QUICKSTART.md) 和 [插件开发指南](PLUGIN_DEVELOPMENT.md)。
- **编写 Python / TypeScript 插件**：阅读 [代码插件说明](CODE_PLUGINS.md)。
- **做深度宿主扩展**：阅读 [创作者扩展接口](CREATOR_EXTENSIONS.md)。
- **修改核心教学/数学能力**：在 `src/mathtutor` 改动并同步修改 `tests/`，特别说明答案披露与核验范围。

## 不应改变的核心设计约束

1. 受助作答、独立作答及看答案后的结果必须区别记录，不能把“懂了”直接当作掌握证据。
2. 题库参考答案不是自动核验结果；模型输出、插件结果不能直接抬高学生知识掌握度。
3. 社区声明式插件与可执行代码插件需要不同的权限确认；后者目前不是 OS 沙盒。
4. `web/` 是 Next.js 项目，不应机械更名成独立 `frontend/` 并破坏现有构建。
5. 现有跨平台 CI、数据迁移、发布门、已有评测结果和原始文档必须保留。
