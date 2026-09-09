"""Bounded Tutor expression runtime, task-local context and process health metrics."""
from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter
from contextvars import ContextVar

from mathtutor.domain.turn_result import FinishReason, TutorTurnResult

continuation_text: ContextVar[str] = ContextVar('continuation_text', default='')

current_turn: ContextVar[TutorTurnResult | None] = ContextVar('tutor_turn', default=None)
health = Counter()


def record_turn(turn):
    health['turns'] += 1
    health[turn.finish_reason.value] += 1
    health['partial'] += int(turn.partial)
    health['grace'] += int(turn.grace_call_used)
    health['steps'] += turn.steps_used
    health['loop_step_cap_hit_total'] += int(turn.finish_reason == FinishReason.STEP_CAP)
    data = turn.wire()
    data.pop('final_text')
    logging.getLogger(__name__).info('tutor_turn %s', json.dumps(data, ensure_ascii=False))


def loop_health():
    n = max(1, health['turns'])
    return {**{name: health[key] / n for name, key in {
        'natural_stop_rate': 'NATURAL_STOP', 'final_answer_rate': 'FINAL_ANSWER',
        'grace_call_rate': 'grace', 'step_cap_rate': 'STEP_CAP',
        'token_limit_rate': 'TOKEN_LIMIT', 'partial_turn_rate': 'partial',
        'provider_error_rate': 'PROVIDER_ERROR', 'average_steps_per_turn': 'steps',
    }.items()}, 'loop_step_cap_hit_total': health['loop_step_cap_hit_total']}


async def complete_tutor(provider, messages, *, max_tokens, temperature, max_retries=0):
    """Non-streaming providers: retain reasons and allow one finalizing call.

    No tool execution is authorized by this expression-only runtime. Unknown
    reasons fail closed. Missing usage uses a conservative UTF-8 byte estimate.
    """
    turn = current_turn.get() or TutorTurnResult()
    turn.provider = getattr(provider, "provider_id", "")
    turn.model = getattr(provider, "model", "")
    messages = list(messages)
    previous = continuation_text.get()
    if previous:
        messages.extend([{'role': 'assistant', 'content': previous}, {'role': 'user', 'content': '接着这条未完成回答继续，只输出后续部分，不重复前文。保持原来的披露范围。'}])
    prior_text = previous
    if not prior_text and messages and messages[-1].get('content', '').strip() == '继续':
        prior_text = next((m['content'] for m in reversed(messages[:-1]) if m.get('role') == 'assistant'), '')
    text = ''
    if turn.steps_used >= turn.max_steps:
        turn.stop(FinishReason.STEP_CAP, turn.final_text)
        raise RuntimeError('Tutor step budget exhausted')
    result = None
    while turn.steps_used < turn.max_steps:
        remaining = turn.max_total_tokens - turn.input_tokens - turn.output_tokens
        prompt_estimate = sum(len(str(m.get('content', '')).encode('utf-8')) + 16 for m in messages)
        allowance = min(max_tokens or 512, remaining - prompt_estimate)
        if allowance <= 0:
            turn.stop(FinishReason.TOKEN_LIMIT, text)
            break
        if turn.steps_used == turn.max_steps - 1 or remaining < 2 * (prompt_estimate + allowance):
            turn.grace_call_used = True
            messages.append({'role': 'system', 'content': '这是最后一次回答机会。不要调用工具或开始新的任务。接着已有回答完成可靠结论，不要重复前文；明确尚未完成的部分。'})
            prompt_estimate = sum(len(str(m.get("content", "")).encode("utf-8")) + 16 for m in messages)
            allowance = min(allowance, remaining - prompt_estimate)
            if allowance <= 0:
                turn.stop(FinishReason.TOKEN_LIMIT, text)
                break
        turn.steps_used += 1
        try:
            result = await asyncio.wait_for(provider.complete(messages, temperature=temperature,
                max_tokens=allowance, max_retries=0), timeout=60)
        except asyncio.CancelledError:
            turn.stop(FinishReason.USER_CANCELLED, text)
            raise
        except Exception as exc:
            import httpx
            timed_out = isinstance(exc, (TimeoutError, httpx.TimeoutException)) or isinstance(exc.__cause__, httpx.TimeoutException)
            turn.stop(FinishReason.TIMEOUT if timed_out else FinishReason.PROVIDER_ERROR, text)
            if result is None:
                raise
            break
        turn.provider, turn.model = result.provider_id, result.model
        turn.input_tokens += result.input_tokens if result.input_tokens is not None else prompt_estimate
        turn.output_tokens += result.output_tokens if result.output_tokens is not None else len(result.text.encode('utf-8'))
        turn.usage_estimated |= result.input_tokens is None or result.output_tokens is None
        addition = result.text
        prefix = text or prior_text
        if prefix and addition.startswith(prefix):
            addition = addition[len(prefix):]
        elif prefix:
            for size in range(min(len(prefix), len(addition)), 11, -1):
                if prefix.endswith(addition[:size]):
                    addition = addition[size:]
                    break
        text += addition
        reason = result.finish_reason
        if turn.input_tokens + turn.output_tokens > turn.max_total_tokens:
            turn.stop(FinishReason.TOKEN_LIMIT, text)
            break
        if reason in {'stop', 'end_turn', 'stop_sequence'}:
            turn.stop(FinishReason.NATURAL_STOP, text)
            break
        if reason not in {'length', 'max_tokens'}:
            turn.stop(FinishReason.INVALID_TOOL_SEQUENCE if reason == 'tool_calls' else FinishReason.STREAM_INTERRUPTED, text)
            break
        turn.stop(FinishReason.TOKEN_LIMIT, text)
        messages.extend([{'role': 'assistant', 'content': addition}, {'role': 'user', 'content': '从中断处继续，不重复已有内容。'}])
    else:
        if turn.finish_reason != FinishReason.TOKEN_LIMIT:
            turn.stop(FinishReason.STEP_CAP, text)
    if result is None:
        raise RuntimeError('Tutor turn budget exhausted')
    return result.model_copy(update={'text': text, 'turn_result': turn.wire()})


async def complete_auxiliary(provider, messages, *, temperature, max_tokens, max_retries):
    """Charge auxiliary generation to the same turn without treating it as final output.

    Structured candidate/practice responses cannot be given the Tutor's prose
    grace instruction. They retain their existing deterministic fallback path.
    """
    turn = current_turn.get()
    if turn is None:
        return await provider.complete(messages, temperature=temperature, max_tokens=max_tokens, max_retries=max_retries)
    if turn.steps_used >= turn.max_steps:
        turn.stop(FinishReason.STEP_CAP, turn.final_text)
        raise RuntimeError('Tutor step budget exhausted')
    estimate = sum(len(str(m.get('content', '')).encode('utf-8')) + 16 for m in messages)
    available = turn.max_total_tokens - turn.input_tokens - turn.output_tokens - estimate
    if available <= 0:
        turn.stop(FinishReason.TOKEN_LIMIT, turn.final_text)
        raise RuntimeError('Tutor token budget exhausted')
    turn.steps_used += 1
    if not turn.provider:
        turn.provider, turn.model = getattr(provider, 'provider_id', ''), getattr(provider, 'model', '')
    try:
        result = await asyncio.wait_for(provider.complete(messages, temperature=temperature,
            max_tokens=min(max_tokens or 512, available), max_retries=0), timeout=60)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        import httpx
        timed_out = isinstance(exc, (TimeoutError, httpx.TimeoutException)) or isinstance(exc.__cause__, httpx.TimeoutException)
        turn.stop(FinishReason.TIMEOUT if timed_out else FinishReason.PROVIDER_ERROR, turn.final_text)
        raise
    turn.input_tokens += result.input_tokens if result.input_tokens is not None else estimate
    turn.output_tokens += result.output_tokens if result.output_tokens is not None else len(result.text.encode('utf-8'))
    turn.usage_estimated |= result.input_tokens is None or result.output_tokens is None
    if turn.input_tokens + turn.output_tokens > turn.max_total_tokens:
        turn.stop(FinishReason.TOKEN_LIMIT, turn.final_text)
        raise RuntimeError('Tutor token budget exhausted')
    if result.finish_reason in {'length', 'max_tokens'}:
        turn.stop(FinishReason.TOKEN_LIMIT, turn.final_text)
    return result
