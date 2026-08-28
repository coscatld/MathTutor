# ADR: MathTutor 桌面壳（Electron）

- 状态：**Accepted**（v0.3.0，2026-08-21，Phase 6 第二轮 + Desktop Production Readiness）
- 日期：2026-08-20（v0.2.0 初版；v0.3.0 修订见文末「修订历史」，正文为当前事实）

> 修订原则（项目文档纪律）：历史章节不覆盖当前事实——v0.2.0 的过时声明在正文中已就地修正，原断言保留于「修订历史」快照。

## 背景与问题

K12 MathTutor 是本地优先的辅导产品：核心练习、资料库、记忆图谱和 AI
模型配置都运行在用户自己的机器上。需要把已有的 Web 产品（Next.js 前端 +
FastAPI 本地服务）包成桌面应用，同时满足三个硬约束：

1. **密钥安全**：API key 永不进 localStorage / 普通 config JSON / SQLite 业务表，
   只进 OS 级凭据存储（macOS 钥匙串，`com.mathtutor.product` service）。
2. **不扫描用户磁盘**：唯一的文件入口是「用户显式点击 → 系统文件对话框」，
   绝不遍历 Downloads/Documents/Desktop。
3. **业务逻辑不进 Electron**：壳只做原生窗口、系统对话框、进程启停与打包。

## 决策

### D1. Electron 是薄壳，不是应用

`desktop/main.js` 只做四件事：spawn 本地 Python 服务、spawn Next.js 前端、
在 127.0.0.1 上起一个 loopback `/native-pick` 端点、开一个锁定配置的窗口。
任何辅导/文档/记忆/设置逻辑都不允许出现在 Electron 或 renderer 里。

### D2. 架构：三层，全部走 HTTP/WS

```
┌─────────────────────────────────────────────────────────┐
│ Electron 壳 (desktop/main.js)                            │
│  · BrowserWindow → http://127.0.0.1:<frontendPort>       │
│  · loopback /native-pick（dialog + fs.readFile）         │
└───────────────┬─────────────────────────────────────────┘
                │ spawn（standalone MathTutor Python）
┌───────────────▼─────────────────────────────────────────┐
│ Python 产品服务 (uvicorn --factory 127.0.0.1:随机端口)    │
│  mathtutor.api.product_app                    │
│  create_math_tutor_app_from_runtime                      │
│  env: MATHTUTOR_DESKTOP=1                                │
│       MATHTUTOR_ELECTRON_PICKER_URL=<loopback picker>    │
│  key → KeychainSecretStore (macOS security CLI)          │
└───────────────┬─────────────────────────────────────────┘
                │ MATHTUTOR_API_BASE_URL 注入
┌───────────────▼─────────────────────────────────────────┐
│ Next.js 前端 (next start/next dev -p 随机端口)            │
│  proxy.ts 中间件把 /api/*、/ws/* 重写到后端               │
│  桌面视图在 web/features/math-tutor/desktop/             │
└─────────────────────────────────────────────────────────┘
```

- 前端**无需改动任何 API 调用**：`web/proxy.ts` 已在请求时按
  `MATHTUTOR_API_BASE_URL` 重写，壳注入该环境变量即可。
- renderer 与 Electron 的唯一交互是 `window.desktopAPI`（preload 暴露的
  `isDesktop` 标记）。文件选择路径是：用户点击「添加资料」→ Python
  bridge `POST /documents/pick` → Python 转发到壳的
  `MATHTUTOR_ELECTRON_PICKER_URL`（loopback）→ 系统对话框 → 字节回流 →
  本地 import 端点。无对话框之外的任何文件系统访问。

### D3. 后端启动方式

`uvicorn --factory mathtutor.api.product_app:create_math_tutor_app_from_runtime`
（必须可从独立 MathTutor 环境导入）。端口全部随机、只绑 `127.0.0.1`。
Python 解析顺序：`MATHTUTOR_PYTHON` → 仓库根目录 `.venv`；发行包只使用
内置的可重定位 runtime。

### D4. 密钥只进 OS 凭据库

桌面生产模式（`MATHTUTOR_DESKTOP=1` 且非 dev）下，ProductState 的
`_default_secret_store()` 返回 **单实例** `KeychainSecretStore`
（`infrastructure/keychain_secret_store.py`）——设置面与 model gateway
共享同一实例（2026-08-21 审计修复：此前 desktop_api 每次新建实例、
gateway 绑定 InMemory，桌面生产下 key 存进 Keychain 但解析不到；
修复后 +2 测试锁定共享）。

- macOS：`security add-generic-password -U -s com.mathtutor.product -a <key> -w`，
  值经 **stdin 两遍** 传入，不进 argv（`ps` 不可见）；`find` 用退出码 44 表示不存在。
- Linux：`secret-tool store/lookup`。
- **Windows：Credential Manager（advapi32，2026-08-21 落地）**——ctypes 直调
  `CredWriteW`/`CredReadW`，值只经内存 `CREDENTIALW.CredentialBlob`，不进 argv/文件/环境；
  未找到映射 fail-closed（抛 `KeychainSecretStoreError`，不静默降级 InMemory）。
  **诚实标注：UNTESTED on a real Windows host**（本项目无 Windows 机器，adapter
  按文档化 API 实现；平台矩阵见文末）。
- 前端永远只拿到掩码尾号 `••••••••abcd`；GET /settings 不含任何 key 材料。

### D5. 文件选择：显式点击 + loopback，绝不扫描

- `/native-pick` 只监听 127.0.0.1、只接受 POST、要求 `student_id`。
- `dialog.showOpenDialog` 只在该端点被 UI 显式点击触发时打开。
- 返回单文件字节（base64），上限 20MB，与 `MAX_DOCUMENT_BYTES` 一致。
- 后端桥 `LoopbackElectronPickTransport` 不可用（未设 URL / 非 200）时，
  `/documents/pick` 返回 501「此环境不支持原生文件选择」，UI 回退到
  `<input type=file>`；**任何情况下都不扫描用户目录**
  （`test_desktop_bridge.py::test_picker_source_never_scans_directories`
  静态断言 `desktop_files.py`/`desktop_api.py` 无 walk/scandir/iterdir/glob）。

### D6. 渲染层安全基线

`contextIsolation: true`、`nodeIntegration: false`、`sandbox: true`、
`webSecurity: true`；preload 只暴露 `desktopAPI.isDesktop/platform`。

## 后果

正面：

- 密钥、文档、记忆、模型配置全部复用既有 Web 桥的 HTTP 契约，无第二套状态机。
- 前端 node 测试（30 个新用例）验证：掩码尾号、无 localStorage 用法（源码扫描）、
  `extra.child_cycle_id` 只有 `offer-navigation.ts` 一个读取点。
- 安全边界可用测试锁定（后端 38 个桌面桥测试 + 前端源码扫描测试）。

代价/注意：

- SecretStore 单实例接线已落地（`product_state._default_secret_store()`，
  2026-08-21 审计修复，+2 测试）；桌面生产启动时构造 ProductState 即自动
  使用 KeychainSecretStore（含 Windows Credential Manager adapter），
  不再需要额外接线。
- `next start` 需要 `.next` 或 `.next-mathtutor` 构建产物；壳优先用
  `.next-mathtutor`（产品构建），退而求其次 `.next`，都没有则 `next dev`。
- `accept_practice_offer` 的 child-cycle 跳转依赖
  `/api/v2/math-tutor/offers` 与 WS 公共事件 `extra.child_cycle_id`（已实现）。
- 已知：`dev-heap-ceiling.test.ts` 因仓库根目录无 `Dockerfile` 失败（既有问题，
  与桌面集成无关）。

## 修订历史

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1.0 | 2026-08-19 | 初版：Electron 薄壳决策（D1 壳只做窗口/对话框/启停） |
| v0.2.0 | 2026-08-20 | Phase 5/6 桌面集成：三端口编排、KeychainSecretStore（macOS/Linux；**Windows 显式不支持**）、/native-pick loopback、渲染层安全基线、30 前端测试 |
| v0.3.0 | 2026-08-21 | Phase 6 第二轮 + Desktop Production Readiness：**Windows Credential Manager（advapi32）落地（UNTESTED on real host）**、SecretStore 单实例审计修复（`_desktop_secret_store()` 移除，`_default_secret_store()` 下沉 ProductState）、bootstrap 九步骤（STARTING→…→READY/DEGRADED/BLOCKED）、backups 四端点（list/create/verify/restore + 路径穿越防御）、resident outbox relay（启动常驻/shutdown 停）、`GET /student-summary`（未观察 skill mastery=null）、`POST /model/test` 五类错误文案、privacy UI（文档/记忆删除/检索开关，不可编辑 mastery）、smoke-full 14/14。平台矩阵（诚实标注）：macOS=TESTED（smoke 全过）；Windows/Linux=PARTIAL（adapter 已实现，无目标机实测）。 |
