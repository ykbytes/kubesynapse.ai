import { useEffect, useRef, type ReactNode } from "react";

/**
 * Focus trap for modals, drawers, and dialogs.
 * WCAG 2.1 AA 2.4.3 (Focus Order), 2.1.1 (Keyboard).
 *
 * Usage:
 *   <FocusTrap active={isOpen}>
 *     <dialog>...</dialog>
 *   </FocusTrap>
 */

interface FocusTrapProps {
  active: boolean;
  children: ReactNode;
  initialFocusSelector?: string;
  onEscape?: () => void;
}

export function FocusTrap({ active, children, initialFocusSelector, onEscape }: FocusTrapProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!active || !containerRef.current) return;

    const container = containerRef.current;
    const focusableSelector =
      'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

    // Focus initial element or first focusable
    const initialTarget = initialFocusSelector
      ? (container.querySelector(initialFocusSelector) as HTMLElement | null)
      : null;
    const firstFocusable = container.querySelector(focusableSelector) as HTMLElement | null;

    if (initialTarget) {
      initialTarget.focus();
    } else if (firstFocusable) {
      firstFocusable.focus();
    }

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && onEscape) {
        onEscape();
        return;
      }

      if (e.key !== "Tab") return;

      const focusableElements = container.querySelectorAll(focusableSelector);
      if (focusableElements.length === 0) return;

      const first = focusableElements[0] as HTMLElement;
      const last = focusableElements[focusableElements.length - 1] as HTMLElement;

      if (e.shiftKey) {
        if (document.activeElement === first) {
          e.preventDefault();
          last.focus();
        }
      } else {
        if (document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [active, initialFocusSelector, onEscape]);

  if (!active) return <>{children}</>;

  return <div ref={containerRef}>{children}</div>;
}
