import { useEffect, useState } from "react";

/**
 * ARIA live region for announcing dynamic content updates to screen readers.
 * WCAG 2.1 AA 4.1.3 (Status Messages).
 *
 * Usage:
 *   import { announceToScreenReader } from "./AriaLiveRegion";
 *   announceToScreenReader("Agent deployed successfully");
 */

let globalAnnounce: ((message: string, priority?: "polite" | "assertive") => void) | null = null;

export function announceToScreenReader(message: string, priority: "polite" | "assertive" = "polite") {
  if (globalAnnounce) {
    globalAnnounce(message, priority);
  }
}

export function AriaLiveRegion() {
  const [politeMessage, setPoliteMessage] = useState("");
  const [assertiveMessage, setAssertiveMessage] = useState("");
  const [politeKey, setPoliteKey] = useState(0);
  const [assertiveKey, setAssertiveKey] = useState(0);

  useEffect(() => {
    globalAnnounce = (message: string, priority: "polite" | "assertive" = "polite") => {
      if (priority === "assertive") {
        // Clear first to re-trigger announcement for repeated messages
        setAssertiveMessage("");
        setTimeout(() => {
          setAssertiveMessage(message);
          setAssertiveKey((k) => k + 1);
        }, 50);
      } else {
        setPoliteMessage("");
        setTimeout(() => {
          setPoliteMessage(message);
          setPoliteKey((k) => k + 1);
        }, 50);
      }
    };
    return () => {
      globalAnnounce = null;
    };
  }, []);

  return (
    <>
      {/* Polite: announced after current screen reader utterance finishes */}
      <div
        key={`polite-${politeKey}`}
        role="status"
        aria-live="polite"
        aria-atomic="true"
        className="sr-only"
      >
        {politeMessage}
      </div>
      {/* Assertive: interrupts current screen reader utterance */}
      <div
        key={`assertive-${assertiveKey}`}
        role="alert"
        aria-live="assertive"
        aria-atomic="true"
        className="sr-only"
      >
        {assertiveMessage}
      </div>
    </>
  );
}
