import { useCallback, useEffect, useRef, useState } from "react";
import type { UiTodo } from "../types";

/**
 * Dock state machine for the plan panel.
 *
 * States:
 * - "hide"  — no todos, panel invisible
 * - "open"  — busy with todos, panel visible
 * - "close" — all done while busy, hold briefly then hide
 * - "clear" — idle with todos, schedule clear then hide
 */
export type DockState = "hide" | "open" | "close" | "clear";

interface UsePlanDockOptions {
  todos: UiTodo[];
  isSending: boolean;
  /** Delay in ms before auto-hiding after completion (default: 400) */
  closeDelay?: number;
  /** Delay in ms before clearing idle todos (default: 400) */
  clearDelay?: number;
}

export interface PlanDockResult {
  /** Current dock state */
  dockState: DockState;
  /** Whether the panel content is visible (open or close states) */
  visible: boolean;
  /** Whether the user has manually overridden visibility */
  manualOverride: boolean;
  /** Toggle panel visibility (user action) */
  toggle: () => void;
  /** Force open the panel */
  forceOpen: () => void;
}

function computeDockState(count: number, done: number, isSending: boolean): DockState {
  if (count === 0) return "hide";
  if (!isSending) return "clear";
  if (done === count) return "close";
  return "open";
}

export function usePlanDock({
  todos,
  isSending,
  closeDelay = 400,
  clearDelay = 400,
}: UsePlanDockOptions): PlanDockResult {
  const [visible, setVisible] = useState(false);
  const [manualOverride, setManualOverride] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const prevCountRef = useRef(0);

  const count = todos.length;
  const done = todos.filter((t) => t.status === "completed" || t.status === "cancelled").length;
  const state = computeDockState(count, done, isSending);

  // Clear any pending timer on unmount
  useEffect(() => () => {
    if (timerRef.current) clearTimeout(timerRef.current);
  }, []);

  useEffect(() => {
    // Clear previous timer
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }

    if (state === "hide") {
      setVisible(false);
      setManualOverride(false);
      return;
    }

    if (state === "open") {
      // Auto-open when first todo arrives (unless user manually closed)
      if (!manualOverride) {
        setVisible(true);
      }
      // Also auto-open on first todo if count went from 0 to >0
      if (prevCountRef.current === 0 && count > 0) {
        setVisible(true);
        setManualOverride(false);
      }
      prevCountRef.current = count;
      return;
    }

    if (state === "close") {
      // All done while still sending — hold visible briefly then auto-hide
      timerRef.current = setTimeout(() => {
        if (!manualOverride) setVisible(false);
      }, closeDelay);
      prevCountRef.current = count;
      return;
    }

    if (state === "clear") {
      // Idle with todos — hold visible briefly then hide
      timerRef.current = setTimeout(() => {
        setVisible(false);
        setManualOverride(false);
      }, clearDelay);
      prevCountRef.current = count;
      return;
    }

    prevCountRef.current = count;
  }, [state, count, done, manualOverride, closeDelay, clearDelay]);

  const toggle = useCallback(() => {
    setManualOverride(true);
    setVisible((v) => !v);
  }, []);

  const forceOpen = useCallback(() => {
    setManualOverride(false);
    setVisible(true);
  }, []);

  return {
    dockState: state,
    visible,
    manualOverride,
    toggle,
    forceOpen,
  };
}
