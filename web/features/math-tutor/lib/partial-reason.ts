const reasons: Record<string, string> = {
  STEP_CAP: "本轮处理次数已达到上限。",
  TOKEN_LIMIT: "本轮回答长度已达到上限。",
  COST_LIMIT: "本轮用量已达到设置上限。",
  TIMEOUT: "模型响应超时。",
  PROVIDER_ERROR: "模型服务暂时不可用。",
  STREAM_INTERRUPTED: "回答传输中断。",
  USER_CANCELLED: "已按你的要求停止生成。",
  INVALID_TOOL_SEQUENCE: "本轮处理未能继续。",
  INTERNAL_ERROR: "本轮处理发生错误。",
};

export function partialReason(reason?: string): string {
  return reason && Object.hasOwn(reasons, reason) ? reasons[reason] : "";
}
