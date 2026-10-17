# MathTutor 官网与 Docs

独立静态站点，部署目标：https://coscatld.github.io/MathTutor/

与 `web/` 教学应用隔离：本目录有自己的 `package.json`、依赖和构建产物。访问官网不需要 Python 或 API Key。

```bash
npm ci
npm run dev      # http://127.0.0.1:3000/MathTutor/zh/
npm run build    # 输出 site/out/
npm run verify:export
```

配置说明见 [DEPLOYMENT.md](DEPLOYMENT.md)。在维护者启用 GitHub Pages 并批准首次发布前，站点未上线。
