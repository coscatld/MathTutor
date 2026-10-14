# Tutor v2 实施与验收覆盖矩阵

审查日期：2026-09-11。依据：《MathTutor 整体重构修改方针 v2.0》第 1–21 节，重点逐项核对第 18 节的 52 个验收编号。对象为当前工作区，包含尚未提交的前两批修正和本批正在集成的代码。

## 阅读口径

- **已实现**：对应行为已有实际调用链及针对性自动回归；适用范围写在所在行。
- **部分实现**：已有部分机制，但关键分支、端到端接线或专门回归仍有缺口；缺口写明需要补什么。
- **需真实数据验收**：工程管道可运行，结论依赖真实学习数据、模型配置或人工评分。此状态不用于替代尚缺的代码。

本表记录行为证据，不按类名、函数数量或测试总数判定完成。新集成代码的最终全量运行结果与三条真实前端演示写入文末“最终验收记录”。

## 代码与测试入口

| 简称 | 实际入口与职责 |
|---|---|
| 命令/编排 | [controller.py](../src/mathtutor/application/controller.py)、[message_intent.py](../src/mathtutor/application/message_intent.py)、[student_contract.py](../src/mathtutor/application/student_contract.py)：公开命令、绑定、意图、作答与教学调度 |
| 请求恢复 | [math_tutor_ws.py](../src/mathtutor/api/math_tutor_ws.py)、[turn_repository.py](../src/mathtutor/repositories/turn_repository.py)：请求 claim、负载校验、持久化结果与重放 |
| 教学与交付 | [teaching_plan.py](../src/mathtutor/pedagogy/teaching_plan.py)、[quality_guard.py](../src/mathtutor/pedagogy/quality_guard.py)、[teaching_repository.py](../src/mathtutor/repositories/teaching_repository.py)：子目标、计划、质量门、帮助交付 |
| 数学验证 | [attempt_verifier.py](../src/mathtutor/learning/attempt_verifier.py)、[linear_system_attempt.py](../src/mathtutor/learning/linear_system_attempt.py)、[linear_system_verifier.py](../src/mathtutor/solving/linear_system_verifier.py)：原题验证、局部结果、完整性与二元一次方程组 |
| 练习 | [practice_policy.py](../src/mathtutor/application/practice_policy.py)、[adaptive_practice.py](../src/mathtutor/application/adaptive_practice.py)、[practice_release.py](../src/mathtutor/application/practice_release.py)：推荐目的、候选预算、发布与快照 |
| 学习追踪 | [knowledge_tracing](../src/mathtutor/learning/knowledge_tracing)：事件、EvidenceTracker、特征、LSTM 训练、评估、推理与 h/c 恢复 |
| 前端 | [protocol.ts](../web/features/math-tutor/lib/protocol.ts)、[reducer.ts](../web/features/math-tutor/lib/reducer.ts)、[teaching-contract.ts](../web/features/math-tutor/lib/teaching-contract.ts)、[delivery.ts](../web/features/math-tutor/lib/delivery.ts)：公开投影、同源恢复、语义标签与呈现 ACK |
| P0 回归 | [test_tutor_p0.py](../tests/test_tutor_p0.py)：真实 HTTP/WS、隔离 SQLite、重启、并发与结果去重 |
| 绑定回归 | [test_tutor_p1_binding.py](../tests/test_tutor_p1_binding.py)：同题作答、知识点追问、复合请求和版本校验 |
| 方程组回归 | [test_linear_system_v2.py](../tests/test_linear_system_v2.py)：独立代入验证、部分解、替代等式与伪造步骤拒绝 |
| 本批教学集成回归 | [test_teaching_v2.py](../tests/test_teaching_v2.py)：真实 WS/SQLite、独立完成、返回原题、答案 ACK、可选诊断与累计坐标 |
| 内容质量回归 | [test_answer_exposure_v2.py](../tests/test_answer_exposure_v2.py)、[test_teacher_error_example_v2.py](../tests/test_teacher_error_example_v2.py)：实际答案暴露和经验证的明示错误/修复 |
| 练习回归 | [test_practice_recommendation_v2.py](../tests/test_practice_recommendation_v2.py)、[test_phase5_e2e_offer_flow.py](../tests/test_phase5_e2e_offer_flow.py)、[test_phase5_practice.py](../tests/compat_deeptutor/test_phase5_practice.py) |
| 追踪回归 | [test_knowledge_tracking_v2.py](../tests/test_knowledge_tracking_v2.py)：真实 SQLite、标签时序、训练参数变化、NumPy/PyTorch 一致性与版本恢复 |
| 前端回归 | [math-tutor-completion.test.tsx](../web/tests/math-tutor-completion.test.tsx)、[math-tutor-binding.test.tsx](../web/tests/math-tutor-binding.test.tsx)、[math-tutor-teaching-contract.test.tsx](../web/tests/math-tutor-teaching-contract.test.tsx) |
| 固定验收回归 | [test_tutor_v2_acceptance.py](../tests/test_tutor_v2_acceptance.py)：真实 WS 的能力遍历、裸数字、伪造评价、同技能示例、自我报告、邀请失败/拒绝与 Writer 失败 |
| 语言语义回归 | [test_tutor_language_intent.py](../tests/test_tutor_language_intent.py)、[test_tutor_semantic_guards.py](../tests/test_tutor_semantic_guards.py)：LLM-first 结构化提案、白名单、否定/引用、复杂作答、预算、故障与真实 Writer 同链路 |
| 任务与技能回归 | [test_problem_context_v2.py](../tests/test_problem_context_v2.py)：完整任务投影、验证引用、13 节点诊断题实算与逐步技能映射 |
| 表达恢复回归 | [test_teaching_recovery_v2.py](../tests/test_teaching_recovery_v2.py)、[test_student_evidence_view.py](../tests/test_student_evidence_view.py)：已批准表达的重启恢复、焦点竞态，以及 Writer 学生证据的答案隔离 |

## C：公开命令与交互恢复

| ID | 要求 | 当前状态 | 已有行为证据与验收缺口 |
|---|---|---|---|
| C01 | 真实按钮展示当前完整答案 | 已实现 | 前端按钮仅发送 `request_solution`；0.4.5 之后需先看过一次提示，下面的零提示演示是更早的行为记录；真实 UI 演示 3 在 `4x-1=19` 零提示点击索解，展示完整验证解答 `x=5` 与 B 邀请，随后原题复述正确进入 post_solution。 |
| C02 | 未解决的题目先看一次提示再索解 | 已实现（取代原「零提示允许明确索解」） | `StagePolicy.min_hints_for_solution = 1`，规划器拒绝时返回 `HINT_REQUIRED`、不推进状态，能力快照同步置灰；已答对、已看过答案的题目可回看。`test_solution_after_one_hint_and_retry_actions`、`tests/test_solution_hint_gate.py` 覆盖。 |
| C03 | 答错后仍可索解 | 已实现 | 同一参数化回归覆盖 `AWAITING_RETRY`；状态与公开能力允许解释、示例和答案。 |
| C04 | 旧内部名仅作为受限兼容请求 | 已实现 | `test_legacy_alias_is_only_a_version_one_request`：协议 v1 归一化后再校验；协议 v2 拒绝内部事件名。 |
| C05 | 所有 enabled 动作都能由公开解析器识别 | 已实现 | 静态状态全表和 `test_c05_all_observed_enabled_capabilities_are_public_parseable_commands` 双重覆盖。后者走真实练习/接受/返回、诊断错误/跳过/C、独立完成/到期 E，逐个校验 enabled 命令通过公开解析器和 allowlist；前端不显示内部事件。 |
| C06 | 相同请求只有一个失败容器与恢复入口 | 已实现 | 前端 `same_turn_error_and_terminal_error_share_one_result_and_one_recovery`、`error_after_content_remains_inside_the_same_turn_container`；后端失败追加到同一个结果记录。 |
| C07 | 双击/重发不重复产生学习事实 | 已实现 | P0 覆盖重复 hint、两个 socket、不同 payload 冲突、重启重放；请求在产生效果前 claim，并按 owner/conversation/request 隔离。 |

## I：题目绑定、子目标与意图

| ID | 要求 | 当前状态 | 已有行为证据与验收缺口 |
|---|---|---|---|
| I01 | `x=2`、`2=x`、`x=4/2` 属于当前题作答 | 已实现 | `test_main_input_is_assessed_against_the_same_problem` 断言评估结果及原题 ID；跨算术、多项式、一次/二次方程变量的参数化回归同时覆盖。 |
| I02 | 错误中间式保留原题并纠错/标未知 | 已实现 | 显式步骤进入原验证器；无明确意图的新等式先澄清。当前验证覆盖范围内输出 invalid/unknown，均保留原题与原始输入。 |
| I03 | 方程组仅答出 x 不算整题完成 | 已实现 | `test_partial_values_never_complete_the_system` 验证单坐标/中间式为 partial；`test_system_accumulates_verified_coordinates_but_not_premature_completion` 通过真实 WS 从主输入框按 x/y、y/x 两种顺序作答，断言首步无邀请、第二步完整验证后才完成。 |
| I04 | 接受有效替代方法、跳步或整题答案 | 部分实现 | 方程组验证支持原式倍乘、任意有效一次关系与完整坐标；教学上下文仍使用有限目标序列，任意替代分支和跨轮合并结果需专门验收。 |
| I05 | 明确换题时正确切换并保留旧题事实 | 已实现 | `test_old_cycle_binding_is_rejected_after_explicit_topic_switch` 与 `test_explicit_new_problem_replaces_active_cycle`；旧请求带旧 cycle/revision 时拒绝。原题搁置/返回的生命周期由 P10 另验。 |
| I06 | 新方程/旧步骤歧义先问清楚 | 已实现 | 澄清文本持久化；`test_ambiguous_equation_clarification_survives_restart` 与 `test_clarification_can_choose_new_problem` 覆盖重启后确认步骤或新题。 |
| I07 | 正确处理“不要答案，给提示” | 已实现 | `test_negation_and_method_questions_do_not_submit_an_answer` 验证不会触发索解或伪造作答。 |
| I08 | 复合作答先记索解前证据，再给答案 | 已实现 | 原索解复合句和 `test_composite_answer_is_verified_before_semantic_explanation_and_never_replaces_problem` 均通过；“x=3，我还是糊涂，解释一下”先提交原题独立错误证据，再记录讲解帮助，保持同题和 awaiting_retry。 |
| I09 | 无题干的 391 先澄清任务 | 已实现 | `test_i09_bare_number_requires_a_specific_task_before_grounding` 现通过：回复明确针对 391 询问任务，当前题目为空，原有启动种子题数量不变、零学生作答。 |
| I10 | 已完成题目的追问仍绑定原题 | 已实现 | `test_review_uses_bound_problem_and_does_not_create_extra_solution_action`、`test_same_skill_followup_keeps_problem_and_reaches_bounded_writer`；答案回看只取批准正文。 |

## T：教学策略与输出质量

| ID | 要求 | 当前状态 | 已有行为证据与验收缺口 |
|---|---|---|---|
| T01 | 只求提示时不伪造学生正确评价 | 已实现（固定集） | `test_t01_hint_never_publishes_an_unobserved_student_success` 通过真实请求注入六种 Writer 伪造肯定，均在呈现前替换为同题可操作提示；原 cycle 保留，无作答或学习正确性记录。对抗同义改写可继续扩展，但不宣称通用语义判别完备。 |
| T02 | 两次没懂后改变支架 | 已实现 | 真实 UI 演示 2 中两次困惑后，由概念提示转为 `3x-9=0` 的已验证局部移项；语言回归还验证单次 persistent 语义即可拆小，不要求凑足关键词计数。 |
| T03 | 示范后仍卡住提供退出选择 | 已实现 | 重复教学操作提供示例/索解/主动练习/结束出口；真实 UI 演示 2 在可验证基础错误后授权 C，实际接受、独立作答并返回原题。补基础不会仅凭“不会”自动宣告知识缺陷。 |
| T04 | 已验证子目标不被原样重问 | 部分实现 | 已有持久化 progress/subgoals 和指纹；只有经验证的 variable_value/root_subset 推进局部目标，重述原式不算完成。跨轮方程组坐标已通过产品回归；任意有效替代方法的后续教学目标仍需专门多轮断言。 |
| T05 | 消元例题保持同技能 | 已实现 | `test_t05_system_example_is_verified_same_skill_material` 捕获真实 Writer 输入与最终正文：示例仍是 linear_system、题目不同、完整批准示例进入正文、无分数模板串入，不创建学生作答。 |
| T06 | 找错示例明确标注且不记作学生错误 | 已实现 | 五题族错误与修复独立验证；`test_teacher_error_analysis_is_verified_but_not_original_task_evidence` 经真实 WS 请求明示错误示例，拒绝把重述题干当修复，接受有效修正；保持原题、零 mastery_evidence，作答仅进入 error_analysis。 |
| T07 | 立即作答无强制等待 | 已实现 | 发送请求无 45–60 秒阅读锁；busy 仅表示本次请求未终止。未新增提醒默认开启或“超时即不会”判定。 |
| T08 | Writer 失败有界恢复且保持同题 | 部分实现 | 输出先 Guard，再同题模板；无无限重写循环。异常、伪造学生评价、显式不泄露与恢复检查点已有真实回归；空响应、数学错误、跑题、无授权模板材料的完整失败分支矩阵仍需补齐。 |
| T09 | 一步提示泄露最终结果时如实记暴露 | 已实现（五个支持题族） | `test_target_answers_detected_across_all_supported_families` 覆盖五题族、根式与无实根；`test_l3_final_step_exposure_cannot_be_independent_evidence` 验证 L3 的真实终值也算 post_solution。产品交付在发送前调用同一 `target_answer_only` 检测口径；超出支持题族不宣称有通用语义识别能力。 |

## P：学习证据与练习邀请

| ID | 要求 | 当前状态 | 已有行为证据与验收缺口 |
|---|---|---|---|
| P01 | 完整独立正确→A1 迁移 | 已实现 | 推荐/发布/真实 WS 回归通过；真实 UI 演示 1 用 `x=2` 独立完成 `2x+3=7` 后产生 A1，接受 `3x-5=4`，重启后仍处在同一子题与历史。 |
| P02 | 受助完成→A2，不能算独立 | 已实现 | `test_p02_presented_hint_then_correct_answer_is_assisted_and_offers_a2` 经真实 WS 请求提示、发送真实 delivery ACK，再答对原题；断言呈现事件先于作答、assisted=1/independent=0、正确证据带 prior_help_ids，且推荐 A2。无需等待或轮询制造顺序。 |
| P03 | 看答案后复述标 post_solution | 已实现 | 真实 UI 演示 3 查看 `4x-1=19` 完整答案后复述 `x=5`，界面 post_solution=1、独立=0；接受新题 `3x-2=16` 后首次答 `x=6` 记录独立=1。丢 ACK/跨会话同题暴露另有回归。 |
| P04 | “懂了”仅作为自我报告 | 已实现 | `test_p04_understood_is_self_report_not_correctness_or_completion` 现通过：保持原题、无作答/完成/邀请，新增一条无正确性标签的 self_explanation 事实。 |
| P05 | 候选全部失败，没有空邀请 | 已实现 | 服务层三候选上限/FAILED/可重试与真实 WS `test_p05_failed_candidates_keep_the_assessment_but_never_publish_an_empty_offer` 均通过；后者确认原题 SOLVED、唯一作答保存、零 offer、无接受/拒绝能力。 |
| P06 | 主动练习不要求先完成或达到 L4 | 已实现（公开命令） | `test_practice_without_completion_and_return_to_original` 在零作答、零帮助时经真实 WS 请求 D、接受子题、返回原题；前端公开按钮只使用服务端 capability。自然语言同义句仍按意图覆盖集持续扩展。 |
| P07 | 并发接受同邀请只开一个子周期 | 已实现 | `test_concurrent_accept_opens_only_one_child_cycle` 使用两个并发真实 WS，两个响应返回同一个 child，SQLite 对该 practice_offer_id 只有一条 child cycle。 |
| P08 | 已接受后过期的重放返回原 child | 已实现 | `test_duplicate_accept_after_expiry_replays_same_child_cycle` 先接受、将过期时间推进至过去、重新请求；返回原 child 与 idempotent_replay，而不是重新发布或拒绝原收据。 |
| P09 | 子题固定接受时 release 快照 | 已实现 | `test_17_exact_release_snapshot_judging` 发布新版本后仍用原快照判题；`test_full_chain_solve_offer_accept_child_judge` 覆盖真实 SQLite 子周期。 |
| P10 | 补基础后可返回父题，父题不自动完成 | 已实现 | `test_verified_prerequisite_gap_enables_foundation_and_keeps_parent` 和真实 UI 演示 2 一致：C 子题独立完成后返回父题，父题仍 awaiting_retry、原目标/受助记录保留，不继承子题的完成结论。 |
| P11 | 拒绝邀请后仍可追问原题 | 已实现 | `test_p11_decline_preserves_original_problem_for_followup` 经真实 WS 拒绝后询问等式两边操作，响应仍使用相同 cycle/revision，状态保留 SOLVED，无额外作答或重新弹出邀请。 |

## D：学习事件、训练与追踪

| ID | 要求 | 当前状态 | 已有行为证据与验收缺口 |
|---|---|---|---|
| D01 | unknown 没有正确性监督 | 已实现 | `test_unknown_attempt_commits_without_optional_evidence`、`test_unknown_and_partial_never_become_whole_task_failure`：保留作答，排除独立二元目标。 |
| D02 | 提示失败不产生呈现帮助 | 已实现 | `test_d02_failed_writer_request_is_not_presented_help` 注入 Writer 异常，真实终止为错误、无 teaching_deliveries、无 possibly_exposed/presented、无学生作答；请求/提交本身不算帮助曝光。 |
| D03 | 局部错误不扣所有技能 | 已实现 | `test_multiskill_failure_not_copied_to_every_skill`：未定位多技能失败仅保留题目级不确定性；有 verified_error_skill_ids 才定位对应技能。当前原题步骤到细技能的接线另列下方额外交付表。 |
| D04 | 同一事件重放不重复更新状态 | 已实现 | `test_prepare_prediction_precedes_label_and_replay_is_idempotent` 与 owner/event_seq 唯一约束；帮助呈现重复事件也按 ID 去重。 |
| D05 | 修改未来标签不改变更早预测 | 已实现 | 训练逐事件先 predict/loss 再 update，在线固定 cutoff；新增 `test_d05_future_label_mutation_cannot_change_any_earlier_prediction` 对真实训练模型翻转后半段标签，比较改变事件自身及之前所有预测完全一致。 |
| D06 | padding/缺失时间不是有效学习 | 已实现 | 首版逐实际事件训练，无 padding 行；缺失 response/time_gap 使用独立 mask。`test_feature_unknown_is_distinct_from_incorrect_and_current_item_has_no_label` 验证 missing 与 0 区分。 |
| D07 | 同题副本/多技能行无跨划分泄漏 | 部分实现 | `test_splits_isolate_identity_and_chronology` 覆盖 student/time/family；`test_near_duplicate_family_keys_cannot_cross_student_split` 覆盖显式 leakage_group。未标注近重复组的数据在 data_gaps 单列，训练前仍需完成题族/近重复映射审查。 |
| D08 | 模型换版本按事件重建 h/c | 已实现 | `test_model_snapshot_restart_and_version_change_replay` 对比重启预测、换版本重放；快照保存 h、c、事件序号及模型/图谱/特征版本。 |
| D09 | DKT 故障不阻断数学辅导 | 部分实现 | `test_bad_model_does_not_block_assessment_or_claim_trained` 验证不可读模型仍保存作答；无 DKT 模型的产品回退已随全量测试与真实 UI 执行。坏模型配置的完整产品聊天链仍缺针对性回归。 |

## R：事务、流式交付与恢复

| ID | 要求 | 当前状态 | 已有行为证据与验收缺口 |
|---|---|---|---|
| R01 | 作答已提交后 Writer 失败只补未完成表达 | 已实现 | `test_committed_assessment_writer_failure_resumes_expression_only_after_restart` 对正确/错误复合作答均先提交，再注入 Writer 失败；重启重放只补未完表达，同一 message_id、一次作答/动作，再重放也不新增。 |
| R02 | 消息已提交后崩溃重放同一 message_id | 已实现 | P0 restart/replay/abandoned 回归与前端 snapshot 去重；客户端呈现 ACK 仅对可见已终止正文发出。generic 生命周期帧的缺省 null 不再清空刚提交的权威上下文；明确的 capability 快照仍可清除失效邀请。 |
| R03 | 生成中换题不污染新题 | 已实现 | `test_focus_changed_while_model_runs_discards_old_expression_before_delivery` 在真实 Provider 调用期间更改持久化焦点，返回前再次校验并拒绝旧表达；新题焦点保留、零旧题消息/动作/帮助交付。另有 cycle/revision 变化后旧表达检查点不得恢复的重启回归。 |
| R04 | 答案中断仅记录实际/可能暴露 | 部分实现 | 已批准内容才进入流式，台账区分 committed/possibly_exposed/presented；需记录部分内容对应范围并验证断线/取消下无“全文已呈现”误记。 |
| R05 | 计划 L5 降级 L1 时按最终动作记账 | 已实现 | `test_final_disclosure_downgrade_is_consistent_across_action_delivery_and_evidence` 固定触发 L5→L1：实际 TutorAction 为 hint/L1，delivery 与学习事件均非答案暴露、未进入 solution_shown、无 B 邀请。明确“不要答案”的 L3 最后步也回退为不泄露终值的 L1。 |
| R06 | 刷新/恢复不清空同题帮助 | 已实现 | `test_same_canonical_problem_in_new_conversation_keeps_answer_exposure` 与 `test_new_cycle_does_not_inherit_old_help` 成对通过：同 owner/canonical revision 的历史暴露跨会话保留；真正不同题目不继承，其他用户仍隔离。 |

## 第 18 节之外的必要交付

| 文档要求 | 当前状态 | 可核查结果与剩余工作 |
|---|---|---|
| ProblemContext 保留完整任务、来源、定义域、单位、精度与验证能力 | 已实现（五个支持题族） | `problem_context.py` 已接 initial_context、原题归一化和 Writer 输入，保留完整原文/来源、规范任务/预期答案形态、当前目标与验证能力。VerifiedSolutionRef 校验题目版本和载荷摘要，公开投影不含答案。未提供或当前验证器不支持的单位、精度、附加条件明确记 unknown/unverified，不伪造为已验证。 |
| 按学段和当前证据选择策略，取消固定 PRIMARY | 部分实现 | `controller` 已切换中性 ADAPTIVE_POLICY，新 TeachingPlan 按停滞与局部错误调整；学生明确学段/偏好持久化后进入具体语言策略仍需完整链路。 |
| 历史知识点证据驱动下一步教学 | 部分实现 | `_write_guarded` 已加载相交细技能的历史独立题目证据；多题独立正确选择 compare_methods/较轻支架，多题独立困难选择 prerequisite_check。前端显示对应原因；需专门比较有/无历史证据的实际教学内容，不以字段变化代替适配效果。 |
| 自然语言和按钮同链路、语义理解困难（用户追加） | 已实现（调用链与固定集） | 当前 Tutor Provider 先输出严格语义 DTO，后端验证引用/目标/权限后执行同一公开教学动作。隐喻求助、否定/引用、复杂作答、resolved 清困惑、按钮不复用旧信号、一次语义调用及共享 token 预算均通过；真实 UI 原话也到讲解。LLM 固定测试使用可控 Provider，真实模型语义质量另做样本评审。 |
| 可维护知识图谱和步骤知识点 | 已实现（当前课程覆盖） | 13 个细技能节点包含定义、常见错误、诊断题与适用题族；prerequisite/related/part_of 各有语义。25 项专项回归实际 parse→solve→verify 全部节点诊断题，检查一次/二次方程和方程组的逐步 skill_map；未知步骤不猜。当前目标的 skill_ids 已进入计划，未把整题技能复制给每步。 |
| 5–10 分钟可跳过冷启动诊断 | 部分实现 | 已绑定题目后可自愿开启相关诊断、保留原题、跳过不记错。完整时间预算、学段/章节偏好、按技能分支与结束反馈需专项验收。 |
| 学生群体先验与共享模型 | 部分实现 | EvidenceTracker 使用中性基线，训练参数共享、个人 h/c 隔离；群体/诊断/迁移先验的冷启动效果尚无真实数据验证，外部数据的课程映射、授权与帮助字段接入仍未完成。 |
| LSTM 训练、导出、推理、恢复与评估 | 已实现（工程管道） | 训练使用真实梯度更新；NumPy 推理与 PyTorch h/c 对齐；CLI 支持三种划分、多 seed、校准、AUROC/AUPRC/log loss/Brier/ECE、按技能/学生/序列长度分组、学生重采样与模型大小/延时。最终执行产物记录见下。 |
| DKT 对教学策略的接管 | 需真实数据验收 | 产物固定 shadow，产品选择 EvidenceTracker。需真实学生数据、多 seed 与冷启动群体评估后才能讨论显著影响策略。 |
| 独立/受助/post_solution 事件与可解释 UI | 已实现（证据展示） | 会话按当前 canonical revision 计数，profile 按细技能展示 flat 数字；无跟踪器也返回同一细技能结构和 null mastery。`test_student_summary_empty_in_memory`、`test_student_summary_reports_evidence_without_fabricated_mastery` 通过，web 不再显示旧百分比。 |
| 候选题接地、技能适配与有界预算 | 已实现（当前模板覆盖） | 新练习回归检验引用区间、设计影响、无关 chunk 不算接地、错误技能发布被拒绝、最多三个候选。更细步骤技能与二元方程组推荐仍需联调。 |
| 延迟复习入口与证据 | 部分实现 | purpose E 与 `request_review` 已接，只有同技能历史独立正确距今至少三天才授权；前端不推断开启。当前是固定试验窗口，配置化间隔与实际复习作答回归仍需补齐；未启用后台提醒。 |
| 旧数据安全迁移 | 部分实现 | 011–014 增加新实体；012 已将无历史 offer 的 reflection/practice_offered 修复为 solution_shown。旧会话缺少新上下文时，恢复链按需写入 legacy_auto_transition/legacy_provenance_uncertain，来源不确定的旧帮助排除独立主目标；这不是全库主动回填，完整安装升级验收尚未执行。 |
| 作答事务、最终消息、动作、交付与 outbox 一致 | 部分实现 | 作答与追踪事件复用事务，Writer 不占长事务。R01/R05 和 6 项表达恢复回归证明：已批准但未提交动作、动作已提交但未发送两个检查点都恢复同正文/ID，只调用一次模型、不重复事实。任意流式中断的部分呈现范围及所有故障窗口的原子性仍由 R04 单列。 |
| Writer 只接收必要学生证据，不旁路获取答案 | 已实现（结构化上下文） | `student_evidence_view.py` 白名单保留学生实际步骤、已验证正确性和待完成要求名称；移除等价证明中的私有 root、expected、missing_roots。两个固定测试同时验证不修改原验证台账、不误删学生已经写出的坐标。 |
| 回复质量固定集与评分量表 | 部分实现 | 已有协议/数学行为回归；需导出固定多轮样本，按数学、目标相关、学生证据、可执行性、适配、连贯六维完成评分，保留关键失败。 |
| 解决率 >85%、平均 5–8 轮、长期迁移/保持与 B0/B1/B2 对照 | 需真实数据验收 | 按文档口径收集分子、分母、退出和失败。合成训练、模板演示与工程测试分别报告，不用它们替代真实学习效果。 |
| 产品漏斗与验收分母 | 已实现（事件统计管道） | `test_product_funnel_v2.py` 覆盖 eligible start、实际呈现、退出/未知仍保留在分母；缺少遥测时返回 unavailable。尚无真实用户样本支持达成目标解决率或学习效果。 |

## 最终验收记录

### 自动化与构建

| 检查 | 当前已观察结果 | 记录边界 |
|---|---|---|
| web 自动测试 | 129 项通过 | 含 C/E 命令授权、教学理由、诊断计数、真实按钮 payload、呈现 ACK、generic null 保留权威快照、图标可访问名称及所有新增学习动作中文卡片标签。 |
| web 生产构建 | 最终 `npm run build` 通过 | 编译、TypeScript 和 11 个静态页生成全部通过。真实 UI 验收停服后构建；已删除本次 dev 生成的 AGENTS.md/CLAUDE.md，next-env.d.ts 回到原构建路径，这三文件无残余 diff。未打包 dmg。 |
| 本批 Python 聚焦回归 | 217 项通过；其后 offer E2E 7 项通过 | 14 个文件，含旧契约、教学、方程组、答案暴露、练习与真实 LSTM 回归；后一轮含新增并发接受与过期重放。不把两轮重叠测试相加。 |
| 新增固定验收回归 | 20 项完整复跑通过，随后新增 P02 单项通过 | 首轮揭示 I09 具体任务澄清与 P04 自我报告缺失，修复后完整复跑；新增 P02 使用实际 ACK 与 SQLite 作答事实验证 A2。最终是否包含最新用例以全量记录为准。 |
| 语言语义与教学集成复跑 | 84 项通过 | language_intent / semantic_guards / v2_acceptance / teaching_v2 四文件；含 resolved 重置困惑及讲解后保留 retry 的严格回归。 |
| 冻结后最后聚焦补验 | 55 项通过，12.47 秒 | teaching_v2 18 项、language_intent 35 项、student_evidence_view 2 项；新增“引用讨论困惑”走非教学整链、零数学动作/帮助的回归通过。与全量重叠，不相加。 |
| 任务上下文/学习追踪集成 | 122 项通过 | problem_context / knowledge_tracking / product_funnel / answer_exposure / data_lifecycle / privacy_wiring / teaching_v2 七文件；其中完整任务与技能专项 25 项通过。与其他回归有重叠，不累加。 |
| Python 全量回归 | 最终完整一轮 1001 项通过、4 项跳过 | 用时 86.99 秒；4 项 sqlite_vec_probe 因 `/tmp/sqlite_vec_probe` 缺少扩展 dylib 跳过。包含 R03/R05 与 Writer 证据隔离回归；其后的固定范围补测与本轮有重叠，不另加到总数。 |
| LSTM 训练/评估实跑 | 9 个训练/评估运行完成，全部 shadow | 合成 18 名学生、432 条事件；seed 17/29/43 × student/time/family 三种划分，各 3 epoch。实际梯度参数变化、NumPy/PyTorch h/c 对齐；部分 time 划分不优于 EvidenceTracker。报表 `/tmp/mathtutor-dkt-v2.Ec8WBL/final/evaluation-report.json` 明确 learning_effect_verified=false，仅证明工程训练管道可运行。 |

### 三条真实前端演示

| 路径 | 本批状态 | 验收时必须记录 |
|---|---|---|
| 1. 自然语言独立答对→迁移练习 | 已通过 | `2x+3=7` 首次答 `x=2` → A1 → 接受子题 `3x-5=4`；重启后仍保留 child 焦点与历史。 |
| 2. 持续卡住→局部示范/补基础→返回原题 | 已通过 | 父题 `3x+2=11` 两次困惑后展示验证移项 `3x-9=0`；错误 `3x=13` 后真实 C。子题 `x+2=7` 不先展示答案，答 `x=5` 独立计数 1；返回父题仍 awaiting_retry、受助 1/独立 0、原目标保留。 |
| 3. 点击完整答案→同构检测→证据分流 | 已通过（零提示版本，需按新门槛重验） | `4x-1=19` 零提示真实点击完整答案，显示 `x=5` 与 B；复述 `x=5` 后 post_solution 1/独立 0；接受 `3x-2=16`，首次答 `x=6` 独立 1并产生 A1。 |

以上由真实浏览器操作验证，使用隔离数据库 `/tmp/mathtutor-v2-ui.BtAUfM/math_tutor.db`。数据库复查确认三条 UI 帮助的 help_presented ACK；路径 3 的目标答案暴露、原题 post_solution 和新题 independent 均真实落库。另用“这个我听不懂，是什么意思”进入同题讲解；“我不太懂”在 `5x+1=26` 进入 `5x-25=0` 的已验证局部示范，两条也有实际呈现 ACK。该 UI 会话未配置模型，语义来源为离线规则。LLM 语义调用链由可控 Provider 自动回归验证，不将其写成真实模型质量评测。
