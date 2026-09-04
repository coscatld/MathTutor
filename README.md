# MathTutor

独立的 K12 数学辅导桌面应用。Python distribution、import package 和命令行
入口均为 `mathtutor`；运行和安装包都不依赖 DeepTutor 源码仓库。

## 从源码运行

### 环境要求

- macOS、Linux 或 Windows（当前正式验证的桌面安装包为 macOS arm64）
- Python 3.11–3.13
- Node.js 20+

下面的源码命令以 macOS/Linux shell 为例；Windows PowerShell 中的虚拟环境
可执行文件位于 `.venv\Scripts\`，环境变量使用 `$env:NAME="value"` 设置。

### 1. 安装并启动后端

在项目根目录执行：

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'

MATHTUTOR_DATA_ROOT=/tmp/mathtutor-dev-data \
MATHTUTOR_ENVIRONMENT=development \
MATHTUTOR_AUTH_ENABLED=1 \
.venv/bin/mathtutor
```

后端默认监听 `http://127.0.0.1:8001`。`MATHTUTOR_DATA_ROOT` 中保存 SQLite、
上传资料和备份，属于运行时数据，不应提交到 Git。

### 2. 安装并启动前端

另开一个终端：

```bash
cd web
npm ci

MATHTUTOR_API_BASE_URL=http://127.0.0.1:8001 \
MATHTUTOR_AUTH_ENABLED=1 \
npm run dev
```

浏览器访问 `http://127.0.0.1:3000/math-tutor`。全新数据目录会自动跳转到
`/register`；创建第一个本地账户后登录即可进入工作台。

仅做无账户的本机界面调试时，可将前后端的 `MATHTUTOR_AUTH_ENABLED` 都设为
`0`；不要在公开监听或生产环境关闭认证。

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
# 后端
.venv/bin/pytest

# 前端
cd web
npm test
npm run build

# Desktop contracts
cd ../desktop
npm run test:distribution
```

## 使用 macOS DMG

当前 DMG 仅适用于 Apple Silicon（arm64）Mac，并且尚未使用 Apple Developer ID
签名或公证。

### 安装

1. 双击 `MathTutor-0.2.0-mac-arm64.dmg`。
2. 将 `MathTutor.app` 拖入“应用程序”文件夹。
3. 第一次打开时，macOS 可能提示无法验证开发者。关闭提示后进入“系统设置 →
   隐私与安全性”，在 MathTutor 提示旁点击“仍要打开”，再次确认启动。
4. 不要通过关闭 Gatekeeper 或执行全局 `xattr` 命令绕过系统安全机制。

### 首次运行流程

1. Electron 在本机随机端口启动内置后端、Verifier Worker 和前端，所有服务只
   监听 loopback。
2. 应用创建本地数据目录并自动执行数据库 migration 001–006。macOS 数据通常
   位于 `~/Library/Application Support/MathTutor/`。
3. 首次访问工作台会进入注册页；第一个本地账户具有管理员角色。
4. 注册成功后进入登录页，登录后打开中文数学辅导工作台。
5. 欢迎弹窗允许选择模型服务商并填写 API Key，也可以选择“跳过，使用模板教学”。
6. API Key 只保存到 macOS 钥匙串；普通配置、SQLite、日志和前端存储不会保存
   明文密钥。
7. 不配置 API Key 时，Parser、Solver、Verifier Worker、AttemptVerifier、
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
shasum -a 256 MathTutor-0.2.0-mac-arm64.dmg
```

输出必须与 Release 描述中的 SHA-256 完全一致后再安装。
