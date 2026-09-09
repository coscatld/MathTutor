# Tutor Loop 审计与修复

审计日期：2026-09-09。基于本轮开始时的工作区（其中已有大量未提交修改），先读取并报告原逻辑，再实施修复。没有重置用户原有改动。

## 原始调用链与实际停止条件

```text
ChatComposer → useMathTutorSession.send → WebSocket
→ math_tutor_ws._normalize_message → MathTutorController.run
  ├─ send_message / 意图路由 → TutorChatResponder.respond
  │  → GenerativeModelGateway → OpenAICompatibleProvider / OllamaProviderAdapter
  └─ 显式教学命令 → Planner → 确定性 State Machine
     → DisclosureProjector → LLMTutorWriter / TemplateTutorWriter → OutputGuard
→ MathTutorEventStream → StudentPublicEvent
→ ConversationRepository → 前端协议投影 → reducer → TutorActionCard
```

原始伪代码：

```python
while websocket_connected:  # 这是接收用户消息的循环，不是 LLM tool loop
    request = receive_and_validate()
    if general_chat:
        try:
            result = gateway.complete(max_tokens=512, max_retries=0)
            text = result.text.strip()  # finish_reason 未使用
        except Exception:
            text = local_fallback()
    else:
        action = planner.plan()
        state_machine.step()
        raw = await wait_for(writer_client.complete(max_tokens=1024), timeout=120)
        # GatewayRoleClient.complete 仅返回 str；Writer 异常回退到模板
        text = guard(raw_or_template)
    emit_public_content(text)
    persist_as_normal_tutor_message(text)
    send(turn_end)
```

每个表达调用只尝试一次；Provider 成功返回、Writer 超时/异常回退、Controller 捕获状态异常都会结束当前处理。模型的 `stop` 不会触发额外模型调用，因为原先没有工具循环。`StagePolicy.max_steps_per_turn` 限制教学披露步骤，不是 LLM iteration cap。Provider 请求是完整 HTTP 响应，Ollama 明确使用 `stream=False`；WebSocket 原本传输整块内容，并非 token stream。

## 五种停止机制：修复前

| 机制 | 判定 | 证据与位置 |
|---|---|---|
| Model-driven stop | PARTIAL | `infrastructure/generative_gateway.py` 的两种 Provider 保留 `finish_reason` / `done_reason`；`tutor_chat.py:respond` 只取 text；`GatewayRoleClient.complete` 丢弃元数据；WS 不读取模型原因 |
| Grace Call | MISSING | `tutor_chat.py:respond` 与 `pedagogy/tutor_writer.py:write` 均是一次调用后直接返回 |
| Step Cap | PARTIAL | 固定一次表达调用构成隐式上界；没有模型步骤计数、明确 STEP_CAP 结果或指标；状态机步骤不是模型循环 |
| Token Budget | PARTIAL | chat 512、Writer 默认 1024 为单次输出上限；没有整轮 input/output usage 聚合 |
| Cost Budget | MISSING | 无可靠模型价格表，无实际成本统计 |

## “回答一半停止”的证据与排查结论

确认的代码路径：Provider 返回 `finish_reason=length` → Chat 只拿 text / Writer 的字符串适配器丢失原因 → guard 不负责完成性 → WS 保存普通 tutor 消息 → `turn_end` 清除 pending。**截断被误当作完整回答**。本次没有提高原来的 512/1024 输出上限。

附件未包含实际截图、对应 conversation/turn ID 或运行日志，而且 CASE C 文本在公式后截断。因此可以确认并复现代码缺陷，不能声称已证明某一次截图的具体网络或 Provider 根因。

| 排查项 | 结论 |
|---|---|
| max_tokens 太小 | 512 可能截断长回复；真正的完成性缺陷是未检查 length |
| Gateway 丢原因 | Writer 字符串适配器存在此问题，已新增结构化接口并切换 Writer |
| streaming 提前关闭 | 上游不是 token stream；下游 socket 中断原先无消息状态 |
| HTTP timeout | Provider 有 HTTP timeout；Writer 另有 120 秒默认总调用超时；原先回退掩盖结果原因 |
| AbortController | 当前聊天 hook 没有 fetch streaming / AbortController |
| 路由离开 | hook cleanup 关闭 WS；现在服务器取消活动任务、前端不将断线当完成 |
| step cap | 原先无模型工具循环，也没有明确 step-cap 退出结果 |
| token cap | 仅单次输出限制，没有整轮总预算 |
| tool finalization | 当前产品工具 allowlist 为空，工具由确定性服务调用，模型无权执行工具 |
| State Machine 异常 | Controller 捕获异常发送错误；现在具有单独终态 |
| turn_end 提前 | 原逻辑在 controller task 后发，但该 task 不检查模型完成原因；所以是语义过早 |
| reducer 把 partial 当完成 | 没有 status 字段，turn_end 仅清 pending；现在只有明确完成事件才能 COMPLETED |
| length 当 stop | 确认，是主要可复现路径 |
| catch 后静默 | Chat/Writer 回退未留下统一失败原因；现在由 runtime 保留原因 |
| final buffer 未 flush | 上游无 token buffer；现在 terminal 仅使用投影/guard 后的安全文本，保存后才发送终态 |

## 修复后的完成契约与运行边界

- `src/mathtutor/domain/turn_result.py:8`：统一 FinishReason；`TutorTurnResult` 包含 status、final_text、usage、steps/max_steps、partial、error_code、耗时与来源。
- `src/mathtutor/application/tutor_runtime.py:40`：有限表达循环。默认 `max_steps=2`，来自原有“一次表达调用 + 一次收尾”的架构；整轮默认 16384 token 预算。单次输出上限保持原值。每次调用最长 60 秒，Writer 外层仍有其配置的总超时。
- `src/mathtutor/infrastructure/generative_gateway.py:56`：原始 Provider 原因与 input/output usage 保留；`GatewayRoleClient.complete_result` 提供结构化返回。非 Tutor 的兼容字符串接口保留。
- `complete_auxiliary`：同一任务上下文中的候选/练习生成也计入整轮步骤与 token 总量；结构化辅助生成不能接受 Tutor 的自由文本收尾指令，保留其原有确定性回退。
- 正常 `stop/end_turn/stop_sequence` 结束；`length/max_tokens` 允许剩余预算内一次 Grace。未知/缺失原因不能认作完成；当前不授权的 `tool_calls` 不能触发执行。
- 收尾明确禁止新工具和探索，要求只继续剩余内容并说明未完成部分。第二次仍截断为 `PARTIAL + TOKEN_LIMIT`。后续调用被步骤硬上限拒绝为 STEP_CAP。
- 真实 usage 优先；缺失时用 UTF-8 字节数加消息开销做保守代理估计，并标记 `usage.estimated=true`。这不是声称掌握该 Provider 的准确 tokenizer。
- 无价格表，因此 `estimated_cost=None`；COST_LIMIT 预留枚举，无虚构金额或成本限制执行器。
- `FINAL_ANSWER` 表示服务端明确交付的确定性最终输出。没有实现真实 `final_answer` 工具：当前架构刻意禁止 LLM 工具调用，也必须兼容 Ollama。统一结构化结果是这里的 fallback 合约。

```python
turn = TutorTurnResult(max_steps=2, max_total_tokens=16384)
for each_authorized_generation:
    enforce_remaining_steps_and_tokens()
    if tutor_expression:
        while steps_remain:
            if last_step_or_budget_near_limit:
                add_grace_instruction()
            result = call_model_with_bounded_timeout()
            aggregate_usage()
            if natural_stop:
                finalize(NATURAL_STOP)
                break
            if token_truncated and budget_remains:
                append_partial_as_context()
                continue
            finalize_partial_or_failure(reason)
            break
    else:
        run_bounded_structured_auxiliary_generation()
project_and_guard_visible_text()
persist_message_with_explicit_status()
emit_assistant_complete_or_partial_or_error()
```

## 传输、恢复与取消

`src/mathtutor/api/math_tutor_ws.py` 现在发送：

```text
assistant_start
旧 tutor/state 事件（保留状态机协议兼容；新客户端不重复渲染其正文）
assistant_delta（当前 Provider 缓冲返回，故通常是一次完整的 guarded 文本 delta）
持久化
assistant_complete / assistant_partial / assistant_error
turn_end（兼容边界标记，不是完成证明）
```

事件携带 conversation_id / turn_id；正文另有 message_id。Reducer 合并相同消息的 delta、隔离旧对话事件；连接关闭或仅收到 turn_end 时将未完成正文标为 PARTIAL。最终事件只包含已经通过公开投影/输出 guard 的正文；取消过程中未检查的内部模型缓冲区不会透传。

独立 WS 接收任务允许在模型运行期间接收 `cancel_turn` 并取消当前对话任务。用户取消为 CANCELLED/USER_CANCELLED，断线为 STREAM_INTERRUPTED；没有正文的失败为 FAILED，已经有安全正文的中断为 PARTIAL。当前 Provider 不支持真正逐 token 上游恢复，无法恢复服务器从未收到的网络字节。

`010_turn_completion.py` 为内存/SQLite 同步增加 status、finish_reason、turn_id、continuation_context。旧历史默认 COMPLETED，仅作迁移兼容，无法逆推历史消息是否曾被截断。恢复 GET 保留公开状态，但剔除内部 continuation_context。

“继续生成”只针对最新部分回答显示：

- Chat 使用当前对话历史、原问题和上一条 partial；提示不重复前半段，同时移除确切前缀/长边界重叠。
- 教学回答持久化原动作和 cycle ID，恢复相同披露动作，重新通过 Projector/Writer/Guard；不增加提示等级或推进状态机。旧 cycle 不复用。
- 不承诺能机械消除模型对前文的所有语义改写；精确文本重复有去重，非完全相同的重复仍可能发生。

## Markdown / LaTeX

`web/components/common/MarkdownRenderer.tsx` 原本忽略 enableMath。现在用户/Tutor 共用 `remark-gfm + remark-math + rehype-katex`，加载 KaTeX CSS；Composer 仍保留原文本。

`math-normalization.ts` 支持 `$...$`、`$$...$$`、`\(...\)`、`\[...\]`。代码块/inline code 保留原文；只对独占一行、包含已知 LaTeX 命令且不含明显自然语言的旧方括号表达式做兼容转换。普通数组、链接和中文方括号保持原样。输入中未闭合的数学分隔符不强行修复。

HTML 不启用 raw 解析、设置 skipHtml；KaTeX trust=false，链接使用 react-markdown 的安全 URL 处理。标题、列表、表格、blockquote、code 有共用样式；长公式/代码/表格可水平滚动。Chat/Writer Prompt 加入数学分隔符与自然教学表达要求，移除主动解释内部计算管线的引导。Prompt 只约束呈现，数学与披露检查仍由现有服务/guard 承担。

## Telemetry 与健康指标

`application/tutor_runtime.py:18` 输出 JSON 结构化 turn 日志：ID、provider/model、steps/max_steps、usage/估算标记、finish_reason、status、latency、tool_calls_count、grace_call_used、partial。日志不含 final_text、完整系统提示词或密钥。

`loop_health()` 提供 natural_stop_rate、final_answer_rate、grace_call_rate、step_cap_rate、token_limit_rate、partial_turn_rate、provider_error_rate、average_steps_per_turn 和 loop_step_cap_hit_total。它们是当前进程累计指标，重启清零；未新增持久化指标库或监控 HTTP 路由。实际模型工具调用数为零，与产品当前工具权限一致。

## 验证与剩余验收边界

- 全量后端回归：660 passed、4 skipped（缺少本地 sqlite-vec 探测库）；前端 node：96 passed；桌面分发检查：33 passed、2 skipped；Next 生产构建通过；git diff --check 通过。
- 新增真实 HTTP adapter MockTransport 测试验证 stop/length 与 usage 保留；runtime 测试覆盖自然完成、显式 final output、grace、token/step cap、timeout、provider error、缺失终止原因。
- WebSocket + SQLite 受控 E2E 验证 partial 持久化、原对话继续生成、正常终态与模型运行期间取消。
- 前端 SSR 测试验证两种角色 Markdown、四种数学定界符、代码保留、HTML/危险 URL 防护、保守旧公式规范化；Reducer 测试验证无完成事件不得 COMPLETED、delta 聚合、跨对话隔离、内部命令不展示。
- `test_tool_call_continues_loop` 不适用于当前无工具执行权限的架构；替代测试验证 tool_calls 不能触发执行或伪装成功。没有为了满足测试名称引入通用 tool agent。
- CASE A（17×23）、CASE B（长推导）涉及真实模型输出质量：没有使用用户的真实 API 凭据进行外部模型调用；受控测试证明完成/截断协议，不冒充真实 Provider 验收。
- CASE C 的数学定界符、lim/frac 渲染由同一 renderer 支持；附件后续要求未收到，不推测缺失验收内容。未进行桌面 GUI 截图验收。
