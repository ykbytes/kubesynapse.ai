import { memo, useState, useCallback, useEffect, useRef } from "react";
import { Check, Copy, Pencil, RotateCcw, ThumbsUp, ThumbsDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type FeedbackState = "none" | "positive" | "negative";

interface MessageToolbarProps {
  /** The text content of the message (for copy). */
  content: string;
  /** Whether this is a user message (shows edit) vs assistant (shows regenerate/feedback). */
  isUser?: boolean;
  /** Whether the message is currently streaming. Hide toolbar during streaming. */
  isStreaming?: boolean;
  /** Callback when user wants to edit their message. */
  onEdit?: () => void;
  /** Callback when user wants to regenerate the assistant response. */
  onRegenerate?: () => void;
  className?: string;
}

export const MessageToolbar = memo(function MessageToolbar({
  content,
  isUser = false,
  isStreaming = false,
  onEdit,
  onRegenerate,
  className,
}: MessageToolbarProps) {
  const [copied, setCopied] = useState(false);
  const [feedback, setFeedback] = useState<FeedbackState>("none");
  const timerRef = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    return () => { clearTimeout(timerRef.current); };
  }, []);

  const handleCopy = useCallback(async () => {
    if (!content) return;
    await navigator.clipboard.writeText(content);
    setCopied(true);
    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => setCopied(false), 1500);
  }, [content]);

  if (isStreaming || !content) return null;

  return (
    <div
      className={cn(
        "flex items-center gap-0.5 rounded-lg border border-border/50 bg-background/90 px-1 py-0.5 shadow-sm backdrop-blur-sm",
        "opacity-0 group-hover:opacity-100 transition-opacity duration-200",
        className,
      )}
    >
      {/* Copy */}
      <Button
        variant="ghost"
        size="icon"
        className="h-6 w-6 text-muted-foreground hover:text-foreground"
        onClick={handleCopy}
        aria-label={copied ? "Copied" : "Copy message"}
      >
        {copied ? (
          <Check className="h-3 w-3 text-emerald-400" />
        ) : (
          <Copy className="h-3 w-3" />
        )}
      </Button>

      {isUser ? (
        /* User message: edit */
        onEdit && (
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6 text-muted-foreground hover:text-foreground"
            onClick={onEdit}
            aria-label="Edit message"
          >
            <Pencil className="h-3 w-3" />
          </Button>
        )
      ) : (
        /* Assistant message: regenerate + feedback */
        <>
          {onRegenerate && (
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6 text-muted-foreground hover:text-foreground"
              onClick={onRegenerate}
              aria-label="Regenerate response"
            >
              <RotateCcw className="h-3 w-3" />
            </Button>
          )}
          <div className="mx-0.5 h-3 w-px bg-border/60" />
          <Button
            variant="ghost"
            size="icon"
            className={cn("h-6 w-6", feedback === "positive" ? "text-emerald-400" : "text-muted-foreground hover:text-foreground")}
            onClick={() => setFeedback((f) => (f === "positive" ? "none" : "positive"))}
            aria-label="Good response"
          >
            <ThumbsUp className="h-3 w-3" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className={cn("h-6 w-6", feedback === "negative" ? "text-red-400" : "text-muted-foreground hover:text-foreground")}
            onClick={() => setFeedback((f) => (f === "negative" ? "none" : "negative"))}
            aria-label="Bad response"
          >
            <ThumbsDown className="h-3 w-3" />
          </Button>
        </>
      )}
    </div>
  );
});
