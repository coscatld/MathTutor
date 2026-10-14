# 题库与学段（Question Bank v1）协议

## 目标

- 按人教版教材顺序整理小学一年级到高三的数学知识点：学段 → 学期（册）→ 单元 → 知识点。
- 用户在设置里选择自己的学段（可选具体年级）。题库默认只显示该学段：高中只出现高一上到高三下，初中只出现七年级上到九年级下，小学只出现一年级上到六年级下。
- 选一个知识点，可以：
  - 做**已验证**的练习题：题目由模板生成，每道都先经过本地求解器和验证器，未通过的不出现；
  - 看**数形结合演示**：一句会生成 Scene v2 的「画出 / 演示 …」请求；
  - 两者都没有时，如实显示「这个知识点暂无可核验题目」，不编造题目。

## 学期编排

| 学段 | 学期（顺序） | 教材 |
|---|---|---|
| 小学 `primary` | 一年级上册 … 六年级下册（12 册） | 人教版义务教育教科书 数学 |
| 初中 `middle` | 七年级上册 … 九年级下册（6 册） | 人教版义务教育教科书 数学 |
| 高中 `high` | 高一上 必修第一册；高一下 必修第二册；高二上 选择性必修第一册；高二下 选择性必修第二册；高三上 选择性必修第三册；高三下 总复习（专题） | 人教A版 普通高中教科书 数学（2019） |

学校之间进度可能不同；高三下没有新教材，按专题复习组织，引用前面各册的知识点。

## 数据

目录是随应用发布的静态数据：`src/mathtutor/question_bank/catalog_k12_v1.json`。

```json
{
  "version": "k12-pep-v1",
  "source_note": "参照人教版教材目录整理，学校进度可能不同",
  "terms": [
    {
      "code": "g7a", "stage": "middle", "grade": 7, "order": 13, "label": "七年级上册", "book": "人教版 数学 七年级上册",
      "units": [
        {"code": "g7a-u3", "title": "第三章 一元一次方程",
         "points": [
           {"code": "g7a-u3-p2", "title": "解一元一次方程——移项",
            "practice": [{"family": "linear", "template": "move_terms", "count": 6}],
            "demos": [{"title": "看等式两边的平衡", "request": "画出 y=2x+3 和 y=7"}]}
         ]}
      ]
    }
  ]
}
```

- `order` 全局递增，1 = 一年级上册，18 = 九年级下册，19–24 = 高中六个学期。
- `practice[].family` ∈ 现有可核验题型：`arithmetic` `polynomial` `linear` `linear_inequality` `quadratic` `quadratic_inequality` `linear_system`；`template` 是该题型下的生成模板名。
- `demos[].request` 必须能被 `scene_from_text` 确定性解析，或是 v1 单函数画图请求。
- 知识点可以同时有练习和演示，也可以两者都没有。

## 接口

全部挂在桌面路由 `/api/v2/math-tutor/desktop` 下，按现有方式鉴权。

### `GET /settings/learner`
`{"stage": "primary"|"middle"|"high"|null, "grade": 1..12|null, "stages": [{"stage": "primary", "label": "小学", "grades": [1,2,3,4,5,6]}, ...]}`

### `PUT /settings/learner`
请求 `{"stage": "high", "grade": 10}`（`grade` 可为 null，必须属于该学段）；返回同 GET。保存到数据目录的 `learner.json`。

### `GET /question-bank?stage=high`
`stage` 不传时用设置里的学段；设置也为空时返回全部学段。

```json
{
  "version": "k12-pep-v1",
  "stage": "high",
  "source_note": "...",
  "terms": [
    {"code": "h1a", "stage": "high", "grade": 10, "order": 19, "label": "高一上 · 必修第一册", "book": "...",
     "units": [{"code": "...", "title": "...",
                "points": [{"code": "...", "title": "...", "problem_count": 6, "demo_count": 1}]}]}
  ]
}
```

### `GET /question-bank/points/{code}`

```json
{
  "point": {"code": "...", "title": "...", "term": "高一上 · 必修第一册", "unit": "第二章 …"},
  "problems": [{"id": "g7a-u3-p2-1", "text": "3x-5=10", "display_latex": "3x - 5 = 10", "family": "linear", "difficulty": 1}],
  "demos": [{"title": "...", "request": "画出 …"}],
  "note": ""
}
```

- 题目在首次请求时生成并验证，之后缓存；同一版本的同一个 `id` 永远对应同一道题。
- 没有题目和演示时，`note` 是「这个知识点暂无可核验题目，可以把题目发给 Tutor 讲解」。
- 未知 `code` 返回 404。

## 前端

- 侧栏新增「题库」。页面顶部显示当前学段，可临时切换查看其他学段，不改设置；下面按学期分组，学期内是单元和知识点，知识点后标注题数和演示数。
- 点开知识点，列出题目（难度用星级）和演示。
  - 「开始练习」：新建对话，发送 `submit_problem`。
  - 「看演示」：新建对话，发送 `send_message`，正文是演示的 `request`。
- 设置 → 新增「学段」分区，可选小学、初中、高中，可选年级，也可以不选。
- 首次进入题库且未设置学段时，页面先提示选择学段。
