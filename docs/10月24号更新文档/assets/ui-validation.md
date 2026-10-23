# UI 验证记录 · 2026-10-24

本记录对应本轮学习画像、知识库与对话资料导航改动。时间使用北京时间，测试约在 00:32–00:38 运行。测试未调用付费模型、未读取用户聊天或密钥。

## 验证结果

| 验证 | 实际结果 |
| --- | --- |
| `cd web && npm test` | 251 项通过，0 失败；包含新增 6 项画像分类、未知计数、资料导航和加载状态回归。 |
| `cd web && npm run build` | 通过，生成 16 个页面路由并完成 TypeScript 检查。最终全仓复验结果以本轮主报告为准。 |
| `smoke-learning-profile.mjs` | 通过：1280×800、1024×768、375×812、812×375；证据抽屉、Esc 关闭与焦点返回、排除判定、空态、503 重试、偏好展开。 |
| 同一画像浏览器脚本新增检查 | 通过：浅色与深色、减少动画、可见键盘焦点、资料选择导航保留当前会话且不写入 scope、新会话生成 session 后保留 panel、刷新仍打开资料面板。 |
| `smoke-vault-files.mjs` | PASS；覆盖文件别名移动、共享正文保存、检索切换、编辑后资料库导出。 |
| `smoke-learning-support.mjs` | PASS；覆盖教学支持、对话资料、选中文档范围、记忆、窄屏、横屏和深色知识库。 |
| `git diff --check` | 通过。 |

首次前端测试为 250/251：资料范围读取失败时，说明文字仍建议点击“应用到当前对话”，触发既有失败状态断言。已改为按真实读取状态显示说明，保留原断言，重跑 251/251 通过。

## 执行方式

生产预览使用 `npm run start -- --port 3197`，测试完成后已停止。此配置使用 standalone 输出，Next.js 启动时提示部署应运行 standalone server；本轮没有修改部署方式。

浏览器使用本机 Google Chrome 和 Codex 随附的 Playwright：

```bash
PLAYWRIGHT_MODULE=<USER_HOME>/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs \
CHROME_EXECUTABLE='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' \
PROFILE_QA_URL=http://127.0.0.1:3197 \
node scripts/smoke-learning-profile.mjs
```

另外两个脚本使用同样的 `PLAYWRIGHT_MODULE`、`CHROME_EXECUTABLE`，地址变量为 `LAYOUT_URL=http://127.0.0.1:3197`。

## 数据与验收范围

浏览器脚本拦截全部业务 API 和相关 WebSocket，使用隔离的合成业务样例：独立与受助作答、未知/空画像、证据排除、资料范围及导入导出。它验证的是界面、导航、状态与前端契约，不是生产后端的真实模型调用，也不证明学生学习效果。

后端证据和权限隔离由本轮其他回归覆盖。本次未运行 Electron 安装包、Windows 或 Linux 桌面测试，未开展真实学生实验、迁移效果或长期保持评测。

截图使用 `animations: disabled` 固定到入场动画结束状态；减少动画另通过媒体偏好及计算样式断言验证。已实际查看桌面画像、桌面知识库及窄屏深色截图。

## 截图

- `ui-profile-desktop.png`：1280×800，画像“下一步 → 实际观察”的层级与三类作答计数。
- `ui-knowledge-desktop.png`：1280×800，资料保存、选择范围、追溯引用的流程与入口。
- `ui-profile-mobile-dark.png`：375×812，深色、减少动画与空画像。

截图为合成测试样例，不是用户生产数据。最后一处 UI 微调恢复了复盘折叠区的原生展开标记；主流程最终构建需包含该样式调整。
