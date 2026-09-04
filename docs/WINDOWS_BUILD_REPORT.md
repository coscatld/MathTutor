# MathTutor Windows x64 构建与测试报告

- 测试日期：2026-09-05（Asia/Shanghai）
- 测试平台：Windows 11 `10.0.26100` x64
- 安装器：`MathTutor-0.2.0-win-x64.exe`
- 大小：130,630,054 bytes
- SHA-256：`efb4f775fb8e22f32564dd5170bd9f41c27f5fe62af00c3e90e8465c7f25df22`

## 结果

- Python：568 passed，4 skipped（仅 macOS `.dylib` sqlite-vec 可选探测）
- Web：67 passed；Next.js production standalone build PASS
- Desktop contracts：28 passed，2 skipped（两个仅适用于 macOS `.app` 目录结构的最终包检查）
- Windows package-surface audit：PASS，3,169 个文件，0 个禁止路径
- 安装器公共发布 smoke：19/19 PASS
- 产品全流程 smoke：17/17 PASS
- Next.js 浏览器静态资源：PASS，11 个 JS/CSS 文件均可访问
- NSIS 静默安装：PASS（非管理员、安装路径含空格和中文）
- 生产认证注册/登录/readiness：PASS
- Windows Credential Manager 写入/读取/删除/最终不存在：PASS
- 数据库 migration `006`、Verifier Worker、练习流程、文档检索、Memory CRUD、备份/恢复、重启和无孤儿进程：PASS
- 静默卸载并保留用户数据：PASS

## 尚未关闭的发布项

- Authenticode：未签名（缺少外部代码签名证书）
- 中文 Windows 用户名：本机用户名为 ASCII，未实测；中文安装路径已通过
- Native File Picker：静态和单元测试通过，未做人工 GUI 点击验收
- Windows 旧版本升级：缺少上一版 Windows 安装器，未实测
- 图标：当前使用 Electron 默认图标

机器可读的 19 项 RC smoke 结果见
[`rc/WINDOWS_X64_RC_PUBLIC_RELEASE_SMOKE.json`](rc/WINDOWS_X64_RC_PUBLIC_RELEASE_SMOKE.json)。
package-surface 报告可通过以下命令生成；`desktop/dist` 构建目录不纳入 Git：

```powershell
.\.venv\Scripts\python.exe .\desktop\scripts\audit-package-surface.py `
  --app .\desktop\dist\win-unpacked `
  --report .\desktop\dist\package-surface-audit.json
```
