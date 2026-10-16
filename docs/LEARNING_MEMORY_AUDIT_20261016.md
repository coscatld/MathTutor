# 学习记忆实际链路检查（2026-10-16）

本轮检查覆盖界面保存所调用的 HTTP API、真实 SQLite 持久化、WebSocket 回答、模型实际收到的消息和关闭模型后的模板回答。所有模型响应由本地测试替身提供，没有调用付费模型，也没有重新生成或修改基准成绩。

## 发现与修复

原有记忆增删改、检索开关、AI 推测确认和数据库 owner 隔离已经存在。但是普通对话没有读取记忆；结构化辅导虽然在上下文组装时读取了记忆，最终只把文档资料交给 writer，丢弃了记忆。因此，列表中显示“已启用”原本不能证明记忆影响了回答。

现已让普通对话与结构化辅导共同使用 `PersonalMemorySourceProvider` 的只读、类型化投影。普通对话通过独立的参考数据消息传入；结构化辅导通过 `PublicProblemView.personal_memory` 传给模型 writer。练习生成继续使用同一 provider 和原有上下文组装链路。数学修复保留本轮投影；用户发起下一轮或续写时重新读取开关和内容。

输出链路直接调用 provider 的 `load_for_tutor(student_id)`，不解析检索策略矩阵，也不声称 `SOLVE_PROBLEM` 策略行已经投入生产。`ContextAssembler` 的 `load(student_id, intent, ...)` 在自身完成来源策略判定后，委托同一个只读实现。检索矩阵的生产范围保持为原有的练习生成、请求提示和解释概念；用户记忆开关与 owner 隔离由共享数据层在两条入口统一执行。

原实现按创建顺序只取最早 20 条，新增及近期修改的记忆可能一直无法参与回答。现按最近修改顺序选择，最多 20 条、总计 4,800 个投影 JSON 字符，每条最多 1,600 字符。超出预算的整条记录暂不注入，不切断原句或条件；数据库内容不变。诊断的 `detail` 记录候选与选入数量，不能把“启用”理解为每条都会在每轮使用。

## 使用边界

- 只有 `USER_EXPLICIT` 和 `USER_CONFIRMED` 会参与回答。未确认的 `MODEL_INFERRED` 留在管理列表，可确认或删除，确认前不作为用户事实注入。
- 记忆只作为表达偏好、目标和备注。当前请求的语言、长度、格式和提示/完整解答要求优先于旧偏好；记忆不能改变数学验证结果、教学披露许可或学生掌握度。
- 使用、关闭或删除记忆均不写入学习证据。掌握度仍由独立作答和正式评估链路决定。
- 读取遵守 owner、`retrieval_enabled` 和软删除；修改、关闭或删除后，下一轮不再新增注入旧内容。已经出现在真实聊天正文中的旧内容仍属于聊天历史，记忆删除不是聊天历史擦除。
- 模型不可用时，结构化辅导使用确定性模板。模板不会解释任意自由文本偏好，也不会因为记忆声称“已掌握”就给出完整答案。界面不应声称所有偏好必然改变每次离线输出。
- 这一轮证明上下文已真正送达模型，并检查数据与权限边界。没有用在线模型验证长期教学收益，也不能保证任何外部模型都会完全遵循所有偏好。

## 可复查证据

`tests/test_memory_output_integration.py` 经真实 HTTP、SQLite、进程重建与 WebSocket 捕获模型输入，覆盖：

1. 主动保存、重启恢复、同一会话中的禁用/启用/修改/删除；不把旧记忆作为隐藏上下文保留。
2. 其他 owner 的内容既不出现在列表，也不出现在模型消息。
3. AI 推测确认前不注入、确认后结构化提示模型收到 `USER_CONFIRMED`；其他 owner 不能确认。
4. 已有超过 20 条记忆时，新保存或新修改的偏好仍能进入实际 prompt；过大记录整条跳过。
5. 当前英文、两句限制、只给提示等约束与数学修复共同保留；中文提示请求在续写时仍保留，新修改记忆会重新读取。
6. 长历史不会挤掉本轮记忆、文档与学生当前问题。
7. 不新增 `mastery_evidence`，离线模板不接受记忆授予完整解答许可。

诊断可通过已有 `/api/v2/math-tutor/desktop/diagnostics/turns` 查看 `details.memory`：`status`、`included_count`、`memory_ids` 和选择说明。这里不保存记忆正文。它证明投影读取，外部模型最终是否充分使用仍需结合实际回答判断。

运行命令：

```bash
python -m pytest tests/test_memory_output_integration.py tests/test_personal_memory.py tests/test_context_assembler.py tests/test_chat_document_context.py tests/test_tutor_output_contract_integration.py -q
```
