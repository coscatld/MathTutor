# 二次函数顶点 Python 插件示例

输入 `/vertex a b c`，对 `y=ax²+bx+c` 计算顶点 `(h,k)` 与判别式 `Δ=b²-4ac`。仅接受整数系数、`a≠0`，并限制绝对值不超过 1000，使用 `fractions.Fraction` 返回精确分数。

在仓库根目录执行：

```bash
python examples/code-plugins/build_bundle.py \
  examples/code-plugins/quadratic-vertex \
  --include README.md \
  --output /tmp/quadratic-vertex-1.0.0.zip
```

将 ZIP 导入“社区 → 我的插件”，读明权限并明确同意本地代码执行后启用，输入 `/vertex 1 -4 3`，预期顶点 `(2,-1)`、判别式 `4`。

**警告：代码插件不是 OS 沙盒。** 即使本示例不访问网络或文件，也不要运行未知作者的代码。
