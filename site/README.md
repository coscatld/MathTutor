# MathTutor 官网与 Docs

独立静态站点，部署目标：https://coscatld.github.io/MathTutor/

与 `web/` 教学应用隔离：本目录有自己的 `package.json`、依赖和构建产物。访问官网不需要 Python 或 API Key。

知识探索的中英文说明位于 `content/docs/user/knowledge-exploration*.mdx`，首页与下载页标注源码预览状态。真正的探索入口 `/math-tutor/explore` 由 `web/` 与 Python 服务提供，官网不代发知乎请求。已发布安装包尚不包含探索功能。

```bash
npm ci
npm run dev      # http://127.0.0.1:3000/MathTutor/zh/
npm run build    # 输出 site/out/
npm run verify:export
```

配置说明见 [DEPLOYMENT.md](DEPLOYMENT.md)。当前发布地址：https://coscatld.github.io/MathTutor/
