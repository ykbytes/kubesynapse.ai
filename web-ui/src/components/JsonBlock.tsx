import { CopyButton } from "./CopyButton";

interface JsonBlockProps {
  data: unknown;
  maxHeight?: string;
  className?: string;
}

/**
 * Formatted JSON display with syntax colouring, copy button, and scroll overflow.
 */
export function JsonBlock({ data, maxHeight = "max-h-64", className }: JsonBlockProps) {
  const raw = typeof data === "string" ? data : JSON.stringify(data, null, 2);
  return (
    <div className={`group relative rounded-lg border border-border/50 bg-background/60 ${className ?? ""}`}>
      <div className="absolute top-1.5 right-1.5 opacity-0 group-hover:opacity-100 transition-opacity z-10">
        <CopyButton value={raw} />
      </div>
      <pre
        className={`overflow-auto whitespace-pre-wrap break-words p-3 font-mono text-[11px] leading-relaxed text-muted-foreground ${maxHeight}`}
      >
        {colorize(raw)}
      </pre>
    </div>
  );
}

/* Lightweight JSON syntax colouring via spans */
function colorize(json: string): (string | JSX.Element)[] {
  // Regex to match JSON tokens: strings, numbers, booleans, null
  const TOKEN =
    /("(?:[^"\\]|\\.)*"\s*:)|("(?:[^"\\]|\\.)*")|(\b(?:true|false)\b)|(\bnull\b)|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g;

  const parts: (string | JSX.Element)[] = [];
  let last = 0;
  let match: RegExpExecArray | null;

  while ((match = TOKEN.exec(json)) !== null) {
    // push text before token
    if (match.index > last) {
      parts.push(json.slice(last, match.index));
    }
    const [full, key, str, bool, nil, num] = match;
    if (key) {
      // JSON key (strip trailing colon for colouring then re-add)
      const colonIdx = key.lastIndexOf(":");
      const keyPart = key.slice(0, colonIdx);
      parts.push(
        <span key={match.index} className="text-blue-400">
          {keyPart}
        </span>,
      );
      parts.push(key.slice(colonIdx));
    } else if (str) {
      parts.push(
        <span key={match.index} className="text-emerald-400">
          {full}
        </span>,
      );
    } else if (bool) {
      parts.push(
        <span key={match.index} className="text-amber-400">
          {full}
        </span>,
      );
    } else if (nil) {
      parts.push(
        <span key={match.index} className="text-red-400/70">
          {full}
        </span>,
      );
    } else if (num) {
      parts.push(
        <span key={match.index} className="text-purple-400">
          {full}
        </span>,
      );
    }
    last = match.index + full.length;
  }
  if (last < json.length) {
    parts.push(json.slice(last));
  }
  return parts;
}
