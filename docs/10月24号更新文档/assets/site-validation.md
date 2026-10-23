# 官网最终验收

2026-10-24，macOS / 已安装 Chrome 的隔离上下文；服务为本地静态导出 `http://127.0.0.1:4174/MathTutor/`，未连接用户数据或部署公网。

- `NEXT_TELEMETRY_DISABLED=1 npm --prefix site run build` 通过；`npm --prefix site run typecheck` 通过；`npm --prefix site run verify:export` 通过，扫描304个文本文件。[构建日志](site-build.log)。
- 对全部导出HTML的内部链接作本地目标存在性检查：首次发现6处既有中英文安装/FAQ断链，修复后80个不同内部目标全部有效。[链接记录](site-links.json)。此检查不包含外链在线可达性及片段ID存在性。
- 实际Chrome：中文首页、中文文档首页、知识库指南、英文文档首页均HTTP 200、单个H1、桌面1440×1000无横向溢出；移动390×844首页/文档无溢出。
- 点击任务卡进入快速开始；切换英语保留文档路径；静态搜索返回学习证据、Escape关闭；移动侧栏展开并呈现用户指南；没有pageerror。
- 深色主按钮实测前景rgb(15,23,42)、背景rgb(96,165,250)，对比度7.02:1。测试上下文启用reduced-motion；截图禁用动画。
- 手工查看最终桌面文档、深色首页以及移动长页截图，检查层级、侧栏、断行和表格。未开展完整无障碍审计或真实读者可用性研究。

过程记录：初版浏览器脚本以English可见文字匹配语言链接，但该链接有独立aria-label，定位超时；改用实际href，并等待页面网络空闲。主题点击后立刻断言也早于异步状态更新，改为等待dark类后继续。这两项是验收脚本时序/定位修正，没有为通过而改产品逻辑。最终完整脚本通过，见[结果](site-browser.json)与[本次脚本](site-browser.cjs)。执行时使用现有本机Playwright。公开归档版本仅将其绝对路径替换为MATHTUTOR_PLAYWRIGHT_MODULE环境变量（默认playwright），未新增项目依赖。

截图： [桌面首页](site-home-desktop.png)、[深色首页](site-home-dark.png)、[文档首页](site-docs-desktop.png)、[知识库指南](site-guide-desktop.png)、[英文文档](site-docs-english.png)、[移动首页](site-home-mobile.png)、[移动文档](site-docs-mobile.png)。
