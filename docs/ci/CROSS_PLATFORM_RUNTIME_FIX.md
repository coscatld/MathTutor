# Cross-platform verification：源码契约与打包环境拆分

## 根因与原执行时机

`desktop/tests/distribution.test.js`、`package-surface.test.js`、`platform-release.test.js` 都在顶层导入 `electron-builder.config.cjs`。原配置在构造 `extraResources` 的 `from: pythonRuntime()` 时立即查找环境，先尝试 MATHTUTOR_PYTHON_RUNTIME，再尝试 .venv / CONDA_PREFIX。三个文件因此在测试注册前同时失败；并不是三个独立功能回归。

配置原本还在 import 时检查 Next standalone/server.js 和 static。它们同样属于打包前置条件，而非静态配置导入前置条件。

## 修复后的边界

- 配置仅声明平台目标、产物命名、资源目的地及过滤规则。Python 的静态 `from` 为明确的未解析占位路径，不是 hosted Python，也不会作为成功打包的替代资源。
- `packaging-prerequisites.cjs` 导出 `resolvePythonRuntime()` / `resolvePackagingPrerequisites()`；显式调用即进行严格验证。没有环境变量就抛错，没有 .venv / CONDA_PREFIX 后备路径。
- `before-pack.cjs` 是配置中的正式 beforePack hook。electron-builder 在计算 extraResourceMatchers / 复制资源之前调用它；先核对构建目标 OS/arch 与宿主匹配，再解析资源、做真实 runtime 重定位探测，最后才写入经过检查的 Python resource.from。
- 直接执行 electron-builder、`test:package`、现有 macOS/Windows/Linux 打包脚本都会经过同一个 hook。缺 runtime、路径无效、目录不是 runtime、venv、hosted tool cache、包外/绝对符号链接、错误 OS/arch、缺 stdlib/dependencies 或缺前端构建产物，均不能通过正式打包。
- 结构检查不冒充可分发性证明：`verify-distribution-runtime.cjs` 将 runtime 完整复制到临时目录，在清除 Python/Conda 环境的上下文中执行 `-I -B` 探测，验证 sys.prefix、目标 OS/arch、Python 版本和依赖来源。结构 fixture 可以通过结构测试，但伪造 executable 无法通过真实分发测试。

## CI 职责

| 命令 | 目的 | 缺少 target runtime |
|---|---|---|
| `npm run test:contracts` | runtime path、平台配置、产物命名、资源/源码表面契约和前置检查单元测试 | PASS；不要求构建前端或真实 runtime |
| `npm run test:distribution` | 先执行真实 runtime 重定位/隔离导入探测，再运行契约测试 | FAIL，不会变成 PASS 或仅跳过 |
| `npm run test:package` | 真正调用 electron-builder `--dir` 生成应用目录 | FAIL；同样经过 beforePack |
| `python scripts/check.py` | Python tests → Web tests → Next build → desktop contracts | 源码检查通过后，明确报告 Distribution SKIPPED / NOT APPLICABLE |

check.py 在 MATHTUTOR_PYTHON_RUNTIME 已显式设置时追加 distribution 验证；无效路径导致 check.py 失败。未准备 runtime 时输出并写入 GitHub Step Summary：

```text
Distribution: SKIPPED / NOT APPLICABLE — target packaging runtime not provisioned
```

已有的两个最终 artifact 检查在没有 MATHTUTOR_PACKAGE_APP 时仍标记 skip，它们不是目标机验证的 PASS。源码 CI 的 actions/setup-python 只负责构建和测试。

## Release workflow 与 runtime 提供者

新增手动触发的 `.github/workflows/release-packaging.yml`：

1. macOS arm64 runner：发布维护者提供独立可重定位 CPython install-only 归档 URL 和独立核对的 SHA256；准备脚本校验摘要、检查平台、用归档内解释器安装依赖。setup-python 仅运行准备脚本，不会被复制为运行时。
2. Windows x64 runner：沿用带 SHA256 校验的官方 embeddable CPython 准备脚本；hosted Python 仅将依赖安装到独立 runtime 目录。
3. CI 将准备好的 `.runtime/<target>` 写入 MATHTUTOR_PYTHON_RUNTIME → test:distribution → package。禁止跨 OS/架构打包；不能拿 Linux Python 代替 macOS/Windows。
4. 公开 macOS 构建仍调用 `package:mac:release`，保留 CSC_NAME 签名门；workflow 从仓库 secrets 读取证书配置。Windows 公开构建也要求证书。没有自动上传 GitHub Release，也未宣称公证已完成。

macOS job 使用 `macos-15` arm64 标签，依据 [GitHub hosted runners 官方说明](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)。发布者需配置 macOS 归档输入、MACOS_CSC_NAME / MACOS_CSC_LINK / MACOS_CSC_KEY_PASSWORD 和 Windows 证书 secrets；缺输入或证书不会自动改用 hosted Python 或 unsigned 公共构建。

## 版本核对

以 pyproject.toml 的 project.version 为项目版本核对基准；release_config 定义后端公开版本，两个 package.json 定义 Web/Desktop 包版本。新增版本一致性测试覆盖它们、两个 lockfile 的顶层和根包版本，以及 NEXT_PUBLIC_APP_VERSION。

本轮开始时工作区/暂存区这些声明均为 **0.2.3**；`git show HEAD` 中 Python/Web/Desktop 仍为 **0.2.2**。CI 打印 0.2.2 与旧 HEAD 一致，而不是工作区各组件互相漂移。本轮保留已有暂存版本修改，没有重新升版，也没有代替用户提交或推送。

## 修改文件

- `desktop/electron-builder.config.cjs`：静态配置与 beforePack 入口。
- `desktop/scripts/packaging-prerequisites.cjs`：严格显式解析。
- `desktop/scripts/before-pack.cjs`：实际打包门及资源注入。
- `desktop/scripts/verify-distribution-runtime.cjs`：真实 runtime 重定位验证。
- `desktop/scripts/prepare-macos-python-runtime.py`：独立 macOS runtime 准备。
- `desktop/scripts/build-windows.ps1`：打包前运行分发验证。
- `desktop/package.json`：contracts/distribution/package 分工。
- `scripts/check.py`、`.github/workflows/cross-platform.yml`：源码 CI 与显式 skip。
- `.github/workflows/release-packaging.yml`：准备目标 runtime 的 release pipeline。
- `desktop/tests/packaging-prerequisites.test.js`、`tests/test_check_pipeline.py`、`tests/test_version_alignment.py`：回归覆盖。

## 验证范围

最终无 runtime 完整源码验证：Python **666 passed / 4 skipped**；Web **96 passed**；Next production build **PASS**；Desktop contracts **43 passed / 2 skipped**；Distribution 明确 **SKIPPED / NOT APPLICABLE**。前置检查新增 **10/10** 测试通过。

本地验证了无 runtime 的完整 check.py、真实 macOS runtime 的分发探测，以及 electron-builder 缺 runtime/无效 runtime 硬失败和提供真实 runtime 后实际构建成功。单元测试覆盖无前端产物时 import、三个平台结构 fixture、macOS/Windows 路径、hosted Python/venv 拒绝、伪 executable 拒绝、源码 CI skip 及配置无效时的失败传播。

真实构建产物输出到 `/tmp/mathtutor-ci-valid-runtime`，没有替换此前交付的 0.2.3 DMG。Windows/Linux 目标路径的 PASS 是契约验证，不能解释为本机已完成 Windows/Linux 安装或发布。新 GitHub workflow 尚未远程执行；没有调用真实签名/公证服务。

## Warning debt

现有 pytest asyncio mark misuse 和 FastAPI on_event/lifespan deprecation 与本次异常无因果关系，本轮未扩展修改这些 warning。其余既存依赖/测试警告也保留，不以警告数作为本轮成功或失败的依据。
