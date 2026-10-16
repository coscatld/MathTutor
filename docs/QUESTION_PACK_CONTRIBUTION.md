# 开源题库贡献快速入门

MathTutor 的共享题库格式为 `mathtutor.question-pack.v1`。它与应用内置的课程核验练习不同：共享包作为用户资料导入并可编辑，参考答案不会自动视为已验证的证明或提升掌握度。

## 最小示例

文件：`examples/question-packs/grade10-quadratic-functions.json`

```json
{
  "format": "mathtutor.question-pack.v1",
  "name": "高一二次函数基础练习",
  "author": "MathTutor 社区示例",
  "description": "原创基础题，不代表官方课程标准。",
  "questions": [
    {"id":"g10-quadratic-001","title":"配方法求最小值","stem":"求 y = x² - 4x + 3 的最小值。","answer":"最小值为 -1，在 x = 2 时取得。","explanation":"y = (x - 2)² - 1，平方项非负，所以最小值为 -1。","grade":10,"tags":["二次函数","配方法"]}
  ]
}
```

严格要求：包对象必须包括 `format`、`name`、`questions`；每题有唯一的非空 `id`、`stem`、`answer`；`grade` 若填写只能为 1–12 的整数。避免不认识的字段、重复题目 ID 或空字符串。请使用 UTF-8 保存文件。

## 投稿检查

```bash
python -m json.tool examples/question-packs/grade10-quadratic-functions.json > /dev/null
```

Windows PowerShell 可直接运行 `python -m json.tool 路径` 并查看是否报错。**JSON 语法通过不表示导入契约、数学答案或版权审核已通过**。须在 MathTutor 的“社区 → 发现资源”导入检查，然后在知识库编辑、导出回归。

## 版权与质量

- 只提交原创题目、明确获得开源授权的题目或确实属于公有领域的内容；教材、试卷、网站题目即使可公开访问，也不自动允许再分发。
- 涉及非原创内容，请在 PR 中附许可、来源 URL 和必要署名，切勿上传付费资料或隐私信息。
- 对每题核对答案和讲解；可以附解释，但不能宣传为已通过 MathTutor 的自动数学核验。
- 一题多个解时说明答案等价性；记录边界条件、单位和取值范围。

完整导入/导出规则和容量限制见 [共享题库与文本资料库](SHARED_QUESTION_PACKS.md)。
