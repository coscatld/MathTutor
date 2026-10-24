# MT-TEACH-001：多技能错误归因与整题观察

时间：2026-10-24 12:44（北京时间）。基线：`4e713f9`。本附件记录后端实现与验证；前端呈现和整轮验收由主报告汇总。未提交、推送或部署。

## 问题证据与真实链路

`application/controller.py:2102` 将确定性核验结果写入 `tracking_attempt`：`skill_ids` 来自整道题，`misconception_codes` 来自已核验作答的 signals。`subgoal_id` 只是当前教学目标，不能证明错误发生在哪个技能。生产链路当前没有可靠组件定位，不填写 `verified_error_skill_ids`。

旧 `application/learning_profile.py::active_misconceptions` 把错误、部分正确的每条 signal 复制到全部技能；后续多技能整题独立正确，又把这些技能上的全部规则清除。真实 WS 输入 `2x+3=7`、回答 `x=-2`，会得到 sign_flip 和三个题目关联技能，但没有证据证明三项技能都错误。画像因此与原本较保守的技能证据摘要不一致。

修改生产代码前先运行新增回归，得到 **11 failed、10 passed**：复现多技能误归因、整题成功全清、同题重答清除、部分正确定位不一致及缺失整题观察等问题。没有删除这些失败测试或降低断言。

## 实际行为

- `events.py` 提供共享的 `has_verified_outcome`、`attributed_skill_ids`、`independent_skill_success_ids`。单技能保留原作用域；多技能错误/部分正确仅采用已有的、服务器验证器提供的 `verified_error_skill_ids`，不从信号名称、当前教学目标或学生自述猜定位。
- `evidence_summary` 与画像共用归因规则。已定位的部分正确事件可以包含错误组件，该组件计入诊断错误，不再被计为步骤正确。无法定位的多技能整题结果仍计相关整题观察，不为每个技能复制成功或失败。
- 已定位规则只有该技能的首次独立新题成功，或明确单技能新题步骤成功，才会解除。受助、看答案、同题重答、选择诊断、来源不确定和多技能最终答对均不清除技能规则。步骤证据不成为整题独立训练标签。
- 新增 `item_error_observations`，保留无法定位的多技能错误及已知错误类别；不计入 `active_misconceptions`。后续同一 canonical revision 的可信自由作答整题正确可标记 `corrected_later`，包括提示后纠正；原错误仍保留，并指向纠正事件，不宣称长期掌握。
- 排除纠正记录会恢复 `unlocalized`；排除错误会移除该观察；删除学习结果会清除观察。导出调用同一投影，并增加白名单字段。旧事件、数学核验、所有者权限和删除事务均未改写。
- `teaching_evidence` 查询单个技能时，不再借用只是“包含该技能”的未定位整题结果。查询覆盖整道题的全部技能时，仍可使用整题观察。

公开 JSON 合同（画像顶层与导出的 `student_summary` 同名字段）：

```typescript
item_error_observations: Array<{
  rule_id: string;
  label: string;
  event_id: string;
  assessment_id: string;
  cycle_id: string;
  related_skill_ids: string[];
  last_seen_at: string | null;
  status: "unlocalized" | "corrected_later";
  correction_event_id: string | null;
}>;
```

每次错误的每条已知规则一项，最新在前。`related_skill_ids` 是题目关联范围，不是已证明的薄弱技能。根代理已据此接入学习画像与按 cycle 查证入口。

## 修改文件

- `src/mathtutor/learning/knowledge_tracing/events.py`：共享证据归因及解除条件，修正部分正确的失败组件统计。
- `src/mathtutor/application/learning_profile.py`：已定位规则、整题错误及后来纠正的重放投影。
- `src/mathtutor/application/evidence_projection.py`：教学上下文遵循技能作用域。
- `src/mathtutor/application/data_export.py`：共用投影、增加严格字段白名单。
- `tests/test_learning_profile_misconceptions.py`：先红后绿，覆盖单/多技能、错误/部分正确、解除条件、同题纠错、真实 WS/API 导出、排除、删除和持久化所有者隔离。
- `tests/test_phase6_privacy_wiring.py`：空导出精确合同加入 `item_error_observations: []`，保留所有原有字段断言。

## 验证结果

环境：本机 macOS，`<USER_HOME>/miniconda3/envs/deeptutor/bin/python`，仓库 `tests/conftest.py` 隔离临时数据；没有调用付费模型或读取真实学生数据。

1. 首轮红回归：归因文件 **11 failed、10 passed、13 warnings，0.92s**。
2. 首轮实现后：归因、证据分类、知识追踪三文件 **68 passed、1 failed**；失败为旧真实 WS 测试仍期望将未定位整题错误挂到技能。将该测试改为真实整题观察/纠错/排除/删除闭环后，三文件 **79 passed、13 warnings，2.41s**。
3. 相关集成首次执行 **223 passed、1 failed**；唯一失败是空导出精确合同缺少新增字段。补齐后单独运行归因与隐私接线文件：**40 passed、121 warnings，3.97s**。
4. 最终重新运行以下 11 文件：**224 passed、605 warnings，19.60s**。日志：`/tmp/mathtutor-003-teaching-attribution-tests.log`。警告未当作失败，也未声称为零。

```bash
PYTHONPATH=src <USER_HOME>/miniconda3/envs/deeptutor/bin/python -m pytest \
  tests/test_learning_profile_misconceptions.py \
  tests/test_learning_evidence_consistency.py \
  tests/test_knowledge_tracking_v2.py \
  tests/test_learning_profile_api.py \
  tests/test_learning_profile_contract.py \
  tests/test_production_evidence_contract.py \
  tests/test_main_sync_evidence_contract.py \
  tests/test_initial_assessment.py \
  tests/test_phase6_main_integration.py \
  tests/test_phase6_data_lifecycle.py \
  tests/test_phase6_privacy_wiring.py -q --disable-warnings --tb=short
```

`git diff --check` 通过。前端、全量后端、桌面构建和其他平台由整轮主报告提供实际结果，本附件不替代这些验收。

另一个旧预期来自固定多轮场景：`sign-error-diagnosis` 和 `quadratic-missing-root` 仍要求把整题信号放入技能误概念。根代理已把场景与 grader 改为严格检查：活动技能误概念必须为空，整题规则、状态和关联技能必须精确匹配；已纠正观察必须有 `correction_event_id`。这些检查均为 critical，并加入错误归因、观察丢失和伪纠正的负例，没有降低原评分门槛。根代理回报相关合并测试 **49 passed**；最终 16 场景 CLI 与全量验收结果以主报告为准。缺少 coverage 的旧评测报告仍标为未验收。

## 对应研究与采用边界

Ma 等《Interpreting Learning Under Competing Models: Joint and Stepwise Approaches for Dynamic Cognitive Diagnosis》，arXiv v1，**2026-06-05**。已读 §2 的 DINA/Q 矩阵方法、§3 的真实评分定义、§4 模拟设计、§5 局限，而非仅摘要。[论文全文](https://arxiv.org/html/2606.06804v1)

研究用阅读游戏中 1,978 名学生的二至三年级数据，对比联合与分步估计；DINA 明确容许猜对与失误。Punchline 只采用第一选择步骤，第二步骤因评分不一致被排除。局限包括选定题目子集、二元属性假设、计算成本和未建模的行为测量误差。其方法提醒我们：题目关联技能与单次可验证技能表现是不同层次，分类不确定性不能直接变成确定的薄弱判断。[方法与局限](https://arxiv.org/html/2606.06804v1#S5)

本轮据此采用保守归因与可查证的整题观察，不引入新的学生模型，也不把阅读研究或代码回归解释为 MathTutor 的教学效果提升。

## 遗留边界与后续检查

- 当前确定性验证器仍不能对通用多技能作答给出可靠的组件定位，因此生产多技能错误通常显示“具体技能待定位”。这是公开的产品状态，不是缺失数据时补猜测。
- `corrected_later` 仅表示这道题后来得到可信整题正确结果；包含受助后纠正，不等于独立迁移，更不等于长期掌握。首次独立标签与历史预测不被重写。
- 下一轮若实现步骤到技能的定位，应通过真实步骤核验产生依据，并覆盖多个错误类别与多个技能的对应关系；不能只让 LLM 填字段。
- 观察列表随保留历史增长，当前与既有画像一样全量重放；大量长期历史的分页和性能基准可另轮处理。本轮未运行人类学习实验，不报告诊断精度或学习增益。
