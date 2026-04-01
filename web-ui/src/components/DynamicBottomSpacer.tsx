import { useEffect, useRef, useState } from "react";

/**
 * A spacer that pushes the first message down when the thread is short,
 * giving a centered/fresh-chat feel (inspired by Onyx's DynamicBottomSpacer).
 *
 * When messages fill the viewport, the spacer shrinks to 0.
 * Uses ResizeObserver for responsive adaptation.
 */
export function DynamicBottomSpacer({ minHeight = 0 }: { minHeight?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const [height, setHeight] = useState(200);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    // Calculate available space: parent viewport height - content above
    const recalc = () => {
      const parent = el.closest("[data-radix-scroll-area-viewport]") as HTMLElement | null;
      if (!parent) return;

      const contentContainer = el.parentElement;
      if (!contentContainer) return;

      // Total height of all siblings (messages)
      let contentHeight = 0;
      for (const child of Array.from(contentContainer.children)) {
        if (child !== el) contentHeight += child.getBoundingClientRect().height;
      }

      const viewportHeight = parent.clientHeight;
      const gap = Math.max(minHeight, viewportHeight - contentHeight - 32); // 32px breathing room
      setHeight(Math.max(0, gap));
    };

    const observer = new ResizeObserver(recalc);
    const parent = el.closest("[data-radix-scroll-area-viewport]") as HTMLElement | null;
    if (parent) observer.observe(parent);
    observer.observe(el.parentElement!);

    recalc();
    return () => observer.disconnect();
  }, [minHeight]);

  return (
    <div
      ref={ref}
      className="shrink-0 transition-[height] duration-300 ease-out"
      style={{ height: `${height}px` }}
      aria-hidden="true"
    />
  );
}
