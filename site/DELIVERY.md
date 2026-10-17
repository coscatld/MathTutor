# MathTutor 官网与 Docs 交付报告

日期：2026-10-17  
仓库：https://github.com/coscatld/MathTutor  
目标 URL：https://coscatld.github.io/MathTutor/

本报告区分 **IMPLEMENTED / TESTED / DEPLOYED / PARTIAL / NOT TESTED**。本地静态构建通过不等于 GitHub Pages 已上线。

## 1. 本轮修改文件清单

### 新增

- `site/` 全部官网与 Docs 工程（Next.js App Router、Fumadocs、中英 MDX、静态导出脚本）
- `.github/workflows/deploy-site.yml`
- `.github/ISSUE_TEMPLATE/documentation.yml`
- `docs/DISCUSSIONS.md`
- `design-system/mathtutor-official-site/MASTER.md`（UI/UX Pro Max 检索结果，营销站设计基线）

### 修改

- `README.md`：官网/Docs/Download 入口、真实 GitHub 徽章、DeepTutor 二次开发说明
- `CONTRIBUTING.md`：`site/` 开发与翻译
- `.gitignore`：忽略 `site/out/`、`site/.source/`

### 未改（回归边界）

- `web/` 教学应用路由与构建
- `desktop/` Electron 启动与打包配置
- `src/mathtutor/` Python 求解与教学业务
- 现有 `cross-platform.yml`、`release-packaging.yml`、`windows-installer.yml`

`docs/STUDENT_DATA_AVAILABILITY.md` 在本轮开始前已是工作区脏文件，本任务未把它当作交付物修改。

## 2. 新网站目录架构

```text
site/
├── app/                 # App Router：/[lang] 营销页与 docs、静态 search
├── components/
├── content/docs/        # 默认中文 MDX + *.en.mdx
├── lib/                 # 站点常量、发布清单、文案、Fumadocs source
├── public/              # favicon、og.png、真实产品截图
├── scripts/             # postbuild、verify-export
├── next.config.mjs      # output: export, basePath: /MathTutor
├── DEPLOYMENT.md
└── package.json
```

## 3. 实际完成的页面

| 路径 | 状态 |
|---|---|
| `/MathTutor/` 语言选择并跳转中文 | IMPLEMENTED, TESTED（静态 200） |
| `/zh/` `/en/` Home | IMPLEMENTED, TESTED |
| `/zh/features/` `/en/features/` | IMPLEMENTED, TESTED |
| `/zh/download/` `/en/download/` | IMPLEMENTED, TESTED |
| `/zh/architecture/` `/en/architecture/` | IMPLEMENTED, TESTED |
| `/zh/roadmap/` `/en/roadmap/` | IMPLEMENTED, TESTED |
| `/zh/docs/**` `/en/docs/**` | IMPLEMENTED, TESTED |
| `404.html` | IMPLEMENTED, TESTED（文件存在；GitHub Pages 未知路径行为 NOT TESTED 于线上） |

## 4. 文档清单

用户指南（中/英）：Introduction, Installation, Quick Start, Model Configuration, Math Tutoring Workflow, Learning Evidence, Knowledge Base, Privacy, FAQ。

开发者指南（中/英）：Architecture, Development Setup, API and WebSocket, Math Solver and Verifier, Teaching State Machine, EvidenceTracker and DKT, Retrieval and RAG, Testing and Evaluation, Desktop Packaging, Contributing。

## 5. GitHub Actions

`.github/workflows/deploy-site.yml`

- PR / push `main`（`site/**`）：`npm ci`、typecheck、static export、`verify:export`，**不部署**
- `workflow_dispatch` 且勾选 `deploy` 且在 `main`：上传 `site/out/` 并 `deploy-pages`
- 权限：`contents: read`；deploy job 另有 `pages: write`、`id-token: write`、`environment: github-pages`

首次实施未把 push 到 main 设为自动生产发布。

## 6. Static Export 构建结果

**TESTED（本地）**

```text
cd site && npm ci && npm run build && npm run typecheck && npm run verify:export
```

- Next.js 16.4.2 生产构建通过，56 个静态路由
- 产物 `site/out/`，含 `.nojekyll`
- TypeScript `tsc --noEmit` 通过
- KaTeX 在求解器文档中渲染为 `.katex`（非原始 `$...$`）
- Fumadocs CSS 有 `::highlight` 警告，不影响构建

选型：Fumadocs UI/Core 16.17.5 + fumadocs-mdx 15.4.7。官方 `examples/next-static` 使用 `output: "export"` 与 `staticGET` 搜索。i18n 采用 `[lang]` + `generateStaticParams`，**没有**使用 middleware/`proxy.ts`（静态托管不能跑）。

## 7. GitHub Pages 子路径测试结果

**TESTED（本地模拟，不是线上）**

将 `out/` 放到 `/tmp/mt-pages/MathTutor/`，用 `python3 -m http.server` 提供 `http://127.0.0.1:4173/MathTutor/`。

抽查均为 HTTP 200：中英文 Home/Features/Download/Architecture/Roadmap/Docs 多级页、sitemap、robots、favicon、og、截图、`/api/search`、CSS/JS（`/MathTutor/_next/...`）。

语言切换链接：`/zh/download/` → `/MathTutor/en/download/`；文档同 slug 切换。

**DEPLOYED：否。** `https://coscatld.github.io/MathTutor/` 在建设时返回 404。

## 8. 原应用回归

**TESTED（范围检查）**

`git diff` 未触及 `web/`、`desktop/`、`src/mathtutor/` 或原有三个 workflow。未为完成本任务改教学逻辑，也未跑全量 `python scripts/check.py`（与网站改动无直接耦合）。全量跨平台 CI：**NOT TESTED**（需 push 后看 GitHub Actions）。

## 9. 中英文与移动端

| 项 | 状态 |
|---|---|
| 中文首页/文档 | TESTED（静态 HTML） |
| 英文首页/文档 | TESTED |
| 语言切换到对应页面 | TESTED（真实 `<a href>`） |
| 文档刷新路径（trailingSlash index.html） | TESTED |
| 站内链接带 `/MathTutor` | TESTED |
| 搜索索引静态文件存在 | TESTED |
| 搜索 UI 在真实浏览器中输入查询 | NOT TESTED |
| 375px 真机/浏览器视口 | NOT TESTED（布局为移动优先 CSS + Fumadocs 响应式组件） |
| Dark/Light | IMPLEMENTED（next-themes / Fumadocs）；浏览器切换 NOT TESTED |

## 10. 实际部署状态

**NOT DEPLOYED**

未运行 `workflow_dispatch` 的 `deploy=true`，未改仓库 Pages 设置为 GitHub Actions，未覆盖任何现有站点。

## 11. 已知问题与限制

- Linux 安装包不展示下载按钮：发布矩阵为 UNTESTED，Releases 无验证产物。
- Mac/Windows 安装包无发行证书；Mac 未公证。页面已写明。
- DKT 标为部分/实验：最多一档调节，学习效果未在 MathTutor 学生数据上验证。
- Embedding 默认关闭；无 OCR。
- 搜索文件是 `out/api/search`（无扩展名）。本地 Python 服务器以 `application/octet-stream` 返回，客户端仍可解析 JSON。GitHub Pages 上的 MIME **NOT TESTED**。
- 截图来自 `docs/images/` 真实界面，不是生成的假 UI。
- UI/UX Pro Max 默认金色 CTA 已按任务改为蓝色主色。

## 12. 手动部署步骤

见 [DEPLOYMENT.md](DEPLOYMENT.md)。维护者确认 Pages 已启用后：

1. Settings → Pages → GitHub Actions。
2. Actions → Deploy site → Run workflow → 勾选 `deploy` → 分支 `main`。
3. 打开 https://coscatld.github.io/MathTutor/zh/ 复核资源与文档刷新。

在此之前不得宣称官网已经可用。
