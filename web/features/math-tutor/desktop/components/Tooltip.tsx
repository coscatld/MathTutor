"use client";

import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

type Side = "top" | "right" | "bottom" | "left";
type Position = { left: number; top: number; side: Side; ready: boolean };

const VIEWPORT_PADDING = 10;
const GAP = 8;

export default function Tooltip({
  label,
  children,
  side = "bottom",
  wrapperClassName = "inline-flex",
}: {
  label: string;
  children: React.ReactNode;
  side?: Side;
  wrapperClassName?: string;
}) {
  const id = useId();
  const triggerRef = useRef<HTMLSpanElement>(null);
  const tooltipRef = useRef<HTMLSpanElement>(null);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<Position>({ left: 0, top: 0, side, ready: false });

  const cancelClose = useCallback(() => {
    if (closeTimer.current !== null) {
      clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
  }, []);
  const enter = useCallback(() => {
    cancelClose();
    setOpen(true);
  }, [cancelClose]);
  const leave = useCallback(() => {
    cancelClose();
    closeTimer.current = setTimeout(() => setOpen(false), 120);
  }, [cancelClose]);

  const updatePosition = useCallback(() => {
    const trigger = triggerRef.current;
    const tip = tooltipRef.current;
    if (!trigger || !tip) return;
    const anchor = trigger.getBoundingClientRect();
    const box = tip.getBoundingClientRect();
    const candidates: Record<Side, { left: number; top: number }> = {
      bottom: { left: anchor.left + (anchor.width - box.width) / 2, top: anchor.bottom + GAP },
      top: { left: anchor.left + (anchor.width - box.width) / 2, top: anchor.top - box.height - GAP },
      right: { left: anchor.right + GAP, top: anchor.top + (anchor.height - box.height) / 2 },
      left: { left: anchor.left - box.width - GAP, top: anchor.top + (anchor.height - box.height) / 2 },
    };
    const order = [side, "bottom", "left", "right", "top"].filter(
      (value, index, values): value is Side => values.indexOf(value) === index,
    );
    const fits = ({ left, top }: { left: number; top: number }) =>
      left >= VIEWPORT_PADDING && top >= VIEWPORT_PADDING &&
      left + box.width <= window.innerWidth - VIEWPORT_PADDING &&
      top + box.height <= window.innerHeight - VIEWPORT_PADDING;
    const chosenSide = order.find((candidate) => fits(candidates[candidate])) ?? side;
    const chosen = candidates[chosenSide];
    setPosition({
      left: Math.min(Math.max(chosen.left, VIEWPORT_PADDING), Math.max(VIEWPORT_PADDING, window.innerWidth - box.width - VIEWPORT_PADDING)),
      top: Math.min(Math.max(chosen.top, VIEWPORT_PADDING), Math.max(VIEWPORT_PADDING, window.innerHeight - box.height - VIEWPORT_PADDING)),
      side: chosenSide,
      ready: true,
    });
  }, [side]);

  useLayoutEffect(() => {
    if (open) updatePosition();
  }, [open, label, updatePosition]);

  useEffect(() => {
    if (!open) return;
    const update = () => updatePosition();
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    window.addEventListener("keydown", escape);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
      window.removeEventListener("keydown", escape);
    };
  }, [open, updatePosition]);

  useEffect(() => () => cancelClose(), [cancelClose]);

  return (
    <span ref={triggerRef} className={wrapperClassName} onPointerEnter={enter} onPointerLeave={leave} onFocus={enter} onBlur={leave} aria-describedby={open ? id : undefined}>
      {children}
      {open && typeof document !== "undefined" ? createPortal(
        <span
          ref={tooltipRef}
          id={id}
          role="tooltip"
          data-side={position.side}
          onPointerEnter={enter}
          onPointerLeave={leave}
          className="fixed z-[100] block max-w-[280px] whitespace-normal break-words rounded-lg bg-[#1f2933] px-3 py-2 text-xs leading-5 text-white shadow-xl"
          style={{
            left: position.left,
            top: position.top,
            maxWidth: Math.max(0, Math.min(280, window.innerWidth - VIEWPORT_PADDING * 2)),
            visibility: position.ready ? "visible" : "hidden",
          }}
        >{label}</span>,
        document.body,
      ) : null}
    </span>
  );
}
