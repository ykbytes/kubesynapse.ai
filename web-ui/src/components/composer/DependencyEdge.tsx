import {
  BaseEdge,
  getBezierPath,
  EdgeLabelRenderer,
  type EdgeProps,
} from "@xyflow/react";
import { X } from "lucide-react";
import { useCallback } from "react";

export interface DependencyEdgeData extends Record<string, unknown> {
  sourceStatus?: string | null;
  animated?: boolean;
  onDelete?: (edgeId: string) => void;
}

function edgeColor(status?: string | null): string {
  switch (status) {
    case "completed":
      return "oklch(0.65 0.17 155)"; // emerald
    case "running":
      return "oklch(0.75 0.15 85)"; // amber
    case "continued":
      return "oklch(0.72 0.16 78)"; // amber/orange
    case "waiting_approval":
      return "oklch(0.72 0.18 58)"; // orange
    case "failed":
    case "denied":
      return "oklch(0.6 0.22 27)"; // red
    case "cancelled":
      return "oklch(0.68 0.14 52)"; // muted orange
    default:
      return "oklch(0.30 0.012 274)"; // border color
  }
}

export function DependencyEdge(props: EdgeProps) {
  const edgeData = props.data as DependencyEdgeData | undefined;
  const sourceStatus = edgeData?.sourceStatus;
  const isResolved = sourceStatus === "completed" || sourceStatus === "continued";
  const isFlowing = sourceStatus === "running" || isResolved;
  const isHighlighted = isFlowing || sourceStatus === "waiting_approval" || sourceStatus === "failed" || sourceStatus === "denied" || sourceStatus === "cancelled";
  const color = edgeColor(sourceStatus);

  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX: props.sourceX,
    sourceY: props.sourceY,
    sourcePosition: props.sourcePosition,
    targetX: props.targetX,
    targetY: props.targetY,
    targetPosition: props.targetPosition,
  });

  const handleDelete = useCallback(() => {
    edgeData?.onDelete?.(props.id as string);
  }, [edgeData, props.id]);

  return (
    <>
      {/* Invisible wider hit area for hover */}
      <path
        d={edgePath}
        fill="none"
        stroke="transparent"
        strokeWidth={20}
        className="react-flow__edge-interaction"
      />

      {/* Main edge path */}
      <BaseEdge
        path={edgePath}
        style={{
          stroke: color,
          strokeWidth: isHighlighted ? 2.5 : 1.5,
          strokeDasharray: isFlowing ? undefined : sourceStatus === "waiting_approval" ? "4 3" : "6 4",
          opacity: isHighlighted ? 1 : 0.6,
          transition: "stroke 0.3s ease, stroke-width 0.3s ease, opacity 0.3s ease",
        }}
        markerEnd="url(#dependency-arrow)"
      />

      {/* Animated flow dot when data is passing through */}
      {isFlowing && (
        <circle r="3" fill={color}>
          <animateMotion
            dur={sourceStatus === "running" ? "1.5s" : "2s"}
            repeatCount="indefinite"
            path={edgePath}
          />
        </circle>
      )}

      {/* Delete button on hover */}
      {edgeData?.onDelete && (
        <EdgeLabelRenderer>
          <button
            type="button"
            className="composer-edge-delete absolute flex h-5 w-5 items-center justify-center rounded-full border bg-card text-muted-foreground shadow-md hover:bg-destructive hover:text-destructive-foreground hover:border-destructive transition-colors cursor-pointer"
            style={{
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
              pointerEvents: "all",
            }}
            onClick={handleDelete}
            title="Remove connection"
            aria-label="Remove connection"
          >
            <X className="h-3 w-3" />
          </button>
        </EdgeLabelRenderer>
      )}
    </>
  );
}
