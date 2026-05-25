/**
 * Template variable utilities for workflow step prompts.
 *
 * Mirrors the operator's `render_prompt()` syntax:
 *   {{input}}                         – workflow input
 *   {{previous_output}}               – prior step output
 *   {{step-name.output}}              – full output of a named step
 *   {{step-name.output.json.field}}   – JSON field from a named step
 */

/** Regex matching `{{ ... }}` placeholders (mirrors operator/utils.py L19). */
const PLACEHOLDER_RE = /\{\{\s*([^{}]+?)\s*\}\}/g;

export interface PlaceholderInfo {
  /** Raw expression inside the braces, trimmed. */
  expression: string;
  /** Character offset of the opening `{{` in the source string. */
  start: number;
  /** Character offset just past the closing `}}`. */
  end: number;
}

export interface ValidationResult extends PlaceholderInfo {
  valid: boolean;
  /** Human-readable reason when invalid. */
  reason?: string;
}

/** Extract all `{{ ... }}` placeholders from a template string. */
export function extractPlaceholders(template: string): PlaceholderInfo[] {
  const results: PlaceholderInfo[] = [];
  let m: RegExpExecArray | null;
  const re = new RegExp(PLACEHOLDER_RE.source, "g");
  while ((m = re.exec(template)) !== null) {
    results.push({
      expression: m[1].trim(),
      start: m.index,
      end: m.index + m[0].length,
    });
  }
  return results;
}

/**
 * Validate each placeholder against the known workflow topology.
 *
 * @param placeholders  – output of `extractPlaceholders()`
 * @param upstreamSteps – step names that are *transitive* upstream dependencies
 *                        of the current step (i.e. their output is available).
 */
export function validatePlaceholders(
  placeholders: PlaceholderInfo[],
  upstreamSteps: string[],
): ValidationResult[] {
  const upSet = new Set(upstreamSteps);
  return placeholders.map((p) => {
    const expr = p.expression;
    // Built-in variables are always valid
    if (expr === "input" || expr === "previous_output") {
      return { ...p, valid: true };
    }
    // Step-reference: root must be an upstream step name
    const root = expr.split(".")[0];
    if (!upSet.has(root)) {
      return {
        ...p,
        valid: false,
        reason: upSet.size === 0
          ? `No upstream steps available — "${root}" cannot be resolved`
          : `"${root}" is not an upstream dependency of this step`,
      };
    }
    return { ...p, valid: true };
  });
}

/**
 * Compute *transitive* upstream step names for a given node.
 * The result is a de-duplicated list of step IDs that feed into `nodeId`
 * (directly or transitively), excluding the trigger node.
 */
export function getTransitiveUpstream(
  nodeId: string,
  edges: { source: string; target: string }[],
  triggerNodeId: string,
): string[] {
  const visited = new Set<string>();
  const queue: string[] = [];

  // Seed with direct parents
  for (const e of edges) {
    if (e.target === nodeId && e.source !== triggerNodeId) {
      queue.push(e.source);
    }
  }

  while (queue.length > 0) {
    const id = queue.pop()!;
    if (visited.has(id)) continue;
    visited.add(id);
    for (const e of edges) {
      if (e.target === id && e.source !== triggerNodeId) {
        queue.push(e.source);
      }
    }
  }

  return Array.from(visited);
}

/**
 * Build the list of available placeholder chips for a given step.
 * Returns user-friendly label + insertion text pairs.
 */
export function availablePlaceholders(
  upstreamSteps: string[],
): { label: string; insert: string; description: string }[] {
  const items: { label: string; insert: string; description: string }[] = [
    { label: "input", insert: "{{input}}", description: "Workflow input" },
    { label: "previous_output", insert: "{{previous_output}}", description: "Previous step output" },
  ];
  for (const step of upstreamSteps) {
    items.push({
      label: `${step}.output`,
      insert: `{{${step}.output}}`,
      description: `Full output of "${step}"`,
    });
  }
  return items;
}

/** Check whether any step prompt in the workflow references `{{input}}`. */
export function anyStepUsesInput(
  nodes: { data: { prompt?: string } }[],
): boolean {
  const re = /\{\{\s*input\s*\}\}/;
  return nodes.some((n) => re.test(n.data.prompt ?? ""));
}
