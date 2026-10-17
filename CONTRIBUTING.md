# 参与 MathTutor 开发

感谢参与 MathTutor。项目使用 Python 3.11–3.13、FastAPI、Next.js/React、Electron，并按照仓库根目录 `LICENSE` 采用 Apache-2.0 许可证。

## 从哪里开始

1. 阅读 [README](README.md)、[插件开发指南](docs/PLUGIN_DEVELOPMENT.md)和[共享题库格式](docs/SHARED_QUESTION_PACKS.md)。
2. 在 Issues 中确认需求、复现步骤、验收标准；准备大改动前先讨论方案。
3. Fork 仓库，以 `feat/`、`fix/`、`docs/` 或 `test/` 开头创建功能分支。
4. 针对一个目标提交较小的 Pull Request；写明影响模块、测试方法与安全边界。

## 本地开发

```bash
git clone https://github.com/coscatld/MathTutor.git
cd MathTutor
python -m venv .venv
# macOS / Linux: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m mathtutor
```

另开终端启动前端：

```bash
cd web
npm ci
npm run dev
```

默认服务端地址是 `http://127.0.0.1:8001`，前端是 `http://127.0.0.1:3000`。如需桌面客户端，按 README 的 `desktop/` 步骤构建。

## 提交前检查

```bash
python -m pytest tests/test_community_plugins.py tests/test_community_plugins_api.py tests/test_code_plugins.py -q
python -m pytest tests/test_question_packs.py -q
cd web
npm ci
npm run test
npm run build
```

完整项目回归使用 `python scripts/check.py`，并由 `.github/workflows/cross-platform.yml` 执行跨平台检查。它包含后端和桌面 Python 测试、前端测试、生产构建与桌面源码契约；只有配置了目标 `MATHTUTOR_PYTHON_RUNTIME` 时才检查分发运行时，实际安装包另做目标平台验收。若某条本地测试命令不存在，请在 PR 中说明，并优先遵循仓库现有 CI 和文档，不要修改 CI 以掩盖问题。

## 官网与文档翻译

官网和 Docs 在独立目录 `site/`，不修改 `web/` 教学应用路由。

```bash
cd site
npm ci
npm run dev          # http://127.0.0.1:3000/MathTutor/
npm run build
npm run verify:export
```

- 默认文档是简体中文 `*.mdx`，英文为同 slug 的 `*.en.mdx`。
- 不要提交空白英文页或指向不存在翻译的链接。
- 只根据仓库代码和已有报告写文档，不要按模块名补不存在的接口。
- 部署说明见 [site/DEPLOYMENT.md](site/DEPLOYMENT.md)。GitHub Pages 的正式发布需要维护者确认后再运行 `deploy-site.yml` 的手动部署。

## 题库贡献

- 共享题库使用 `mathtutor.question-pack.v1`，参考 [题库贡献指引](docs/QUESTION_PACK_CONTRIBUTION.md)。
- 只贡献有权发布的原创题目或明确授权的内容；保留来源、许可和修改说明。
- `answer` 是作者提供的参考答案，**不会自动被识别为数学形式化验证结果**。
- 不要在公开样例中包含学生真实作答、姓名、邮箱、学习日志等个人信息。

## 插件贡献

- 声明式插件使用 `mathtutor.community-plugin.v1`，支持 `exam-builder`、`mistake-review`、`learning-report`。
- 代码插件使用 `mathtutor.code-plugin.v1`，Python/TypeScript 文件只能在用户明确同意后执行；**不是操作系统沙盒**。
- 不得通过插件绕过答案披露策略、学生身份与资源范围、学习证据写入约束。
- 必须描述所需权限、输入/输出、版本更新和限制；不要捆绑密钥或用户数据。
- 详细步骤见 [插件快速入门](docs/PLUGIN_QUICKSTART.md)。

## Pull Request 最低要求

- [ ] 说明问题、解决方案与范围
- [ ] 关联 Issue 或说明背景
- [ ] 提供可复现的测试命令与结果
- [ ] 未包含个人数据、密钥或无授权资源
- [ ] 对用户可见行为变化更新文档、测试及 CHANGELOG（适用时）
- [ ] 不将“题目答案正确”“教学能力提升”或“真实掌握度准确”混作一个指标

## 报告安全问题

请不要在公开 Issue 中披露可利用的漏洞、私人数据或密钥。参见 [SECURITY.md](SECURITY.md)。
