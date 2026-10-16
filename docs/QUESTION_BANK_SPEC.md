# 题库与学段协议（课程题 v2，保留 v1 核验入口）

题库按学段、教材分册、单元和知识点组织，提供两种练习入口：

- **课程练习**：每个目录知识点至少两道原创题，有独立题干、参考答案和解题说明。答案默认隐藏，可展开核对；点击讲解时只发送题干，进入普通教学对话。证明题和高级数学题不会被标记为已支持自动核验学生作答过程。
- **步骤核验练习**：使用既有确定性模板和本地求解/验证后端，只有求解成功且题型匹配的题目才显示。继续通过 `submit_problem` 进入作答闭环。

数形结合演示继续通过 `send_message` 发送可解析的画图请求。当前内容数量和逐点覆盖见 [覆盖报告](QUESTION_BANK_COVERAGE.md)。

## 编排与来源

小学 12 册、初中 6 册、高中 6 个教材/专题分组，共 24 组。目录参照人教版（高中人教 A 版 2019）编排，题目为 MathTutor 原创，不复制教材例题。地区与学校教学进度可以不同；选择性必修第三册的计数、分布与统计分析同时标记适用高二和高三。

- `catalog_k12_v1.json` 保留文件名和原有知识点编码；内容版本为 `k12-pep-v2`，新增子点附加在原单元末尾，不重排已有编码。
- `curriculum_questions_v2.json` 保存独立的课程题、参考答案及推导；随应用以包数据发布。
- `curriculum_content.py` 是原创题的紧凑源码，按明确知识点编码生成参数实例，无关键词模糊挂载或按标题套用四则运算。
- `scripts/build_question_bank_catalog.py` 确定性重建目录与课程题文件；构建时拒绝重复题干、超过 300 字的题干、不成立的数值关系和缺失映射。

## API

接口仍使用 `/api/v2/math-tutor/desktop`，身份验证与所有权规则保持现有约定。

`GET /settings/learner`、`PUT /settings/learner` 保留 `stage`、`grade` 和 `stages`。年级必须属于所选学段，`grade` 可为空。

### `GET /exercise-bank?stage=high`

未给出 `stage` 时采用保存的学段；未设置时返回全部学段。原有 `problem_count` 仍然仅表示本地步骤核验练习，不改变旧客户端含义。新增统计字段：

```json
{
  "version": "k12-pep-v2",
  "stage": "high",
  "source_note": "...",
  "terms": [{
    "code": "h3a", "stage": "high", "grade": 12,
    "recommended_grades": [11,12], "order": 23,
    "label": "高三上 · 选择性必修第三册", "book": "...",
    "units": [{"code": "h3a-u1", "title": "第六章 计数原理", "points": [{
      "code": "h3a-u1-p1", "title": "分类加法计数原理与分步乘法计数原理",
      "problem_count": 0, "reference_count": 2, "total_count": 2, "demo_count": 0
    }]}]
  }]
}
```

年级筛选使用 `recommended_grades`；旧数据没有此字段时回退 `grade`。它是查询推荐，不是学生能力标签。

### `GET /exercise-bank/points/{code}`

原有 `problems`、`demos`、`point`、`note` 保留。新增 `reference_problems`：

```json
{
  "point": {"code": "...", "title": "...", "term": "...", "unit": "..."},
  "problems": [{"id": "...", "text": "3x-5=10", "display_latex": "3x-5=10", "family": "linear", "difficulty": 1}],
  "reference_problems": [{
    "id": "...-ref-1", "text": "完整原创题干", "difficulty": 2,
    "category": "推理与证明", "reference_answer": "结论与必要条件",
    "explanation": "推导或参考证明",
    "verification": {
      "mode": "reference", "answer_check": null,
      "student_steps_auto_verified": false
    }
  }],
  "demos": [{"title": "...", "request": "画出 …"}],
  "note": ""
}
```

`answer_check` 为部分参考答案附带的精确数值等式，构建时离线检验。它不会校验用户任意自然语言答案，不代表整道证明已经形式化认证。未知 `code` 返回 404。

课程题、核验题及演示均为空时，`note` 返回暂无可核验题目的提示。课程题有内容时不显示“暂无题目”。

## 启动与答案披露

- 课程题通过 `send_message` 仅发送 `text`。不将参考答案、推导或审核元数据放入学生消息。
- 步骤核验题通过 `submit_problem` 发送 `text`，保留旧练习闭环。
- 演示通过 `send_message` 发送 `request`。
- 新对话 URL 仍使用 `?session=...&start=...` 或 `&ask=...`；读取后去掉启动参数，刷新不重复发送。
- 题干最大 300 字，与现有启动解析边界相同；构建时检查完整题干长度，不截断。答案默认放在可键盘展开的原生 `details` 中。

## 数学验证

覆盖清单、确定性数学断言与独立题面语义测试共同验证本次补题：

```bash
PYTHONPATH=src python scripts/build_question_bank_catalog.py
PYTHONPATH=src python scripts/audit_question_bank.py
PYTHONPATH=src python -m pytest tests/test_question_bank.py tests/test_question_bank_curriculum.py tests/test_curriculum_answer_semantics.py
```

数值关系检查使用精确有理数；独立测试从展示题干重新计算统计量、方程根、原定义域排除点、运算与几何数据，并用枚举/递推/参数代入验证概率及高中综合结论。课程参考题与现有自动步骤核验能力始终分开呈现。
