# MathTutor 官网部署说明

目标地址：https://coscatld.github.io/MathTutor/

本站点是 GitHub **项目站点**（`/MathTutor` 前缀），使用 Next.js `output: "export"`，不需要 Node 常驻进程。

## 1. 首次启用 GitHub Pages

在仓库 `coscatld/MathTutor`：

1. Settings → Pages。
2. Source 选择 **GitHub Actions**（不要选 Deploy from a branch，以免覆盖未知的旧站点）。
3. 确认这是 Project site：`https://<owner>.github.io/MathTutor/`。
4. 确认环境 `github-pages` 存在；如启用了 required reviewers，首次发布需要有权限的维护者批准。
5. 确认 Actions 对 Pages 的 `pages: write` 与 `id-token: write` 未被组织策略禁止。

**在以上步骤完成并由维护者确认之前，不要把 workflow 改成 push 到 main 就自动正式发布。**

当前线上 `https://coscatld.github.io/MathTutor/` 在建设时返回 404，说明还没有可覆盖的正式站点。即便如此，第一次发布仍应走手动 `workflow_dispatch`。

## 2. GitHub Actions

工作流文件：`.github/workflows/deploy-site.yml`

| 事件 | 行为 |
|---|---|
| Pull Request（`site/**` 或该 workflow） | 构建 `site/`，运行 `verify:export`，**不部署** |
| Push `main`（同样路径） | 只构建和验证，**不部署** |
| `workflow_dispatch` 且勾选 `deploy` | 构建通过后发布 `site/out/` 到 GitHub Pages |

手动运行：

1. Actions → Deploy site → Run workflow。
2. 分支选 `main`。
3. 勾选 `deploy`。
4. 等待 `deploy` job 结束，打开 Pages URL 验证。

权限：

- `contents: read`
- `pages: write`（仅 deploy job）
- `id-token: write`（仅 deploy job）
- `environment: github-pages`（仅 deploy job）

该 workflow 不修改、不禁用 `cross-platform.yml`、`release-packaging.yml`、`windows-installer.yml`。

## 3. 本地开发

```bash
cd site
npm ci
npm run dev
```

开发服务器带 `basePath`，请打开：

http://127.0.0.1:3000/MathTutor/zh/

不要只在 `/` 根路径检查链接。

## 4. 静态构建

```bash
cd site
npm ci
npm run build
npm run typecheck
npm run verify:export
```

产物在 `site/out/`。`postbuild` 会写入 `out/.nojekyll`，避免 Jekyll 忽略 `_next/`。

## 5. 产物检查

`npm run verify:export` 至少确认：

- `out/.nojekyll`、`out/index.html`、`out/404.html`
- `/zh/` 与 `/en/` 的 Home、Features、Download、Architecture、Roadmap、Docs
- `sitemap.xml` 使用 `https://coscatld.github.io/MathTutor/`
- 抽样 HTML 含 `/MathTutor/`，不含 localhost

用子路径模拟 GitHub Pages：

```bash
mkdir -p /tmp/mt-pages/MathTutor
cp -R out/ /tmp/mt-pages/MathTutor/
npx --yes serve@14 /tmp/mt-pages -p 4173
```

然后访问 http://127.0.0.1:4173/MathTutor/zh/

## 6. 上线后验证

- https://coscatld.github.io/MathTutor/
- https://coscatld.github.io/MathTutor/zh/
- https://coscatld.github.io/MathTutor/en/
- https://coscatld.github.io/MathTutor/zh/docs/
- 刷新 Docs 深层 URL，应仍是 200（静态 `index.html`）
- CSS/JS、截图、favicon、搜索框
- 中英文切换应留在对应页面，而不是一律回首页

## 7. 常见 404 与资源路径

| 现象 | 原因 | 处理 |
|---|---|---|
| CSS 全挂 | Jekyll 忽略 `_next` | 确认 `out/.nojekyll` 被上传 |
| 资源请求 `/_next/...` | 漏了 `basePath` | `next.config.mjs` 必须有 `basePath: "/MathTutor"` |
| `/docs` 刷新 404 | 未开 `trailingSlash` | 保持 `trailingSlash: true`，让目录 `index.html` 生效 |
| 图片 404 | `public/` 写成了绝对根路径且绕过 Next | 用 `next/image` 或 `next/link`；裸 `href="/x"` 在自定义脚本里要自己加前缀 |
| 搜索空白 | 静态索引路径没带 basePath | `components/search.tsx` 的 `from` 必须是 `/MathTutor/api/search` |

## 8. 部署失败诊断

1. 打开失败的 Actions 日志，先看 `build` job 是否已经失败。
2. 本地复现 `cd site && npm ci && npm run build`。
3. 若 `deploy` 报 Pages 权限，检查 Settings → Pages → GitHub Actions，以及 environment `github-pages` 的保护规则。
4. 不要关闭仓库已有安全检查来“让它变绿”。

## 9. 回滚

优先重新发布一个已经验证过的 git 提交，而不是强推或清空历史：

1. 找出上一版绿灯的 commit SHA。
2. 在该 SHA 上 `workflow_dispatch` 并勾选 `deploy`（若 GitHub 允许对任意 SHA 运行；否则从该 SHA 开修复分支再手动部署）。
3. 不要 `git push --force` 覆盖 `main` 来回滚站点。
4. 不要删除 `gh-pages` 历史作为日常回滚手段。本仓库应使用 Actions artifact，而不是手改 `gh-pages` 分支。

## 10. 以后换成自定义域名

1. 在仓库 Pages 设置填写自定义域名。
2. 增加 DNS：`CNAME` 或 `A`/`AAAA` 按 GitHub 文档。
3. 把 `site/lib/site.ts` 的 `SITE_ORIGIN` / `SITE_URL` 改成新域名。
4. 若站点改到根域名，评估是否去掉 `basePath: "/MathTutor"`。
5. 重新构建，检查 sitemap、canonical、OG 图片和内部链接。
6. 在 `out/` 放置 GitHub 要求的 `CNAME` 文件（仅自定义域名需要）。

在域名切换完成前，不要把 sitemap 写成尚未生效的地址。
