# 0.3.3 主线同步：本地验证记录

日期：2026-09-16。工作票 EXP-W02-002。基线 `133d49e884cef0e9526b0d53dc38c839696e6109`。

## 本轮本地检查

在 Windows 11 / Python 3.12.3 上运行与 CI 相同的 `python scripts/check.py`，完整检查成功，执行期间受检源码没有变化。

| 检查 | 结果 |
| --- | --- |
| pytest（tests＋desktop/tests） | 1099 PASS / 9 SKIP，0 FAIL / ERROR |
| 前端测试 | 160 PASS |
| Next.js 优化生产构建及 TypeScript | PASS |
| 桌面 Node 契约 | 44 PASS / 2 SKIP |
| 独立 PyTorch 环境知识追踪补验 | 27 PASS / 0 SKIP |
| 正式模型冻结交付清单 | 90 文件哈希一致；未改动 |

pytest 跳过项：本机主环境缺 PyMuPDF 的 2 项、缺 torch 的 3 项、依赖 Mac 专用 sqlite-vec 探测 dylib 的 4 项。torch 3 项已在另一个环境补验；不能宣称另外 6 项在本机实测通过。桌面跳过的发行相关门禁和未提供目标 runtime 的 distribution 检查，不是发布成功。

新增 8 项主线合并语义回归、1 项验证子进程环境回归；保留第二周 13 项生产证据契约。新测试通过项目现有 pytest 入口自然进入全部平台。

工作区证据：`research-runs/week02-main-sync-20260916/checks/20260916T154358Z/`（结果 JSON、JUnit、stdout/stderr、受检源码 SHA256）。这些大日志未混入应用资源或仓库发布包。

## 失败记录与修正

首次全流程在 pytest 1098 PASS / 9 SKIP、前端 160 PASS 后，Next.js 遥测配置原子写入发生 EXDEV。仅在 `scripts/check.py` 的验证子进程设置 `NEXT_TELEMETRY_DISABLED=1`，不修改用户全局偏好或安装包行为；第二次完整运行成功。第一次日志保留在 `checks/20260916T153617Z/`。

PyTorch 补验首次缺少产品 src 的 PYTHONPATH，收集失败；修正测试环境路径后 27/27 成功，两个 XML 都保留。不为此修改正式运行时依赖或安装目录。

## 云端与发行边界

同步取得的 main `133d49e...` 已有 Linux/macOS/Windows 三平台 Actions 成功：[main 验证运行](https://github.com/coscatld/MathTutor/actions/runs/35114689470)。这是上游提交证据，本次新增改动的云端结果应以其独立 PR 的精确提交与检查为准，不能借用 main 绿灯。

本轮保留三平台 CI 与 Mac/Windows CD 工作流原样，不绕过真实 runtime、校验和、签名或打包 smoke。用户授权新分支与 PR；未授权直接更新 main、合并 PR 或发布安装器。旧 Mac 0.3.3 DMG 的验收不代表本次新增代码已经重新打包。

DKT 目标预测仍关闭；本轮只有接口兼容性研究和工程契约，不产生新的学习效果结论。接入顺序见 `DKT_INTEGRATION_RESEARCH.md`。
