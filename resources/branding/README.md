# MathTutor Logo

`mathtutor.svg` 是统一源文件：蓝色圆角方块、白色阶梯与目标圆点，沿用此前网页版的图形。品牌颜色固定为 `#1D4ED8`，不随应用主题变色。

在 macOS 上安装 Web 依赖后生成各端资源：

```bash
npm ci --prefix web
node scripts/generate-brand-assets.mjs
```

脚本通过 Web 已有的 Sharp 和 macOS 的 `iconutil` 生成 React 组件、浏览器图标、官网分享图、PNG、Windows ICO 与 macOS ICNS。生成文件均提交到仓库；Windows / Linux 构建直接使用这些文件，不需要 macOS 工具。

Web 与官网使用内联矢量，避免桌面离线加载或 GitHub Pages 子路径造成图片缺失。Logo 旁已有产品名称时作为装饰隐藏；可点击 Logo 的可访问名称由按钮提供。启动动画保留减少动态效果设置。
