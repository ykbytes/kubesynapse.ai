import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

interface SparkPoint {
  label: string;
  value: number | null;
  tone?: "neutral" | "success" | "warning" | "danger";
}

interface RangePoint {
  label: string;
  min: number;
  median: number;
  max: number;
  value?: number | null;
}

interface ShareBarPoint {
  label: string;
  value: number;
  hint?: string;
  tone?: "violet" | "sky" | "emerald" | "amber" | "rose" | "slate";
}

interface ScatterPoint {
  id: string;
  x: number;
  y: number;
  size?: number;
  label: string;
  detail?: string;
  tone?: "violet" | "sky" | "emerald" | "amber" | "rose";
}

function toneClass(tone: SparkPoint["tone"]): string {
  if (tone === "success") return "bg-emerald-500";
  if (tone === "warning") return "bg-amber-500";
  if (tone === "danger") return "bg-red-500";
  return "bg-primary";
}

function shareToneClass(tone: ShareBarPoint["tone"]): string {
  switch (tone) {
    case "violet": return "bg-violet-500";
    case "sky": return "bg-sky-500";
    case "emerald": return "bg-emerald-500";
    case "amber": return "bg-amber-500";
    case "rose": return "bg-rose-500";
    default: return "bg-slate-500";
  }
}

function scatterToneClass(tone: ScatterPoint["tone"]): string {
  switch (tone) {
    case "violet": return "bg-violet-500/80 border-violet-400/60";
    case "sky": return "bg-sky-500/80 border-sky-400/60";
    case "emerald": return "bg-emerald-500/80 border-emerald-400/60";
    case "amber": return "bg-amber-500/80 border-amber-400/60";
    case "rose": return "bg-rose-500/80 border-rose-400/60";
    default: return "bg-primary/80 border-primary/60";
  }
}

export function TrendSparkline({
  data,
  valueFormatter,
}: {
  data: SparkPoint[];
  valueFormatter?: (value: number | null) => string;
}) {
  const points = data.filter((item) => item.value != null && Number.isFinite(item.value));
  const max = Math.max(1, ...points.map((item) => item.value as number));

  if (points.length === 0) {
    return <div className="rounded-lg border border-dashed border-border/50 px-3 py-4 text-xs text-muted-foreground">No trend data yet.</div>;
  }

  return (
    <TooltipProvider delayDuration={120}>
      <div className="grid grid-cols-[repeat(auto-fit,minmax(16px,1fr))] items-end gap-1">
        {data.map((point, index) => {
          const value = point.value;
          const height = value != null && Number.isFinite(value) ? Math.max(14, Math.round(((value as number) / max) * 52)) : 8;
          return (
            <Tooltip key={`${point.label}-${index}`}>
              <TooltipTrigger asChild>
                <div className="flex flex-col items-center gap-1">
                  <div className="flex h-14 w-full items-end rounded-sm bg-muted/30 px-[2px] py-[2px]">
                    <div
                      className={cn("w-full rounded-[3px] transition-all", toneClass(point.tone))}
                      style={{ height }}
                    />
                  </div>
                  <span className="text-[9px] text-muted-foreground tabular-nums">{point.label}</span>
                </div>
              </TooltipTrigger>
              <TooltipContent side="top" className="text-xs">
                <div className="font-medium">{point.label}</div>
                <div className="text-muted-foreground">{valueFormatter ? valueFormatter(value) : String(value ?? "--")}</div>
              </TooltipContent>
            </Tooltip>
          );
        })}
      </div>
    </TooltipProvider>
  );
}

export function RangeBarChart({
  data,
  valueFormatter,
}: {
  data: RangePoint[];
  valueFormatter?: (value: number) => string;
}) {
  const max = Math.max(1, ...data.map((item) => item.max));

  if (data.length === 0) {
    return <div className="rounded-lg border border-dashed border-border/50 px-3 py-4 text-xs text-muted-foreground">No historical range data yet.</div>;
  }

  return (
    <TooltipProvider delayDuration={120}>
      <div className="space-y-2">
        {data.map((point) => {
          const minPct = (point.min / max) * 100;
          const maxPct = (point.max / max) * 100;
          const medianPct = (point.median / max) * 100;
          const valuePct = point.value != null ? (point.value / max) * 100 : null;

          return (
            <Tooltip key={point.label}>
              <TooltipTrigger asChild>
                <div className="grid grid-cols-[minmax(0,128px)_1fr_auto] items-center gap-3">
                  <span className="truncate text-[11px] text-foreground">{point.label}</span>
                  <div className="relative h-3 rounded-full bg-muted/35">
                    <div
                      className="absolute top-1/2 h-2 -translate-y-1/2 rounded-full bg-primary/20"
                      style={{ left: `${minPct}%`, width: `${Math.max(maxPct - minPct, 2)}%` }}
                    />
                    <div
                      className="absolute top-1/2 h-3 w-[2px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-primary"
                      style={{ left: `${medianPct}%` }}
                    />
                    {valuePct != null && (
                      <div
                        className="absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border border-amber-300/60 bg-amber-500/90 shadow-sm"
                        style={{ left: `${valuePct}%` }}
                      />
                    )}
                  </div>
                  <span className="text-[10px] tabular-nums text-muted-foreground">{valueFormatter ? valueFormatter(point.median) : point.median}</span>
                </div>
              </TooltipTrigger>
              <TooltipContent side="top" className="text-xs">
                <div className="font-medium">{point.label}</div>
                <div className="text-muted-foreground">Min {valueFormatter ? valueFormatter(point.min) : point.min}</div>
                <div className="text-muted-foreground">Median {valueFormatter ? valueFormatter(point.median) : point.median}</div>
                <div className="text-muted-foreground">Max {valueFormatter ? valueFormatter(point.max) : point.max}</div>
                {point.value != null && <div className="text-muted-foreground">Current {valueFormatter ? valueFormatter(point.value) : point.value}</div>}
              </TooltipContent>
            </Tooltip>
          );
        })}
      </div>
    </TooltipProvider>
  );
}

export function ShareBars({
  data,
  valueFormatter,
}: {
  data: ShareBarPoint[];
  valueFormatter?: (value: number) => string;
}) {
  const max = Math.max(1, ...data.map((item) => item.value));

  if (data.length === 0) {
    return <div className="rounded-lg border border-dashed border-border/50 px-3 py-4 text-xs text-muted-foreground">No distribution data yet.</div>;
  }

  return (
    <TooltipProvider delayDuration={120}>
      <div className="space-y-2">
        {data.map((point) => {
          const width = Math.max((point.value / max) * 100, point.value > 0 ? 6 : 0);
          return (
            <Tooltip key={point.label}>
              <TooltipTrigger asChild>
                <div className="grid grid-cols-[minmax(0,120px)_1fr_auto] items-center gap-3">
                  <span className="truncate text-[11px] text-foreground">{point.label}</span>
                  <div className="h-3 rounded-full bg-muted/35">
                    <div
                      className={cn("h-3 rounded-full", shareToneClass(point.tone))}
                      style={{ width: `${width}%` }}
                    />
                  </div>
                  <span className="text-[10px] tabular-nums text-muted-foreground">{valueFormatter ? valueFormatter(point.value) : point.value}</span>
                </div>
              </TooltipTrigger>
              <TooltipContent side="top" className="text-xs">
                <div className="font-medium">{point.label}</div>
                <div className="text-muted-foreground">{valueFormatter ? valueFormatter(point.value) : point.value}</div>
                {point.hint && <div className="text-muted-foreground">{point.hint}</div>}
              </TooltipContent>
            </Tooltip>
          );
        })}
      </div>
    </TooltipProvider>
  );
}

export function ScatterField({
  data,
  xLabel,
  yLabel,
}: {
  data: ScatterPoint[];
  xLabel: string;
  yLabel: string;
}) {
  const valid = data.filter((item) => Number.isFinite(item.x) && Number.isFinite(item.y));
  const maxX = Math.max(1, ...valid.map((item) => item.x));
  const maxY = Math.max(1, ...valid.map((item) => item.y));
  const maxSize = Math.max(1, ...valid.map((item) => item.size ?? 1));

  if (valid.length === 0) {
    return <div className="rounded-lg border border-dashed border-border/50 px-3 py-4 text-xs text-muted-foreground">No model scatter data yet.</div>;
  }

  return (
    <TooltipProvider delayDuration={120}>
      <div className="space-y-2">
        <div className="relative h-52 rounded-lg border border-border/50 bg-card/60">
          <div className="absolute inset-x-3 bottom-6 top-3 border-l border-b border-border/40" />
          {valid.map((point) => {
            const left = 12 + (point.x / maxX) * 84;
            const bottom = 10 + (point.y / maxY) * 78;
            const diameter = 10 + ((point.size ?? 1) / maxSize) * 14;
            return (
              <Tooltip key={point.id}>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    className={cn(
                      "absolute rounded-full border shadow-sm transition-transform hover:scale-110",
                      scatterToneClass(point.tone),
                    )}
                    style={{
                      left: `${left}%`,
                      bottom: `${bottom}%`,
                      width: diameter,
                      height: diameter,
                      transform: "translate(-50%, 50%)",
                    }}
                    aria-label={point.label}
                  />
                </TooltipTrigger>
                <TooltipContent side="top" className="max-w-[240px] text-xs">
                  <div className="font-medium">{point.label}</div>
                  {point.detail && <div className="text-muted-foreground">{point.detail}</div>}
                </TooltipContent>
              </Tooltip>
            );
          })}
          <span className="absolute bottom-1 left-3 text-[10px] text-muted-foreground">{xLabel}</span>
          <span className="absolute right-2 top-3 -rotate-90 origin-top-right text-[10px] text-muted-foreground">{yLabel}</span>
        </div>
      </div>
    </TooltipProvider>
  );
}
