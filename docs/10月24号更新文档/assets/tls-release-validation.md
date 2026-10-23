# 社区资源 TLS 测试发布前复核

时间：2026-10-24 01:03（Asia/Shanghai）。范围：修复测试替身的标准库兼容性；生产 TLS 实现未修改。

## 问题与证据

原 `test_tls_uses_the_original_hostname_with_public_pinned_socket` 先检查真实默认 `SSLContext` 的验证设置，随后将 `ssl.create_default_context` 替换成只实现 `wrap_socket` 的自定义 `Context`。实际传入 `http.client.HTTPSConnection` 的已不是被检查过的上下文。

本机 Python 3.11.15 的 `http/client.py:1469` 会读取 `context.verify_mode`，之后读取 `context.check_hostname`。简化替身不具备这些属性，连接初始化即触发 `AttributeError: 'Context' object has no attribute 'verify_mode'`，尚未验证目标 TLS 调用链。

修改前整文件真实结果：**1 failed, 35 passed in 0.22s**。

## 修改

代码变更仅位于 `tests/test_community_fetch.py`：

- 使用真实 `ssl.create_default_context()` 返回的 `SSLContext`，仅 monkeypatch 该实例的 `wrap_socket` 来记录调用，工厂返回同一个上下文。
- 在包装 socket 的实际调用处断言 `verify_mode == ssl.CERT_REQUIRED` 和 `check_hostname is True`，并确认连接持有的上下文就是该实例。
- 保留原域名 SNI、已校验的固定 IP/端口及原始 socket 身份断言，增加超时参数断言。
- 对接受和拒绝证书两个分支参数化：拒绝分支注入 `SSLCertVerificationError`，验证原异常透传、原始 socket 被关闭且没有建立连接；成功分支验证 socket 被赋给连接且未提前关闭。

未修改 `src/mathtutor/application/community_fetch.py`，未关闭证书验证或域名检查，未放宽网络目标及代理限制。

## 运行命令与真实结果

运行目录：MathTutor 仓库根目录。

```bash
PYTHONPATH=src <USER_HOME>/miniconda3/envs/deeptutor/bin/python -m pytest \
  tests/test_community_fetch.py -q --tb=short
git diff --check -- tests/test_community_fetch.py
```

修改后：**37 passed in 0.20s**，无跳过项；`git diff --check` 通过。

执行环境：Python 3.11.15、macOS 26.6.2 arm64、OpenSSL 3.5.7。

## Python 3.12 与验证边界

已检查 PATH、当前 Conda 各环境、系统 Framework、常见 Homebrew/uv/pyenv 路径及项目 `.runtime`，未找到 Python 3.12，因此 **Python 3.12 未实测**；未安装新解释器或依赖。

已只读核对 [CPython v3.12.0 的 HTTPSConnection 源码](https://github.com/python/cpython/blob/v3.12.0/Lib/http/client.py#L1313)：构造函数接受并保存传入的 `context`，连接时使用其 `wrap_socket`。新的真实上下文测试方式符合该接口；这是源码兼容性检查，不能代替 Python 3.12 的实际回归结果。

测试以 socket/握手替身验证安全配置和调用、失败处理，不进行公网证书握手。该结果不代表安装包、部署环境或跨平台发布已验收。
