# Python 与 TypeScript 代码插件

将 `double.py` 或 `double-ts.ts` 在社区“我的插件”中导入，阅读本地代码权限并确认信任后启用。在对话里输入 `/double 21` 或 `/double-ts 21`，插件实际计算 42，再由当前模型组织回答。

这两个文件使用标准库和语言内置功能，不需要安装第三方依赖，不调用模型或网络。Python 提供 `run(request: dict)`；TypeScript 导出 `run(request)`，可返回 Promise。输入只有本次命令后的文字和插件配置，输出为有限 JSON 数据。

单文件示例可直接导入；多文件插件的清单、打包、更新和调试步骤见[代码插件开发说明](../../docs/CODE_PLUGINS.md)。代码按本机账户权限运行，运行时限和文件类型检查不构成操作系统沙盒。
