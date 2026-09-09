"""One output contract; transport closure is never evidence of completion."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum


class FinishReason(StrEnum):
    NATURAL_STOP = 'NATURAL_STOP'
    FINAL_ANSWER = 'FINAL_ANSWER'
    STEP_CAP = 'STEP_CAP'
    TOKEN_LIMIT = 'TOKEN_LIMIT'
    COST_LIMIT = 'COST_LIMIT'
    TIMEOUT = 'TIMEOUT'
    PROVIDER_ERROR = 'PROVIDER_ERROR'
    STREAM_INTERRUPTED = 'STREAM_INTERRUPTED'
    USER_CANCELLED = 'USER_CANCELLED'
    INVALID_TOOL_SEQUENCE = 'INVALID_TOOL_SEQUENCE'
    INTERNAL_ERROR = 'INTERNAL_ERROR'


@dataclass
class TutorTurnResult:
    turn_id: str = ''
    conversation_id: str = ''
    status: str = 'COMPLETED'
    finish_reason: FinishReason = FinishReason.FINAL_ANSWER
    final_text: str = ''
    provider: str = ''
    model: str = ''
    steps_used: int = 0
    max_steps: int = 2  # One normal call and one bounded grace continuation.
    max_total_tokens: int = 16384
    input_tokens: int = 0
    output_tokens: int = 0
    usage_estimated: bool = False
    estimated_cost: float | None = None
    tool_calls_count: int = 0
    grace_call_used: bool = False
    latency_ms: int = 0
    error_code: str | None = None

    @property
    def partial(self):
        return self.status == 'PARTIAL'

    def stop(self, reason: FinishReason, text: str = ''):
        self.finish_reason = reason
        self.final_text = text
        self.status = ('CANCELLED' if reason == FinishReason.USER_CANCELLED else
                       'COMPLETED' if reason in {FinishReason.NATURAL_STOP, FinishReason.FINAL_ANSWER} else
                       'PARTIAL' if text else 'FAILED')

    def wire(self):
        return {**asdict(self), 'partial': self.partial,
                'usage': {'input_tokens': self.input_tokens, 'output_tokens': self.output_tokens,
                          'total_tokens': self.input_tokens + self.output_tokens,
                          'estimated': self.usage_estimated}}


