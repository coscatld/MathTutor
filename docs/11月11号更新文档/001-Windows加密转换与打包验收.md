# Windows 加密转换与打包验收

日期：2026-11-11，Asia/Shanghai。

继续完成桌面打包、提交和 CI 检查时，发现此前提交 `e96acef895363d42b06f14474b1e6bb72775a44c` 的 Windows 源码测试失败。macOS 与 Linux 源码检查、Mac 安装包检查和 Windows 安装启动检查已通过；这些检查的覆盖范围不同，安装启动通过不能替代加密切换测试。

## 修复

加密转换在发布新数据库前调用 `_sync_file`，但原实现以 `rb` 打开文件。Windows 的文件同步要求可写句柄，CI 在该处返回 `OSError: [Errno 9] Bad file descriptor`，导致加密、解密及相关恢复测试失败。

文件现在以 `r+b` 打开：保留既有内容，不创建缺失文件，不截断数据库，再执行 `fsync`。同步错误仍向调用者传播，转换不会跳过持久化检查后继续发布。数据库转换和迁移仍在原有写锁内完成。

新增双向恢复用例，分别在加密和解密前注入源文件同步失败，检查原数据库字节与待转换标记完全保留、没有发布转换日志或临时转换文件；解除故障后，原请求可以完成转换，记录内容与 migration head 保持完整。

## 验证

- 本地运行加密、故障恢复、启动迁移和未见练习四组测试：**72 通过**，127 条已有警告，12.76 秒。环境为 macOS arm64 / Python 3.11.17 / SQLCipher SQLite 3.53.4。
- Windows CI 增加加密转换及进程中断恢复的前置检查，随后仍运行完整后端、Web、生产构建和桌面契约。
- 导致本次修复的原始运行：[三平台 CI](https://github.com/coscatld/MathTutor/actions/runs/41265849884)。失败记录为 Windows 27 项失败、1 项 setup 错误；不能记为通过。
- 重新打包与源码 CI 均绑定修复后的提交。最终状态以对应提交的 [三平台运行](https://github.com/coscatld/MathTutor/actions/workflows/cross-platform.yml) 和 [Windows 安装包运行](https://github.com/coscatld/MathTutor/actions/workflows/windows-installer.yml) 为准，安装包旁保存校验值与验收记录。

本轮测试使用临时数据库与合成密钥，不访问用户学习库。README 按功能、下载和近期改进组织，发行元数据保留在构建文件中。
