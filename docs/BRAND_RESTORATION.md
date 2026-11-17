# 品牌图标统一与构建修复

日期：2026-11-17（Asia/Shanghai）。

## 统一图标

恢复蓝底白色阶梯与目标圆点的旧版 Logo，以此前官网的矢量图为基础。源文件是 [`resources/branding/mathtutor.svg`](../resources/branding/mathtutor.svg)，颜色固定为 `#1D4ED8`，深浅主题使用同一标识。

覆盖应用侧栏、启动页、欢迎页、聊天头像、登录注册与引导页，以及官网、文档导航、README、浏览器图标和分享卡片。移除原位图裁切方式，组件直接内联矢量，避免低分辨率放大和离线图片路径缺失。

桌面资源包含 macOS ICNS、Windows 多尺寸 ICO 和 Linux PNG。Windows 安装与卸载程序、桌面窗口显式指定品牌图标；打包同时带入 Web 的 public 资源。历史验收截图保留当时的画面。

维护时只修改 SVG，再运行 [`scripts/generate-brand-assets.mjs`](../scripts/generate-brand-assets.mjs)。生成方法见[品牌资源说明](../resources/branding/README.md)。

## 构建检查

核查开始时，`fb6a740` 的跨平台 CI 已通过；更早两个提交因 Windows 下生成类型的换行比较失败，已经在该提交修正，历史失败记录仍保留。

这次重新构建官网时，Next.js 的安全升级检查阻止构建结束。依赖审计确认官网与应用 Web 的 Next.js 均处于已公告的受影响范围，因此将两个包及锁文件统一到修复后的 `16.4.6`，随后重新执行构建。没有通过关闭安全检查处理该错误。

参考：[Next.js 官方安全公告 GHSA-mfr8-8qww-v76h](https://github.com/vercel/next.js/security/advisories/GHSA-mfr8-8qww-v76h)。

## 本地验证

- Web 334 项测试通过；生产构建与 API 类型同步检查通过。
- 官网生产构建、TypeScript 检查与静态导出检查通过。
- Node 桌面契约 57 项通过，2 项因未提供最终安装产物跳过；Python 桌面测试 6 项通过。
- Windows ICO 的 7 个尺寸可解析，macOS ICNS 可由系统工具读回 PNG。
- 连接隔离数据目录的真实后端，检查四种主题、桌面和手机布局，确认 Logo 保持品牌色、图形完整且无横向溢出。
- 官网中英文首页和文档页，以及 GitHub Pages 子路径下的图标与分享图片均检查可用。

这些改动更新源码和后续构建使用的资源，不覆盖先前发布的安装包。新安装文件与官网发布仍遵循各自的打包、验收与发布流程。
