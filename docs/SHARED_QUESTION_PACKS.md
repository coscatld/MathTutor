# 共享题库与文本资料库

社区“发现资源”支持直接导入文件夹、Markdown 和 TXT；知识库和资料导入接口也支持题库 JSON 或包含文本文件夹的 ZIP。每次导入创建一个新的课程知识库；导入完成后，在对话的“对话资料”中选择它，才会成为该对话的参考来源。

导入内容是用户参考资料。题库中的答案带有“未经应用自动数学核验”的标识，不会因此写入知识掌握度，也不会成为内置逐步核验练习。普通 `SKILL.md` 也只是一份可编辑资料，不会安装技能、插件或执行代码。

## 题库 JSON v1

可直接使用 [一元一次方程示例](../examples/question-packs/linear-equations.json)。格式如下：

```json
{
  "format": "mathtutor.question-pack.v1",
  "name": "我的题库",
  "author": "创作者",
  "description": "可选的说明",
  "questions": [
    {
      "id": "linear-001",
      "title": "解方程",
      "stem": "解方程：2x+3=7。",
      "answer": "x=2。",
      "explanation": "先减去3，再除以2。",
      "grade": 7,
      "tags": ["一元一次方程"]
    }
  ]
}
```

`format`、`name`、`questions` 必填；每题必须有唯一的非空 `id`、`stem` 和 `answer`。`grade` 可省略，填写时为 1–12 的整数。其他字段可省略。不识别的字段、重复 ID、空题干或答案会使整包在写入前被拒绝。

每题导入为一份 Markdown，保留题干、用户参考答案、讲解、年级、作者和原始 ID。后续可以直接编辑正文。分享导出以编辑后的当前正文为准，导出的是 Markdown 资料库 ZIP，不会用原始 JSON 覆盖你的修改。

## Markdown / TXT 文件夹 ZIP

可以打包 Obsidian 样式的文件夹，例如：

```text
数学笔记.zip
  高一/
    函数.md
    三角函数.md
  复习/
    易错点.md
```

目录作为知识库中的逻辑文件路径保留，不会写入任意电脑目录。`.md`、`.markdown`、`.txt` 必须使用 UTF-8；隐藏文件夹、`.obsidian`、图片和其他文件会跳过，并列出提示。Markdown 中的 HTML、插件配置或文字指令不会获得执行权限。

当前上限：压缩文件 20 MiB、展开后合计 32 MiB、1000 份文档、每份文本 1 MiB。压缩包中的越界路径、绝对路径、Windows 盘符、反斜线、符号链接、重复路径（含大小写冲突）、加密或异常压缩比例会被拒绝。导入不会解压到文件系统。

相同正文会复用同一学生已有的资料。不同文件路径作为别名保留，导出仍包含这些路径；编辑共享正文会影响所有引用它的位置。移动别名只移动当前路径，其他别名保留。

## 可回导的资料库 ZIP v1

导出包含真实当前文本正文，以及 `manifest.json`：

```json
{
  "format": "mathtutor.vault.v1",
  "name": "我的数学笔记",
  "files": [
    {
      "path": "高一/函数.md",
      "title": "函数.md",
      "tags": ["函数"],
      "sha256": "这里填写该文件实际UTF-8字节的64位小写SHA256",
      "source_format": "markdown"
    }
  ]
}
```

导入时逐文件验证清单和 SHA256；哈希用于检查文件完整性，不表示数学答案正确。直接导入的 TXT 保留 `.txt` 路径；从 PDF 等资料提取的正文可导出为 Markdown，`source_format` 标为 `extracted`。图片或没有提取到的内容不会被伪装成完整原文件。旧版 MathTutor 知识库导出的清单列表格式也可以导入。

清单不包含学生身份、内部存储路径或引用回执。同一标题发生冲突时，导出添加安全的文档标识前缀，避免覆盖。

## 开发接口

所有接口要求已认证的当前学生身份：

- `POST /api/v2/math-tutor/desktop/community/documents/import`：multipart 重复的 `files` 字段，文件名为安全相对路径，可选 `operation_id`，支持单文件和文件夹文本；整批在写入前验证。
- `POST /api/v2/math-tutor/desktop/content/question-packs/import`：multipart `file`，可选 `name`。返回 `space_id`、`name`、`imported_count`、`warnings`、`format`。
- `GET /api/v2/math-tutor/desktop/content/libraries/{sid}/export`：导出该学生拥有的知识库 ZIP。
- 原有知识库笔记 API 继续提供 Markdown 编辑和版本冲突检查；更新需 `document_id`、`expected_version`、`operation_id`。
- 修改文件路径时提交 `relative_path` 和打开时的 `previous_relative_path`，只移动匹配的别名；正文仍由同一个文档版本管理。

解析和校验在建库前完成。后续逐条写入发生异常时，服务补偿清理本次新建库及新增资料，保留原有资料、草稿和操作记录；这不是跨多次事务的原子提交。内置题库和冻结的基准结果不受这些接口影响。
