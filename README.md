# MathTutor

独立的 K12 数学辅导桌面应用。Python distribution、import package 和命令行
入口均为 `mathtutor`；运行和安装包都不依赖 DeepTutor 源码仓库。

## 从源码运行

### 环境要求

- macOS、Linux 或 Windows（当前正式验证的桌面安装包为 macOS arm64）
- 标准开发环境：Python 3.12、Node.js 20
- 发行包仍支持 `pyproject.toml` 中声明的 Python 3.11–3.13

Windows 与 macOS 使用同一份受 Git 管理的源码。文件系统、运行时和凭据库
差异集中在桌面基础设施层，不复制业务模块。

### 1. 安装并启动后端

在项目根目录执行：

```bash
python -m venv .venv
# macOS/Linux：source .venv/bin/activate
# Windows PowerShell：.venv\Scripts\Activate.ps1
python -m pip install -e '.[dev]'
python -m mathtutor
```

后端默认监听 `http://127.0.0.1:8001`。`MATHTUTOR_DATA_ROOT` 中保存 SQLite、
上传资料和备份，属于运行时数据，不应提交到 Git。

### 2. 安装并启动前端

另开一个终端：

```bash
cd web
npm ci

npm run dev
```

浏览器访问 `http://127.0.0.1:3000/`。本机开发默认为 loopback 单用户模式：
首次启动进入 Provider/API Key 配置（也可跳过使用模板教学），之后直接进入
工作台，不需要注册或登录。显式 auth-on 的远程/网络部署仍保留现有认证边界。

### 3. 运行源码版 Electron 桌面壳

先完成上面的 Python 安装，再构建前端：

```bash
cd web
npm ci
npm run build

cd ../desktop
npm ci
npm start
```

Electron 会自动选择随机 loopback 端口，依次启动本地 Python 服务、Verifier
Worker 和 Next.js 前端，无需手动保留前两节的进程。

### 4. 测试

```bash
# Windows/macOS/Linux 通用（需先安装上述依赖）
python scripts/check.py
```

该命令使用当前 Python 解释器运行后端与 Python 桌面契约测试，并依次执行前端
测试、生产构建与 Node.js 桌面发行契约测试。CI 在 Windows、macOS 和 Linux 上
用 Python 3.12 / Node.js 20 执行同一组验证。

## 使用 macOS DMG

当前 DMG 仅适用于 Apple Silicon（arm64）Mac，并且尚未使用 Apple Developer ID
签名或公证。

### 安装

1. 双击 `MathTutor-0.3.0-mac-arm64.dmg`。
2. 将 `MathTutor.app` 拖入“应用程序”文件夹。
3. 第一次打开时，macOS 可能提示无法验证开发者。关闭提示后进入“系统设置 →
   隐私与安全性”，在 MathTutor 提示旁点击“仍要打开”，再次确认启动。
4. 不要通过关闭 Gatekeeper 或执行全局 `xattr` 命令绕过系统安全机制。

### 首次运行流程

1. Electron 在本机随机端口启动内置后端、Verifier Worker 和前端，所有服务只
   监听 loopback。
2. 应用创建本地数据目录并自动执行数据库 migration 001–014。macOS 数据通常
   位于 `~/Library/Application Support/MathTutor/`。
3. 启动页检查本地配置。未配置时进入 `/onboarding/provider`；已配置或曾明确
   跳过时直接进入 `/math-tutor`。普通桌面流程不显示注册或登录页。
4. Onboarding 可选择模型服务商并填写 API Key，也可选择“暂时跳过，使用模板教学”。
5. API Key 在 macOS 保存到 Keychain，在 Windows 保存到 Credential Manager；
   平台差异封装在统一 `SecretStore` 之后。普通配置、SQLite、日志和前端存储不会保存
   明文密钥。
6. 不配置 API Key 时，Parser、Solver、Verifier Worker、AttemptVerifier、
   StudentState、课程与模板辅导仍可使用；生成式个性化功能显示为降级状态。

日常工作台包含“练习、练习邀请、我的资料、我的记忆、设置、我的数据”。提交
题目后，系统按 `parse → solve → verify → 分级提示 → attempt verification →
LearningEvidence → StudentState` 推进；所有数学事实和学习状态更新均经过确定性
验证。

关闭 MathTutor 会停止本地子进程，但 SQLite、学习资料、Personal Memory 和备份
继续保留在用户数据目录。删除 `MathTutor.app` 不会自动删除这些数据。

## macOS 安装包校验

发布者会在 GitHub Release 中同时给出 DMG 的 SHA-256。下载后可执行：

```bash
shasum -a 256 MathTutor-0.3.0-mac-arm64.dmg
```

输出必须与 Release 描述中的 SHA-256 完全一致后再安装。

### 卡在“正在启动 MathTutor”

如果窗口长时间停在该画面，先退出 MathTutor，再核对下载文件的
SHA-256。0.3.0 本地构建的校验值见 `docs/releases/0.3.0.md`；
安装包由维护者手动上传，提交源码不代表已发布 GitHub Release。

旧候选包曾遗漏 Next.js 浏览器静态资源，会导致页面 HTML 能打开，但
JavaScript/CSS 返回 404，因而无法完成启动路由。安装当前包时只需替换
`/Applications/MathTutor.app`；不需要删除用户数据目录。

## 构建 Windows x64 安装包

在 Windows 10/11 x64 的 PowerShell 中执行：

```powershell
Set-Location web
npm ci
Set-Location ..\desktop
npm ci
npm run package:win
```

该命令会构建 Next.js standalone 前端、下载并校验 Python 3.12 x64
embeddable runtime、只安装产品运行依赖，然后生成 NSIS 安装器。产物位于
`desktop\dist\MathTutor-0.3.0-win-x64.exe`。本地构建默认不带 Authenticode
签名；公开发布前应在受控签名环境中配置证书，并重新执行安装包 smoke。
