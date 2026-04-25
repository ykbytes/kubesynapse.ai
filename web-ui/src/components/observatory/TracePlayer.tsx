import { useEffect, useRef, useState, useCallback } from "react";
import { Play, Pause, RotateCcw, SkipForward, SkipBack } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { TraceEvent } from "@/types";

interface TracePlayerProps {
  events: TraceEvent[];
  onActiveEventChange?: (eventId: string | null) => void;
}

export function TracePlayer({ events, onActiveEventChange }: TracePlayerProps) {
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentIndex, setCurrentIndex] = useState(-1);
  const [speed, setSpeed] = useState(1);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const sorted = [...events].sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());
  const total = sorted.length;

  const clear = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (isPlaying && total > 0) {
      const baseMs = 1000;
      const intervalMs = Math.max(100, baseMs / speed);
      intervalRef.current = setInterval(() => {
        setCurrentIndex((prev) => {
          const next = prev + 1;
          if (next >= total) {
            setIsPlaying(false);
            return prev;
          }
          return next;
        });
      }, intervalMs);
    } else {
      clear();
    }
    return () => clear();
  }, [isPlaying, speed, total, clear]);

  useEffect(() => {
    onActiveEventChange?.(currentIndex >= 0 && currentIndex < total ? sorted[currentIndex]?.id ?? null : null);
  }, [currentIndex, total, sorted, onActiveEventChange]);

  const handleSeek = (value: number) => {
    setCurrentIndex(value);
  };

  const handlePlayPause = () => {
    if (currentIndex >= total - 1) {
      setCurrentIndex(-1);
    }
    setIsPlaying((p) => !p);
  };

  const handleReset = () => {
    setIsPlaying(false);
    setCurrentIndex(-1);
  };

  const handleStep = (delta: number) => {
    setIsPlaying(false);
    setCurrentIndex((prev) => Math.max(-1, Math.min(total - 1, prev + delta)));
  };

  const progress = total > 0 ? ((currentIndex + 1) / total) * 100 : 0;

  return (
    <div className="rounded-[1.75rem] border border-border/70 bg-card/55 p-4 space-y-4">
      {/* Progress bar */}
      <div className="space-y-1">
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>Event {currentIndex + 1} of {total}</span>
          <span>{Math.round(progress)}%</span>
        </div>
        <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
          <div
            className="h-full bg-primary transition-[width] duration-150 ease-productive"
            style={{ width: `${progress}%` }}
            aria-hidden="true"
          />
        </div>
        <input
          type="range"
          min={-1}
          max={total - 1}
          value={currentIndex}
          onChange={(e) => handleSeek(Number(e.target.value))}
          className="w-full cursor-pointer accent-primary"
          aria-label="Seek through trace events"
        />
      </div>

      {/* Controls */}
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="outline" size="sm" className="h-8 w-8 p-0 rounded-xl" onClick={() => handleStep(-1)} aria-label="Previous event">
          <SkipBack className="h-4 w-4" />
        </Button>
        <Button variant="outline" size="sm" className="h-8 w-8 p-0 rounded-xl" onClick={handlePlayPause} aria-label={isPlaying ? "Pause" : "Play"}>
          {isPlaying ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
        </Button>
        <Button variant="outline" size="sm" className="h-8 w-8 p-0 rounded-xl" onClick={() => handleStep(1)} aria-label="Next event">
          <SkipForward className="h-4 w-4" />
        </Button>
        <Button variant="outline" size="sm" className="h-8 w-8 p-0 rounded-xl" onClick={handleReset} aria-label="Reset">
          <RotateCcw className="h-4 w-4" />
        </Button>

        <div className="ml-auto flex items-center gap-2">
          <span className="text-xs text-muted-foreground">Speed</span>
          {[0.5, 1, 1.5, 2].map((s) => (
            <button
              key={s}
              onClick={() => setSpeed(s)}
              className={cn(
                "h-7 rounded-lg px-2 text-xs font-medium transition-colors",
                speed === s ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground hover:bg-accent",
              )}
              aria-label={`${s}x speed`}
              aria-pressed={speed === s}
            >
              {s}x
            </button>
          ))}
        </div>
      </div>

      {/* Current event preview */}
      {currentIndex >= 0 && sorted[currentIndex] && (
        <div className="rounded-xl border border-border/50 bg-muted/30 p-3">
          <p className="text-xs font-semibold text-foreground">{sorted[currentIndex].event_type}</p>
          <p className="text-[11px] text-muted-foreground">{new Date(sorted[currentIndex].timestamp).toLocaleString()}</p>
          {Object.keys(sorted[currentIndex].payload).length > 0 && (
            <pre className="mt-2 max-h-32 overflow-auto rounded-lg bg-slate-950 p-2 text-[10px] text-slate-100">
              {JSON.stringify(sorted[currentIndex].payload, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
