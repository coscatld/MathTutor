/**
 * Human-facing labels for desktop surfaces — Chinese, friendly, and
 * deliberately decoupled from internal codes (labels keyed by known codes
 * only; unknown values fall back to the raw value).
 */

export const MEMORY_TYPE_LABELS: Record<string, string> = {
  learning_preference: "学习偏好",
  expression_preference: "表达偏好",
  learning_goal: "学习目标",
  interest: "兴趣",
  user_note: "个人说明",
  example_preference: "示例偏好",
  learning_scenario: "学习场景",
  ai_inference: "AI 推测",
};

export const MEMORY_SOURCE_LABELS: Record<string, string> = {
  USER_EXPLICIT: "我的记录",
  MODEL_INFERRED: "AI 推测",
  USER_CONFIRMED: "已确认",
};

export const DOCUMENT_STATUS_LABELS: Record<string, string> = {
  importing: "导入中",
  parsing: "解析中",
  ready: "已就绪",
  ready_with_warnings: "已就绪（有空页）",
  needs_ocr: "无文字层",
  failed: "解析失败",
};

export const OFFER_STATUS_LABELS: Record<string, string> = {
  ACTIVE: "可练习",
  ACCEPTED: "已接受",
  EXPIRED: "已过期",
  REVOKED: "已撤回",
};

export const READINESS_LABELS: Record<string, string> = {
  READY: "一切就绪",
  DEGRADED: "部分功能可用",
  BLOCKED: "服务不可用",
};

/** Bootstrap step keys → friendly Chinese names (defensive fallback: the
 * backend supplies its own label; unknown keys render the key verbatim). */
export const BOOTSTRAP_STEP_LABELS: Record<string, string> = {
  check_data_root: "数据目录",
  database: "本地数据库",
  migration: "数据库迁移",
  secret_store: "系统凭据库",
  document_storage: "资料存储",
  curriculum: "课程内容",
  retrieval: "文档检索",
  outbox: "离线同步",
  model_gateway: "AI 模型服务",
};

export const BOOTSTRAP_STEP_STATUS_LABELS: Record<string, string> = {
  ok: "正常",
  degraded: "降级",
  blocked: "不可用",
};

export const BACKUP_INTEGRITY_LABELS: Record<string, string> = {
  ok: "校验通过",
  unknown: "未校验",
};

export function bootstrapStepLabel(key: string, label: string): string {
  return label || BOOTSTRAP_STEP_LABELS[key] || key;
}

export function memoryTypeLabel(memoryType: string): string {
  return MEMORY_TYPE_LABELS[memoryType] ?? memoryType;
}

export function memorySourceLabel(sourceType: string): string {
  return MEMORY_SOURCE_LABELS[sourceType] ?? sourceType;
}

export function documentStatusLabel(status: string): string {
  return DOCUMENT_STATUS_LABELS[status] ?? status;
}

export function offerStatusLabel(status: string): string {
  return OFFER_STATUS_LABELS[status] ?? status;
}

/** Diffulty label for practice offers (public label only). */
export function difficultyLabel(difficulty: string): string {
  const map: Record<string, string> = {
    easy: "入门",
    medium: "进阶",
    hard: "挑战",
  };
  return map[difficulty] ?? difficulty;
}

/** Expiry text for offers, e.g. "3 分钟后过期" / "已过期"。 */
export function offerExpiryLabel(expiresAt: string, nowIso: string = new Date().toISOString()): string {
  const expires = Date.parse(expiresAt);
  if (!Number.isFinite(expires)) return "";
  const now = Date.parse(nowIso);
  const diffMs = expires - (Number.isFinite(now) ? now : Date.now());
  if (diffMs <= 0) return "已过期";
  if (diffMs < 60000) return "即将过期";
  const minutes = Math.ceil(diffMs / 60000);
  if (minutes < 60) return `${minutes} 分钟后过期`;
  const hours = Math.ceil(minutes / 60);
  return `${hours} 小时后过期`;
}
