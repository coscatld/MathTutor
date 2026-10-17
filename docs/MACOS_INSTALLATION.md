# macOS 安装与首次打开

适用于 Apple Silicon（M 系列芯片）Mac。请从 [0.7.0 发布页](https://github.com/coscatld/MathTutor/releases/tag/v0.7.0)下载 `MathTutor-0.7.0-mac-arm64-r3.dmg`。r3 是 Mac 打包修订，应用版本仍为 0.7.0。

## 为什么旧包显示“已损坏”

原始 `MathTutor-0.7.0-mac-arm64.dmg` 的磁盘镜像 CRC 和 SHA-256 正确，但应用只有 Electron 可执行文件遗留的 linker ad-hoc 签名，没有完整资源封印。实际检查报 `code has no resources but signature indicates they must be present`。此前直接执行应用的业务测试没有发现这一分发缺陷。原始包已标记为撤回使用，请重新下载 r3。

r3 延续完整签名并修复普通数学提问失败的问题，对随附 Python、原生模块及 Electron 应用由内向外签名，并检查最终只读 DMG 内的应用与原生文件。签名完整性通过不等于苹果认证：目前没有 Developer ID 证书和公证凭据，Gatekeeper 的默认分发评估仍拒绝此本地 ad-hoc 签名包。

## 安装

1. 下载 r3 DMG，按发布页 `SHA256SUMS-0.7.0-mac-r3.txt` 核对文件。
2. 打开 DMG，把 `MathTutor.app` 拖入“应用程序”。替换旧应用前退出它；不用删除学习数据。
3. 双击应用。如果系统阻止，在“系统设置 → 隐私与安全性”查看是否提供“仍要打开”，由你确认允许。

系统未提供允许按钮时，只有在你核对了下载摘要、信任本项目代码的前提下，才使用下面的单应用处理。它移除 **MathTutor 这一个应用**的下载隔离属性，不关闭系统 Gatekeeper，不修复其他来源的损坏软件：

```sh
# 先核对 DMG，结果必须与发布页 r3 校验文件一致。
shasum -a 256 "$HOME/Downloads/MathTutor-0.7.0-mac-arm64-r3.dmg"
# 安装后验证资源签名；此命令失败时停止，不执行后面的命令。
codesign --verify --deep --strict --verbose=2 /Applications/MathTutor.app
```

前述验证通过并决定信任后，单独执行：

```sh
xattr -dr com.apple.quarantine /Applications/MathTutor.app
open /Applications/MathTutor.app
```

这些是用户明确接受未公证软件后的临时步骤。要让浏览器下载的新包默认通过 macOS 分发检查，维护者仍须配置 **Developer ID Application 签名、Apple 公证与 stapling**，并实际通过 Gatekeeper；不能用删除隔离属性的测试宣称这一门禁通过。参考 [Apple：安全打开 Mac App](https://support.apple.com/en-ie/102445)与 [Apple：分发前公证 macOS 软件](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)。

## 维护者检查

```sh
npm --prefix desktop run package:mac:unsigned
node desktop/scripts/verify-macos-dmg.cjs desktop/dist/MathTutor-0.7.0-mac-arm64.dmg
node desktop/scripts/run-macos-sealed-startup.cjs desktop/dist/mac-arm64/MathTutor.app desktop/dist/sealed-startup-macos.json
```

`package:mac:unsigned` 保留旧命令名，表示无发行证书；现在明确启用完整 ad-hoc 签名，不再跳过签名。签名完整性失败会使打包失败；旁边的 `.signature.json` 分别记录镜像完整性、应用签名和 Gatekeeper 的真实结果。`package:mac:release` 仍要求发行证书，拒绝 ad-hoc 替代，并要求最终 DMG 通过 Gatekeeper。

可写副本验收在临时中文目录中启动应用、经 LaunchServices 打开并访问页面，每个阶段后重新验签，防止 Python 字节码或前端缓存破坏资源封印；不会操作用户已安装的应用。该检查已加入签名发行工作流。它对临时副本执行的手动信任步骤单独记录，不能替代默认 Gatekeeper 放行。
