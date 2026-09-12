# 聊天图片附件交付报告

日期：2026-09-12。基于 0.3.0 源码实现，随后纳入 [0.3.1 构建与发布](releases/0.3.1.md)。下方验证记录对应功能实现阶段，最新包内验证见发布记录。

## Architecture

截图粘贴、文件选择与拖拽统一进入 `useChatAttachments.addFiles` →
`AttachmentStore` 验证类型/大小/数量 → File + ObjectURL 本地预览 →
发送时检查当前模型能力 → 本地图片接口保存 Blob → WS 同一消息提交 text + attachment_ids →
后端验证附件所属用户、当前模型能力和会话绑定 → 当前 Gateway/Provider 接收真实图片内容 →
原有回复生命周期、消息历史与 Markdown 展示。

- PNG/JPEG/WebP，单张最多 10 MiB，每条最多 4 张；前后端都校验。
- 普通文本粘贴保持浏览器默认行为；混合文字与图片粘贴添加附件并保留默认文字插入。
- 文件选择、粘贴、拖拽共用一个附件 Store，快速重复粘贴也不能越过数量上限。
- 预览在 textarea 上方，空附件不占高度；缩略图保持比例，支持删除及原生 dialog 放大、Esc 关闭。
- 只有图片也可发送；无文字、无图片不发送。
- 上传或模型失败时保留文字与附件，可重试；同一图片请求失败重试保持请求 ID，后端不重复写入用户消息。
- 收到成功终态后清空输入并释放 ObjectURL；移除与卸载也释放临时 URL。
- 图片讨论走视觉表达分支，不进入数学 ambiguity parser，不把图片直接记作已验证作答或掌握证据。
- 普通图片追问及“继续”会重新附带最近图片消息的图片；新结构化数学题保持原有解析链。

## Provider Changes

沿用现有 Chat Completions 客户端、Key 解析、Base URL、Model、timeout、错误处理和 Tutor 请求预算。
现有上游客户端使用非流式完成，前端仍经现有 WS 结果/部分结果机制接收；本次没有另建一套客户端或伪装增量 token 流。

OpenAI 已确认模型清单：GPT-4o、GPT-4o-mini、GPT-4.1、GPT-4.1-mini、GPT-4.1-nano 及日期快照形式。
`openai_vision_model` 根据 Provider 与 Model 一起判断；其他 OpenAI 模型及第三方别名需补充确认后纳入。
DeepSeek、Moonshot 和 Custom 当前未确认视觉能力，返回 false，不通过模型名字猜测或自动 OCR。
Ollama 使用 `/api/show` 返回的 `capabilities` 判断是否含 `vision`；离线或能力不明返回 false。

OpenAI 使用实际 Chat Completions 格式：

```json
{
  "role": "user",
  "content": [
    {"type": "text", "text": "这道题我为什么做错了？"},
    {"type": "image_url", "image_url": {"url": "data:image/png;base64,...", "detail": "auto"}}
  ]
}
```

Ollama Adapter 转为原生 `content: text` 与 `images: [base64]`，不要求 Key。
Gateway 在最终调用前再次检查视觉能力，模型切换不能绕过能力校验。
图片在请求预算中单独预留估算值，不把几 MB Base64 当作文本 token；该预算值不是精确视觉计费估算。
图片模型异常会返回明确错误，不使用文字模板冒充已看图。

依据：[OpenAI 图片输入指南](https://developers.openai.com/api/docs/guides/images-vision)、
[GPT-4.1 模型能力](https://developers.openai.com/api/docs/models/gpt-4.1)、
[Ollama Chat API](https://docs.ollama.com/api/chat)。

## Persistence

- 草稿：内存中的 File + ObjectURL，不写 localStorage。未发送草稿刷新后不保留。
- 发送时：`ImageUploadRepository` 把图片交给本机后端；返回的 MessageAttachment 不含 File、Base64 或磁盘路径。
- 长期存储：应用当前 SQLite 数据库的 `image_attachments` BLOB 表；消息 `conversation_messages.attachments` JSON 字段仅保存附件元数据与本地引用。
- 桌面数据库通常位于应用用户数据目录 `~/Library/Application Support/MathTutor/`；实际位置沿用现有 `MATHTUTOR_DB_PATH` / runtime 配置。
- 新增 migration 015；启动升级前使用现有备份机制备份旧库，旧消息附件默认空数组。
- 已发送图片支持刷新与应用重启后恢复，数据库备份包含图片。
- GET/DELETE 图片接口使用与其他资料相同的用户身份依赖；其他用户不能读取或删除图片。
- 读取使用 `private, no-store` 和 `nosniff`；禁止远程 URL/文件路径注入，后端检查 MIME 与容器签名。
- 本地保存并不表示云端永远看不到图片：点击发送时，图片才会交给用户选择的视觉模型；选择 Ollama 时进入本地服务。

## Modified Files

| 文件 | 修改职责 |
|---|---|
| `web/features/math-tutor/components/ChatComposer.tsx` | 统一附件区、上传、拖入提示、重试与成功清空 |
| `web/features/math-tutor/components/MathTutorPage.tsx` | 接入异步 text + attachments 发送 |
| `web/features/math-tutor/components/TutorActionCard.tsx` | 用户消息展示可放大图片，保留 Markdown |
| `web/features/math-tutor/hooks/useMathTutorSession.ts` | 上传仓库、WS 图片引用、完成确认及图片重试 ID |
| `web/features/math-tutor/lib/protocol.ts` | 允许附件 ID 数组消息字段 |
| `web/features/math-tutor/lib/reducer.ts` | 乐观图片展示、图片-only 历史恢复及安全投影 |
| `web/features/math-tutor/types.ts` | 消息附件与协议类型 |
| `src/mathtutor/api/math_tutor_ws.py` | 校验图片归属/能力、保存附件、失败请求恢复 |
| `src/mathtutor/api/product_app.py` | 挂载图片接口 |
| `src/mathtutor/api/product_state.py` | 初始化独立图片仓库并注入 Controller |
| `src/mathtutor/application/controller.py` | 图片表达路由、会话绑定、图片追问上下文 |
| `src/mathtutor/application/data_lifecycle.py` | 明确图片表的用户内容分类 |
| `src/mathtutor/application/tutor_runtime.py` | 多模态预算与 continuation 兼容 |
| `src/mathtutor/infrastructure/generative_gateway.py` | Provider 视觉能力、Ollama 消息适配、最终能力门 |
| `src/mathtutor/infrastructure/migrate.py` | 当前迁移版本更新为 015 |
| `src/mathtutor/infrastructure/schema.py` | 图片 Blob 表与消息 JSON 引用 |
| `src/mathtutor/infrastructure/tutor_chat.py` | 真实图片 content、视觉教学提示及失败不降级冒充 |
| `src/mathtutor/repositories/conversation_repository.py` | 内存/SQLite 附件持久化、图片-only 标题 |
| `src/mathtutor/security/allowlist.py` | 附件 payload 类型与数量边界 |
| `tests/test_architecture_debt.py` | 新迁移版本回归 |
| `tests/test_phase6_data_lifecycle.py` | 43 张表分类与 015 迁移清单 |
| `tests/test_product_app.py` | 明确四个新增接口的路由清单 |
| `tests/test_release_config.py` | 015 版本契约 |
| `tests/test_tutor_p0.py` | 旧库升级保留历史断言 |
| `desktop/main.js` | 下一次打包自检要求 migration 015 |
| `desktop/scripts/macos-upgrade-probe.py` | 下一次升级检查要求 015 |
| `desktop/scripts/run-packaged-smoke.js` | 下一次包内检查要求图片迁移文件 |

## New Files

| 文件 | 用途 |
|---|---|
| `web/features/math-tutor/lib/attachments.ts` | 附件类型、共享 Store、验证、粘贴处理、发送成功边界、本地上传接口 |
| `web/features/math-tutor/hooks/useChatAttachments.ts` | 接入 React 的三个入口及 URL 生命周期 |
| `web/features/math-tutor/components/ImageAttachments.tsx` | 可复用缩略图、删除、放大 dialog |
| `web/tests/math-tutor-attachments.test.tsx` | 16 项附件、发送与历史测试 |
| `src/mathtutor/api/image_api.py` | 图片能力、上传、读取、删除接口 |
| `src/mathtutor/repositories/image_repository.py` | 内存/SQLite 图片 Blob 存储接口 |
| `src/mathtutor/infrastructure/vision.py` | 保守能力规则、OpenAI/Ollama 格式、图片预算 |
| `src/mathtutor/infrastructure/migrations/versions/015_image_attachments.py` | 图片存储迁移 |
| `tests/test_image_attachments.py` | 17 项实际 API、Provider、历史恢复与安全测试 |
| `docs/chat-image-attachments.md` | 本交付报告 |

## Validation

- Python 全量：`pytest tests desktop/tests -q --disable-warnings --tb=short`：1022 通过、4 跳过，92.76 秒。
- 四项跳过均因 `/tmp/sqlite_vec_probe` 缺少测试专用 dylib；无新增失败。
- Web：`npm test`：145 通过（原 129 + 新 16）。
- Web 生产构建：通过编译、TypeScript、11 个静态页。
- Desktop 契约测试：44 通过、2 跳过；两项产物检查需要新安装包及 `MATHTUTOR_PACKAGE_APP`，本轮未重新打包。
- 新后端 17 项：真实上传、文字+图片、仅图片、原始图片字节到既有 Provider、持久化与重启、失败后保留/重试去重、用户隔离、格式/大小/数量、Ollama 原生图片、Base64 预算。
- 新前端 16 项：Clipboard/File 模拟、普通/混合粘贴、三种入口绑定、类型/大小/数量、释放 URL、发送成败、仅图片、历史格式与模型能力拦截。
- 实际浏览器：Cmd+V 产生预览；连续粘贴第五张被拒绝；删除保留文字；点击放大与 Esc 关闭；文件选择加入项目 logo；无视觉模型明确提示并保留文字和图片。
- 实际浏览器 + 可控 Provider：四图与文字同条发送，成功后清空；刷新恢复四图和文字；继续追问再次携带四张图片。测试 Provider 两次确认收到 4 张图片，未使用真实 API Key。
- 浏览器测试使用隔离目录 `/tmp/mathtutor-image-ui.4UOkwB`，没有修改真实用户数据。测试页面已关闭。
- `git diff --check` 通过。

## Remaining Issues / 验收边界

1. 真实云端视觉模型的识题质量尚未在线验收；协议传输已用可控 Provider 检查原始字节。
2. Windows Ctrl+V 使用同一 ClipboardEvent 路径且通过模拟测试；当前主机是 macOS，未做 Windows 实机验收。
3. 未确认的模型、第三方兼容模型别名默认拒绝图片；后续需按实际 Provider 能力补充，不自动冒充支持。
4. 图片教学属于视觉表达，不自动获得原确定性求解器的数学正确性证书；不增加图片 OCR 引擎。
5. 上传成功但发送前中断的 Blob 可能暂留本地数据库；已有按图片删除接口，尚无未引用 Blob 的定时回收任务。
6. SQLite 备份保留图片；原 JSON 隐私导出尚未增加图片二进制导出包。删除教育证据不等于删除用户图片内容。
