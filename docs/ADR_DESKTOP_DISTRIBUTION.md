# 0.7.0 Mac r2 修正记录 — 2026-10-17

用户反馈浏览器下载后显示“已损坏”。实际检查原始 DMG 校验正确，但应用缺少完整资源签名，`codesign --verify --deep --strict` 失败。此前直接执行应用的验收未覆盖分发签名检查，这一遗漏不能由业务测试绿灯替代。

r2 改为完整 ad-hoc 签名，增加签名后应用检查、最终只读 DMG 中应用及原生资源检查；仍缺少 Developer ID 与公证，Gatekeeper 结果明确记录为拒绝，不再用“未测试”代替已经观察到的结果。下载与临时用户信任步骤见 [Mac 安装说明](MACOS_INSTALLATION.md)。下面保留原发布时记录。

# 0.7.0 公开发行记录 — 2026-10-17

本次按维护者要求发布正式 GitHub Release，公开已经验收的未发行签名安装包。GitHub 的非预发布状态与发行证书、Mac 公证及 Gatekeeper 验证分别记录；本次没有宣称签名发布门通过，也没有放宽 `release-packaging.yml` 或 `package:mac:release` 的证书检查。

- macOS arm64：应用、只读 DMG、凭据清理、业务与插件对话验收通过；无 Developer ID，未公证，Gatekeeper 默认打开体验未验证。
- Windows x64：GitHub 构建、实际安装、中文路径启动、迁移及包内 Python/TypeScript 插件验收通过；无 Authenticode 发行证书。
- Linux：源码 CI 通过，未提供或验收 Linux 安装包；Intel Mac 同样没有本轮安装包。

0.7.0 的来源、文件摘要和验收链接见[更新说明](RELEASE_0.7.0.md)。下文保留历史决策与旧版记录；签名、公证及签名验证后的自动更新目标仍未完成，历史的 PARTIAL 不被改写为签名发布就绪。

# 历史状态 — 2026-09-04 AUTH HOTFIX CANDIDATE

- Core RC: **RC_READY**; macOS public release: **PARTIAL** only because real
  Developer ID signing, notarization/stapling and Gatekeeper validation lack
  external credentials.
- Final unsigned macOS arm64 DMG: 180,747,880 bytes; SHA-256
  `fb9c3a247f9243fe27bafb728ef6892e4fe09f3ffaa328d9baa452e37ea479a5`.
- Final `.app` and readonly DMG smoke: 17/17 PASS; shared public-release smoke:
  19/19 PASS; real Keychain write/read/delete/final cleanup: PASS.
- Standalone frontend auth uses `/api/v2/auth/*`; blank-profile first-user
  registration/login and the workspace runtime-auth gate are verified.
- Next standalone browser JS/CSS is copied explicitly; both packaged-app and
  readonly-DMG smoke fetched all 11 page-referenced static assets successfully.
- Blank-profile production auth-on launch, no-API-key fallback 9/9, package
  surface deny scan, and frozen pre-RC → final RC upgrade all PASS.
- Windows x64 and Linux x64 remain **UNTESTED — NO TARGET MACHINE**. Their
  package configurations and adapters are not support claims.
- Distribution assembly is now allowlist-based; the historical full-source-tree
  package risk below is closed for this artifact. Embedding remains DEFERRED
  and no model weights are bundled.

# ADR: MathTutor 桌面发行版分发策略（安装包 / 签名 / 升级）

- 状态：**PARTIAL / IMPLEMENTED**（standalone macOS arm64 unsigned 公共 smoke 与升级证据，2026-08-28；签名、公证及 Windows/Linux 目标机验证未完成）
- 关联 ADR：`desktop/ADR-DESKTOP.md`（Accepted v0.3.0，桌面壳架构）、
  `docs/ADR_EMBEDDING_DISTRIBUTION.md`（不变式 G：Embedding 模型不进包）
- 目标读者：MAIN 协调 + 发行版实施轮次

> PARTIAL 的含义：electron-builder、内置 Python runtime、Next standalone、
> per-user data root 与真实 macOS DMG smoke 已落地；没有凭据或目标机的门禁
> 仍保持 UNTESTED，绝不由“配置存在”推导为已测试。

## 背景与现状事实（file:line / 实测）

- 桌面壳仅含 `desktop/main.js` 等壳代码：spawn 本地 Python 产品服务 + Next.js
  前端，业务逻辑全在 Python 侧（`desktop/ADR-DESKTOP.md` D1–D3，Accepted）。
- `desktop/electron-builder.config.cjs` 是当前单一打包配置；package scripts
  提供 macOS unsigned DMG、Windows NSIS、Linux AppImage。macOS 包内含目标机
  Python runtime、MathTutor 产品源码与 Next standalone，不要求用户配置 Python。
- API key 的运行时落点是 OS Keychain（`deeptutor/math_tutor/infrastructure/
  keychain_secret_store.py`，macOS `security` CLI，service `com.mathtutor.product`）
  ——安装包内**不存在也不允许存在**任何 key 注入通道。
- 开发/验证机为 macOS arm64（本机实测 Darwin 25.5.0）；Windows 与 Linux
  只有策略、没有本机实测。

## 硬约束（违反即否决）

1. **API key 永不进安装包**：不打进 installer、不写进 bundle 配置、不放进
   更新元数据；key 只允许用户在运行时通过 UI 写入 OS Keychain（或等效凭据存储）。
2. **不变量 G**：安装包不含 embedding 模型权重（分发策略 DEFERRED，
   见 `docs/ADR_EMBEDDING_DISTRIBUTION_DRAFT.md`）；无 backend 时产品按文档
   退化（词法检索），桌面发行版不改变这一契约。
3. 业务逻辑不进 Electron（ADR-DESKTOP D1 延续）；打包脚本只做装配，
   不改变产品行为。
4. 禁止把「未测平台」宣称为已支持——发布矩阵必须诚实标注
   TESTED / PARTIAL / UNTESTED。

## 决策矩阵（平台 → 格式 / 签名 / 工具）

| 平台 | 安装包格式 | 签名 / 公证 | 打包工具 | 状态 |
|------|-----------|-------------|----------|------|
| macOS (arm64 优先) | **dmg**（zip 备选） | Apple Developer ID Application 证书 + notarization + Hardened Runtime | electron-builder | **现在做**（唯一本机可验证平台） |
| Windows | **NSIS 安装器**（便携 zip 备选） | Authenticode 代码签名证书 | electron-builder | 策略已定，实施待 Windows CI/签名机 |
| Linux | **AppImage**（发行主力）+ **deb**（Debian/Ubuntu 系） | 无强制签名生态；随包分发 sha256 校验文件 | electron-builder | 策略已定，实施待 Linux CI |

选择依据：

- **electron-builder** 是三者中最主流且同时覆盖 dmg/NSIS/AppImage/deb 的单一
  配置源；electron-forge 需要更多插件装配，收益不增——选 builder。
- macOS **必须** dmg + 公证：未公证的应用在 Gatekeeper 下无法默认启动
  （右键打开绕行不适合 K12 用户）。签名+公证缺一不可，需要 Apple Developer
  计划（$99/年）——这是发行成本，不是可选项。
- Windows NSIS：K12 家庭用户熟悉的「下一步-安装」形态；便携 zip 作为
  低权限/学校机房场景的备选（不写注册表）。
- Linux AppImage：单文件、免 root、跨发行版，与「本地优先、拷贝即用」气质
  一致；deb 满足包管理器用户的更新习惯。

## 升级策略（诚实分阶段）

| 阶段 | 做法 | 依赖 | 状态 |
|------|------|------|------|
| 现在（MVP） | **手动替换**：新版本覆盖安装 / 重新下载 dmg，数据目录与库文件不动（数据在用户数据目录，不在应用目录） | 无 | 采用 |
| 后续 | **electron-updater 内置升级**：dmg/NSIS/AppImage 三平台 delta/全量下载 + sha512 校验 + 签名验证后再替换 | 签名证书齐备 + 更新服务器 | 推迟（PROPOSED，本轮不实现） |

内置升级的安全前提：更新元数据与包必须由签名链校验通过才可替换二进制；
更新通道**绝不携带 API key**。MVP 阶段宁可手动替换，也不做无签名校验的
自动更新。

## 发布流水线（建议，不实施）

1. 每条 tag 由 CI 产出三平台产物：`*.dmg`（已公证）、`*-Setup.exe`（已签名）、
   `*.AppImage` + `*.deb`，附各产物 sha256 文件。
2. macOS 公证走 `notarytool`；Windows 签名在持有证书的专用 runner 上执行
   （证书不进普通 CI 缓存）。
3. 发布清单（README/release note）明确写出「真实测试矩阵」——见下。
4. 桌面 smoke 验证继续以 `npm run smoke-full`（electron `--smoke-full`）为
   最低验收线，运行在**刚装好的干净机器**而非开发机。

## 真实测试矩阵（诚实声明：按本机实测能力标注）

| 平台 / 架构 | 壳运行 (spawn + 窗口) | 安装包安装 | 签名 / 公证 | 状态 |
|-------------|----------------------|------------|-------------|------|
| macOS arm64（开发机） | TESTED（packaged full smoke 17/17） | TESTED（DMG readonly mount + 卷内 launch） | UNTESTED（无证书） | **PARTIAL** |
| macOS x64 | UNTESTED | UNTESTED | UNTESTED | UNTESTED |
| Windows 10/11 x64 | UNTESTED | UNTESTED | UNTESTED | UNTESTED |
| Linux x64 (AppImage / deb) | UNTESTED | UNTESTED | — | UNTESTED |

> macOS arm64 的 unsigned 本地包已可运行；没有签名/公证证据，因此仍不得称为
> public-release ready。其他平台没有目标机证据，全部保持 UNTESTED。

## 风险与后续工作

- Apple/Windows 证书是年度费用与审核成本，需赛前规划（比赛演示可先用
  macOS 本机 + 右键打开或 ad-hoc 签名的开发场景，并在演示材料中如实标注）。
- electron-builder 已把目标 OS Python runtime + 产品源码 + Next standalone
  装入 `resources/`，用户不需预装 Python；完整 `deeptutor/` 源树带来的包体与
  静态攻击面债务见文末 Residual packaging risk。
- 数据目录（SQLite、uploads、备份、Keychain）独立于应用目录，升级/重装
  不触碰用户数据——此契约写入升级验收测试。

## 2026-08-24 实施记录（Pre-RC）

### PlatformMatrix

状态只来自目标机实测，不由静态配置推断。

| 平台 | BUILD | PACKAGE | SIGN | INSTALL | LAUNCH | SECRET STORE | BACKUP | RESTORE | UPDATE |
|---|---|---|---|---|---|---|---|---|---|
| macOS 26 arm64 | TESTED | TESTED（DMG） | UNTESTED / NEEDS CREDENTIAL | TESTED（DMG mount） | TESTED | TESTED（真实 Keychain random sentinel + cleanup） | TESTED | TESTED | PARTIAL（手动替换 contract） |
| macOS x64 | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED | UNTESTED |
| Windows 10/11 x64 | UNTESTED | UNTESTED（NSIS 配置已实现） | UNTESTED / NEEDS CREDENTIAL | UNTESTED | UNTESTED | UNTESTED（Credential Manager adapter 已有） | UNTESTED | UNTESTED | UNTESTED |
| Linux x64 | UNTESTED | UNTESTED（AppImage 配置已实现） | UNSUPPORTED（本轮无发行签名方案） | UNTESTED | UNTESTED | UNTESTED（secret-tool 缺失应 DEGRADED） | UNTESTED | UNTESTED | UNTESTED |

macOS 构建命令：`cd desktop && npm run package:mac:unsigned`；Windows 与 Linux
分别为 `npm run package:win` / `npm run package:linux`，必须在对应目标 OS 且
`MATHTUTOR_PYTHON_RUNTIME` 指向该 OS 可重定位 runtime 时执行。后两者只是已准备
命令，不是 TESTED。

### macOS unsigned package evidence

- artifact：`desktop/dist/MathTutor-0.2.0-mac-arm64.dmg`（272,838,049 bytes；约 260 MiB）
- sha256：`9cde02bd7f997438b854949e1b5c8d959b9d63b6947e18ac006da446c9718670`
- maintenance gate 最终源码重包后严格连续执行 runner 3 次；每次均为 production
  auth-on launch PASS、本地 `.app` full smoke 17/17、DMG readonly mount 卷内
  full smoke 17/17。此前 restore 偶发残留 active `-shm` 的根因已由全局
  maintenance admission/drain gate 修复；restore 在 verify/copy/migrate/rollback
  全程持有 gate，并配合强 WAL checkpoint、engine dispose 与 sidecar 清理。最终
  三连跑未再复现 flake。
- 覆盖：bootstrap、文档导入、memory CRUD、solve、attempt、practice offer、
  accept、child cycle、backup create/verify/restore、backend restart、durability。
- `desktop/dist/package-smoke-evidence.json` 为 schema v2 machine-readable evidence，
  以 `consecutive_runs=3` 保存三个独立结果而非覆盖最后一次：run 1 的
  production/app/DMG backend→frontend readiness 为 939→961 / 637→660 /
  2147→2171 ms；run 2 为 947→972 / 636→659 / 2165→2198 ms；run 3 为
  635→657 / 636→659 / 2162→2195 ms。每个观测仍是单次 n=1，不把这些值
  伪称为 p50/p95 分布。
  包内已静态确认 Alembic head migration
  `migrations/versions/006_evidence_identity.py` 与最终 schema 均存在。
- production profile 使用同一值同时设置 `AUTH_ENABLED` 与
  `DEEPTUTOR_AUTH_ENABLED`，实测首次注册 → 登录 → 受保护 readiness PASS；
  full smoke 使用 loopback-only OpenAI-compatible mock，显式 PUT settings、
  `/model/test`、gateway=`ok`、embedding=`degraded`，无外网且 test profile
  只使用 InMemorySecretStore。
- package runner 在 checkout 外 cwd 运行，白名单环境不继承 PYTHONPATH、conda
  或 virtualenv；关键模块 `product_app/schema/verifier_worker.__file__` 均实测
  位于 `.app/Contents/Resources/python-app`。bundle 过滤 `__pycache__`、pyc/pyo、
  deeptutor editable `.pth`、finder 与 `deeptutor-*.dist-info`；最终包内这些目标
  计数均为 0。关键共享文件 source→package sha256 一致：`product_app.py`
  `ac5cf7d1d3eb1655ff1111b056ec0ab335803d6bd72dc4d30abfa7496355e2d7`、
  `product_state.py` `7eeb99e1c9375d6640c75fbd86c1fb3270ea76114f4face1a029977825e386a5`、
  `desktop_api.py` `2197efe3558d1a8f2cf4306bb5ba728eb2db1aa2426377a8f3b31c64f9e8bdc8`。
- 这是 2026-08-24 pre-RC 的历史证据：当时 settings API 无 secret delete，
  production Keychain sentinel 因无法保证清理而标为 UNTESTED。该状态已由下文
  2026-08-26 的真实 adapter-level put/read/delete/finally-cleanup 证据取代。
- 本机 `security find-identity -v -p codesigning` 返回 `0 valid identities`；
  electron-builder 明确输出 skipped signing。因此 Developer ID、Hardened
  Runtime 签名结果、notarization、Gatekeeper 默认安装体验均 UNTESTED。

### Data root contract

Electron 使用 `app.getPath("userData")`（可由 `MATHTUTOR_DATA_ROOT` 显式覆盖），
而不是 source tree 或 `.app/Contents`。布局为：

- macOS：`~/Library/Application Support/MathTutor`
- Windows：`%APPDATA%\\MathTutor`
- Linux：`$XDG_CONFIG_HOME/MathTutor`，未设置时 `~/.config/MathTutor`

以上由 Electron 的 `userData` convention 解析，不在代码中手拼 HOME 路径。

| 数据 | 相对 userData | 说明 |
|---|---|---|
| SQLite/WAL | `math_tutor.db`（及 `-wal/-shm`） | 产品唯一事实源 |
| uploads | `uploads/` | 用户显式导入内容 |
| backups | `backups/` | DB + manifest |
| non-secret config | `config/`（gateway 既有配置当前仍由 backend 放在 data root） | 不得包含 API key |
| logs | `logs/` | 发行日志预留目录 |

API key 不属于 data root，只进入 OS credential store。Electron 在启动 backend
前建立目录并传入绝对 `MATHTUTOR_DB_PATH` / `DEEPTUTOR_HOME`；首次启动不要求用户
配置 SQLite、课程、检索、outbox、备份或内部服务。用户只配置 provider/API key，
Custom 模式才配置 Base URL/Model。

### Upgrade / migration / rollback contract

当前 UPDATE 为 PARTIAL（手动覆盖安装）：

1. 退出旧 app，确认 backend/worker 已停止；
2. 从旧版 UI 创建并 verify 一份备份，保留 manifest；
3. 替换 app，绝不删除或移动 userData；
4. 新版启动对现有 DB 执行既有 Alembic upgrade；
5. bootstrap/health 必须通过才继续使用。

迁移失败时停止新 app，保留失败现场，不反复启动；重新安装旧 app，并通过其
verified restore 恢复第 2 步备份。禁止把“安装旧二进制”当作数据库降级工具，
禁止直接复制活跃 WAL 数据库。当前尚未实现“版本变更时自动 pre-migration
backup”，所以升级门禁依赖上述显式 runbook；这是进入签名 RC 前的残余门禁。

### Backup scheduler OS integration

结论：**不接 launchd / Task Scheduler / user systemd timer**。产品已有一个随
backend 生命周期启动/有界停止的 `BackupScheduler`（manual/on_startup/interval）。
再加 OS scheduler 会形成两个不共享锁与 retention 时序的调度者，可能同刻重复
备份。发行默认继续 `manual`；若未来启用 `interval`，唯一调度所有权仍归产品
内部 scheduler。只有产品明确改成“短命令、无常驻 scheduler”的架构后才重审
OS scheduler，二者不得同时 enabled。

### Residual packaging risk（历史；已由 2026-08-26 allowlist 关闭）

为保证 Python import 闭包可靠，本轮包内仍携带完整 `deeptutor/` Python 源树，
而非仅 `deeptutor/math_tutor/`；产品 FastAPI route/capability allowlist 仍 default-
deny，Electron 不暴露通用 DeepTutor 入口，但额外代码增加包体与静态攻击面。
这不是新功能接线，后续应以 import-closure manifest 缩减并重新跑相同 17-step
packaged smoke。当前 DMG 可本地验证，但在此 debt 与签名/公证关闭前不应宣称
public-release ready。

## 2026-08-26 macOS Public Release Assurance（包面缩减前的历史证据）

### 当前 artifact 与升级基线

- 当时的 unsigned assurance artifact：`desktop/dist/MathTutor-0.2.0-mac-arm64.dmg`，
  272,845,178 bytes，sha256
  `788a3e042e5fccb3d6a335c7356f7f0d36749ef4f5156e49ed780954a89f58b2`。
- 升级验收所需的旧 pre-RC artifact 已在重包前冻结为
  `desktop/dist/pre-rc/MathTutor-0.2.0-pre-rc-9cde02bd.dmg`，272,838,049 bytes，
  sha256 `9cde02bd7f997438b854949e1b5c8d959b9d63b6947e18ac006da446c9718670`；
  新构建不会覆盖该路径。
- 最终 assurance build 的 production auth-on readiness、packaged `.app` full
  smoke 17/17、readonly DMG 卷内 full smoke 17/17 均 PASS；backend→frontend
  readiness 分别为 939→962、963→987、2164→2189 ms。统一 19 项
  `RC_PUBLIC_RELEASE_SMOKE` 由 MAIN 集成，本节不把现有 17 项误报为 19 项。

### Real macOS Keychain

`desktop/scripts/macos-keychain-sentinel.py` 使用包内 Python runtime 和包内生产
`KeychainSecretStore`，在真实 macOS Keychain 上完成随机 account/value 的
put → read → constant-time compare → delete → assert missing，并在 `finally` 再次
delete + assert missing。值在探针进程内生成，只经 stdin 进入 `security`，不进
argv、日志、普通配置或 evidence。最终 `cleanup_complete=true`；失败时也执行
finally cleanup。既有 fake-runner/unavailable/error 测试确认异常 fail closed，
不回退 plaintext；相关 Desktop bridge + lifecycle 回归 67 passed。

### Hardened Runtime 与签名边界

entitlements 已从三项缩减为仅
`com.apple.security.cs.allow-jit`（Electron/Chromium JIT）；已移除
`allow-unsigned-executable-memory` 与 `disable-library-validation`，且从未启用
`get-task-allow`。移除后当前 `.app` 与 DMG 卷内真实 packaged launch/full smoke
均 PASS。Next standalone 遗留但未使用的 broken rimraf symlink 已在装配时排除，
包内 broken symlink 计数为 0，避免 strict codesign 的结构性失败。

本机 `security find-identity -v -p codesigning` 为 `0 valid identities found`，
notary/CSC credential env 也不存在。一次临时 ad-hoc Hardened Runtime 探针能完成
`codesign --verify --deep --strict`，但 launch 被 dyld 拒绝：ad-hoc 签名没有
TeamIdentifier，不能证明 Developer ID 下的 library validation。该结果不是恢复
`disable-library-validation` 的理由，也不是公开签名 PASS。Developer ID enforced
launch、真实 sign、notarization、staple 与 Gatekeeper drag-install/first-launch
全部保持 `UNTESTED: MISSING_EXTERNAL_CREDENTIAL`。

公开构建入口 `npm run package:mac:release` 要求显式 `CSC_NAME`；
`scripts/after-pack-macos.cjs` 在 Electron 顶层签名前枚举、签署并严格验证
Resources 内所有 Mach-O，随后由 electron-builder 签 Electron Framework、helpers
与顶层 app。公开构建脚本要求 notary credential 使用 Keychain profile，不把密码
写入 argv/log；真实 Developer ID operator runbook 仍须在取得凭据时按该边界执行。

### Supply chain、SBOM 与 release logs

`desktop/dist/release-manifest/macos-release-manifest.json` 是当前 machine-readable
macOS release manifest，记录 version/artifact/hash/platform/arch/runtime/migration、
sign/notary/Gatekeeper/smoke/embedding/source revision 状态；当前 standalone
初始冻结提交已解析为 `8df190251c26074da3bb48519a2ac079a5ab3159`，tracked
工作树为 clean。它引用并校验以下本地 inventory：

- package contents：8,833 regular files + 1,179 symlinks，逐项 size/mode/sha256；
- Python runtime：43 distributions；packaged Node runtime：21 packages；build
  Node inventory：311 packages；
- third-party license inventory：109 files；
- native binary inventory：161 Mach-O files。

最终 runner 对 Keychain、production bootstrap、app full smoke、DMG full smoke 的
输出执行禁止项检查，`release_log_audit=PASS`，未见 Authorization/Bearer、测试文档
raw text、Personal Memory value、hidden reasoning 或 attestation payload。DMG 没有
传统 installer log，清单如实记录 `NOT_APPLICABLE_DMG_NO_INSTALLER_LOG`；builder
日志同样不含 credential value。连续构建的二进制 hash 可因 DMG timestamp/布局变化，
不宣称 bit-reproducible；相同 version、migration 006、package policy、Keychain
cleanup 与 smoke behavior 已复现一致。

## 2026-09-04 Standalone auth hotfix 最终证据

### 最终 artifact 与自包含性

- `desktop/dist/MathTutor-0.2.0-mac-arm64.dmg`：180,747,880 bytes，
  SHA-256 `fb9c3a247f9243fe27bafb728ef6892e4fe09f3ffaa328d9baa452e37ea479a5`。
- 空白临时 user-data root、checkout 外 cwd、白名单环境下，production
  auth-on 首次注册/登录/readiness PASS；包内 `.app` 与 readonly DMG
  均 17/17 PASS。统一 `RC_PUBLIC_RELEASE_SMOKE` 19/19 PASS。
- 包内 `product_app`/schema/verifier worker 均从
  `Contents/Resources/python-app` 加载；无 editable `.pth`/finder/dist-info
  或 checkout 绝对路径回流。
- 两次同 source state 构建均通过 19/19 public smoke、9/9 no-key、
  pre-RC upgrade 与 package-surface gate。DMG 因 timestamp/layout 哈希不同，
  但 version、migration 006、allowlist policy 与行为一致。

### Package surface 与供应链

`desktop/package_allowlist.json` 执行 default-deny 源码装配。最终 artifact 的
产品 Python 顶层只有 `mathtutor`，`*deeptutor*` 路径为 0；readonly DMG 记录
8,833 个普通文件、1,179 个 symlink 和 480,140,750 file bytes。相对拆分前
package-surface baseline 减少 13,080 个普通文件和 92,382,483 artifact bytes。
generic chat/research/math animator/subagent/MCP/tools 等产品面不在独立源码或
可达路由中；第三方 framework closure 的内部同名文件不等于产品能力。

最终 inventory 记录 43 个 Python distributions、21 个 packaged Node packages、
311 个 build Node packages、109 个 license files 和 161 个 Mach-O files。
ReleaseConfig 随清单固定 app/schema/
migration/curriculum/verifier/estimator/parser/chunker/retrieval/release-policy
版本。Embedding 为 `DEFERRED`，没有模型权重进包。

### 升级、卸载与用户配置

真实 readonly DMG 升级路径为：冻结 pre-RC artifact 创建用户档案和
verified backup → 最终 RC 运行 migration 006/bootstrap → 文档、Personal
Memory、父子 cycle、offer/release exact snapshot 和 backup 仍有效 →
StudentState 持久化投影与 evidence replay 一致。全部 PASS。迁移失败
时保留 verified backup 和旧 artifact，不对数据库做逆向 migration。

卸载应用只删除 app/installer 文件，默认保留 user-data root 中的
SQLite、documents、backups 和 Personal Memory；OS credential 也保留。
未来若加入“Delete my data”，必须显式列出删除范围并二次确认。
本轮没有执行完整 installer uninstall，因此矩阵仍记 `UNTESTED`。

首次使用的普通配置只显示 Provider + API Key；Custom 模式才显示
Base URL + Model + API Key。Key 只写入 OS credential store，非密密配置
可写入 data root。SQLite、worker、outbox、embedding、vector DB、reranker
和 backup 内部均不出现在首次配置中。无 API Key 时 9/9 核心
退化检查 PASS：产品为 `DEGRADED`而非 `BLOCKED`，确定性数学、
Student Model、bank/template practice 和 lexical retrieval 仍可用。
