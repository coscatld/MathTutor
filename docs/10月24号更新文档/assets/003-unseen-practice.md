# MT-TEACH-002：迁移练习的完整历史查重

记录时间：2026-10-24，北京时间。基线提交：`4e713f93322c967cd11fa1f0c26f3a91b291fb02`。本附件记录本机代码与链路验证，不代表跨平台或教学效果评测。

## 问题与证据

原 `AdaptivePracticeService.prepare_offer` 只排除当前题目和最近 20 条练习邀请的题面。学生自行输入、从题库进入、提交但未完成判分、看过解答，以及窗口外的旧题，都可能再次被作为 A1/A2/B“新题”发布。学习追踪器已有的首次作答约束能阻止重复题虚增独立证据，但不能兑现产品层面的新题承诺。

新增专项测试先在修复前得到 **24 failed**，覆盖上述历史来源、完整邀请历史、学生隔离、E 复习、发布前曝光与恢复行为。测试中的旧题 `2x+3=7` 与候选 `2*x + 3 = 7` 使用同一规范化题目版本，不能靠换空格或乘号绕过检查。

审查还发现与候选耗尽恢复直接相关的已有故障：`LLMCandidateExerciseGenerator` 后的 `async def generate` 缩进在模块级；`PracticeGeneratorChain._try_llm` 调用 `llm.generate` 时抛出 `AttributeError`。单独回归在修改前为 **1 failed, 27 deselected**，错误确认为对象缺少 `generate`，并非模型请求失败。

## 已实施行为

1. A1/A2/B 使用学生自己的完整、仍保留的权威历史做本地检查。SQLite 查询合并所有邀请对应的 release hash、已绑定教学周期的 canonical content hash，以及 `problem_started`、`attempt_submitted`、`attempt_assessed`、`help_presented`、`help_possibly_exposed` 事件中的题目版本。查询没有最近条数限制，也不把全局题库或其他学生记录当作本人曝光。
2. 题目身份沿用发布链的 `MathProblem.canonicalize` 与 parser normalized AST。已验证的发布门、技能匹配、候选归属、答案泄露防护均保留。候选池在本地跳过历史版本；仍最多处理 3 个候选，生成等待仍为 30 秒。
3. 完整版本集合仅存于内部 `excluded_problem_revisions`，`exclude=True` 且不参与 repr；LLM 提示不包含它。模型仅收到最多 21 条排除题面和最近 20 条作答摘要，不能把完整历史塞入提示。模型生成的新颖性声明不参与放行。
4. 初次筛选、发布验证后和最终保存前分别检查历史。SQLite 最后一步在 `BEGIN IMMEDIATE` 事务内读取最新历史并写入邀请、推荐状态与 outbox，防止两个推荐并发发布同一新题，也防止生成期间另一窗口的曝光被漏掉。普通 SQLite 和 SQLCipher 路径均有真实并发回归。
5. 没有符合条件的候选时，推荐变为 FAILED，保留原题结果，提示重新请求或明确选择其他难度；不偷偷换目的、降低查重标准或无界重试。学生显式重试可在出现可用候选后恢复。
6. E 到期复习允许重做旧题。实际返回的 `purpose=E`、reason 和 observation_goal 明确说明复习观察不等于新题迁移通过。
7. 修复 LLM 生成方法的单行缩进。离线 provider 回归穷尽题库与模板后调用实际生成链，验证旧候选仍被拒绝、合格新候选正常发布；没有调用真实模型或外部服务。

## 历史、身份与删除语义

- `practice_offers.student_id` 按已有约定使用 `student_uuid(raw_owner)`；教学周期和学习事件使用原始 owner。查询分别使用正确标识，并以其他学生、未见过题目的学生以及全局候选记录验证隔离。
- 邀请无状态或时间筛选：已拒绝、过期或更早的邀请仍是题目已出现的保守证据。
- 排除学习证据不等于从未见过题目。查重读取原始事件，不使用 `valid_events` 去掉被排除的旧判分。
- `delete_educational_history` 的既有行为会删除学习事件和学习结果，但保留教学周期、邀请等骨架。本次尊重此边界：只有事件的历史随删除消失；仍保留的周期或邀请继续阻止“未见过”声明。不重建删除事件、不迁移旧记录、不修改既有删除接口。
- InMemory repository 同步增加接口并检查全部本人邀请，服务层合并可独立存在的事件存储。完整历史与最终写入同事务的保证针对生产 SQLite 路径；分离的开发内存存储不宣称具备跨存储事务。

## 修改文件

- `src/mathtutor/application/adaptive_practice.py`：完整历史筛选、生成后复查、恢复提示与最终保存参数。
- `src/mathtutor/application/llm_candidate_generator.py`：规范化版本计算、有限池本地排除、提示上限、LLM 方法缩进修复。
- `src/mathtutor/application/practice_offer_view.py`：E 复习的公开理由和观察目标。
- `src/mathtutor/domain/practice_context.py`：不序列化的内部历史集合。
- `src/mathtutor/repositories/practice_repository.py`：协议与内存实现同步、可构成曝光的事件类型。
- `src/mathtutor/repositories/sqlite_practice.py`：无窗口限制的本人历史查询、事务内最终检查。
- `tests/test_unseen_practice.py`：30 项真实仓储、服务、API、生成器和并发回归。
- 本附件。

未更改 controller、学习证据标签策略、数据库 schema、模型配置、依赖或服务。未操作用户实际数据库。

## 验证结果

工作目录为项目根目录；实际使用 macOS、Python 3.11.15、已有 deeptutor 环境。

修复前的 LLM 恢复链路回归：

```sh
PYTHONPATH=src <USER_HOME>/miniconda3/envs/deeptutor/bin/python -m pytest tests/test_unseen_practice.py -k exhausted_local_pool -q --tb=short
```

结果：**1 failed, 27 deselected**，`LLMCandidateExerciseGenerator` 缺少 `generate`。修复后该项纳入以下通过结果。

最终相关组合：

```sh
PYTHONPATH=src <USER_HOME>/miniconda3/envs/deeptutor/bin/python -m pytest tests/test_unseen_practice.py tests/test_practice_recommendation_v2.py tests/test_adaptive_practice.py tests/test_phase5_e2e_offer_flow.py tests/test_mastery_isolation.py tests/test_phase6_data_lifecycle.py -q --tb=short --disable-warnings
```

结果：**98 passed, 100 warnings, 6.51s，无 skip**。告警来自已有 FastAPI/Starlette 生命周期弃用和 pytest 标记；未放宽断言或关闭告警为错误的检查。`--disable-warnings` 仅省略详细告警输出。

两位其他 agent 分别只读复核最终事务、owner 映射、删除语义和提示边界，并独立执行专项：**30 passed, 13 warnings, 2.31s** 与 **30 passed, 13 warnings, 2.40s**，均无 skip。明文和 SQLCipher 并发测试都实际运行。`git diff --check` 通过。全仓最终检查由主线程统一运行，结果不在此提前声明。

专项还验证了：历史查询故障时不启动生成、不发布未查重邀请；较早邀请不进入有限题面窗口但仍被 canonical 集合阻止；最终保存前新增曝光会取消邀请，随后显式重试可恢复；真实 WebSocket 自输题与后续练习 API 共享本人历史；完整 hash 集合不出现在提示和公开序列化中。

## 研究依据与适用范围

美国国家研究委员会在《How People Learn》“Learning and Transfer”一章将迁移讨论为把已有学习用于新情境，并区分重复记忆与新问题上的应用。这支持在产品中区分“旧题复习”和“未见过题目的检测”，但不直接给出本系统的 canonical hash 算法或教学有效性结论。[National Research Council, 2000, chapter 3；DOI 10.17226/9853](https://www.nationalacademies.org/read/9853/chapter/6)

本次采用的工程推论是：排除已知旧题是兑现“新题”承诺的必要检查，不是证明迁移能力充分的评测。仅换数字的同构题也不能证明远迁移。没有开展真实学生实验或真实模型质量评测，**教学效果未验证**。

## 遗留风险与后续

- 查重保证限定为当前 parser 支持、可规范化并保留了归属事实的题目版本；不宣称能判断任意图像、自然语言题或语义近似题是否见过。
- 规范化可能把表面不同但化简后相同的算术题合并，表现为保守拒绝，而不是允许旧题冒充新题。
- 完整历史查询和本地集合随历史长度增长，尚未做百万条记录基准；候选循环和模型提示仍有界。后续可基于实际规模测量再决定是否增加索引或局部缓存，不能以截断历史替代正确性。
- 在最终复查拒绝候选之前，已验证 release 可能已写入公共候选存储；不会因此产生新的学生邀请或学习证据。
- A1/A2/B 要求未见过；E 明确允许复习；C/D 保留原有候选策略。未扩展为所有教学目的都必须新题。
- Windows、Linux 和实际外部模型在本附件中均未实测；最终全仓与 CI 状态以主报告为准。
