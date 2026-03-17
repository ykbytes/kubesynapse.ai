import { BaseEdge, getSmoothStepPath, type EdgeProps } from "@xyflow/react";

export function DependencyEdge(props: EdgeProps) {
  const [edgePath] = getSmoothStepPath({
    sourceX: props.sourceX,
    sourceY: props.sourceY,
    sourcePosition: props.sourcePosition,
    targetX: props.targetX,
    targetY: props.targetY,
    targetPosition: props.targetPosition,
  });

  return (
    <BaseEdge
      id={props.id}
      path={edgePath}
      style={{ stroke: "hsl(var(--primary))", strokeWidth: 2 }}
      markerEnd="url(#dependency-arrow)"
    />
  );
}
