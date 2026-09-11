import type { StudentFrame, TutorMessage } from "../types";

export interface PendingPresentation { deliveryId: string; turnId: string; messageId: string; }

export function presentationFromFrame(frame: StudentFrame): PendingPresentation | null {
  if (!frame.delivery_id || !["assistant_complete", "assistant_partial", "turn_end"].includes(frame.event_type)) return null;
  if (!frame.payload.turn_id && !frame.payload.message_id) return null;
  return {deliveryId: frame.delivery_id, turnId: frame.payload.turn_id || "", messageId: frame.payload.message_id || ""};
}

/** A mounted, visible terminal result can be acknowledged as presented only. */
export function presentationAcknowledgement(pending: PendingPresentation, messages: TutorMessage[], visible: boolean): string | null {
  if (!visible) return null;
  const rendered = messages.some(message => message.kind === "tutor" && message.text.trim()
    && ["COMPLETED", "PARTIAL"].includes(message.status || "")
    && ((pending.messageId && message.id === pending.messageId) || (pending.turnId && message.turnId === pending.turnId)));
  return rendered ? JSON.stringify({type: "delivery_presented", delivery_id: pending.deliveryId}) : null;
}
