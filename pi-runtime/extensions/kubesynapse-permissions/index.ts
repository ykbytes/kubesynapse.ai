/**
 * kubesynapse Permissions Extension for pi
 *
 * Enforces security policies within pi agent sessions. Blocks dangerous
 * operations, protects sensitive paths, and applies kubesynapse RBAC rules.
 *
 * Permission levels:
 *   "strict"  — read-only (block all write/bash/edit)
 *   "moderate" — allow writes but block dangerous bash + protected paths
 *   "permissive" — allow all (default, typical for sandboxed agents)
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

const PERMISSION_LEVEL = (
  process.env.KS_PERMISSION_LEVEL || "permissive"
).toLowerCase();

// Dangerous shell patterns
const DANGEROUS_PATTERNS = [
  /\brm\s+-rf\b/,
  /\bsudo\b/,
  /\bchmod\s+777\b/,
  /\bchmod\s+-R\s+777\b/,
  /\bdd\s+if=/,
  /\bmkfs\./,
  /\b:(){ :|:& };:/, // fork bomb
  />\/dev\/sda/,
  /\bcurl.*\|\s*(ba)?sh\b/,
  /\bwget.*\|\s*(ba)?sh\b/,
  /\bgit\s+push\s+--force\b/,
  /\bgit\s+push\s+-f\b/,
  /\bkubectl\s+delete\b/,
  /\bdocker\s+rm\s+-f\b/,
];

// Protected paths (write/edit blocked)
const PROTECTED_PATHS = [
  /\/\.env$/,
  /\/\.env\./,
  /\/credentials\./i,
  /\/secrets?\//i,
  /\/\.git\/config$/,
  /\/\.ssh\//,
  /\/\.gnupg\//,
  /\/node_modules\//,
  /\/\.git\/index$/,
];

// Read-only agent (no bash or write tools)
const READ_ONLY_MODE = process.env.PI_NO_TOOLS === "true" ||
  (process.env.PI_TOOLS || "").split(",").every(t =>
    ["read", "grep", "find", "ls"].includes(t.trim())
  );

export default function (pi: ExtensionAPI) {
  if (READ_ONLY_MODE) {
    PERMISSION_LEVEL !== "permissive" || (PERMISSION_LEVEL === "strict");
  }

  pi.on("tool_call", async (event, ctx) => {
    // Strict mode: block all destructive tools
    if (PERMISSION_LEVEL === "strict") {
      if (["bash", "write", "edit"].includes(event.toolName)) {
        return {
          block: true,
          reason: `Blocked by kubesynapse permission policy (level: strict). Agent is in read-only mode.`,
        };
      }
    }

    // Bash safety checks
    if (event.toolName === "bash" && PERMISSION_LEVEL !== "permissive") {
      const input = (event.input as { command?: string }) || {};
      const command = (input.command || "").trim();

      if (!command) return;

      for (const pattern of DANGEROUS_PATTERNS) {
        if (pattern.test(command)) {
          console.warn(
            `[kubesynapse-permissions] BLOCKED dangerous bash command: ${command.slice(0, 200)}`
          );

          const shouldBlock = PERMISSION_LEVEL === "moderate" ||
            PERMISSION_LEVEL === "strict";

          if (shouldBlock) {
            return {
              block: true,
              reason: `Blocked by kubesynapse permission policy (level: ${PERMISSION_LEVEL}). Dangerous command detected: ${command.slice(0, 100)}`,
            };
          }

          // In permissive mode, just warn
          ctx.ui.notify(
            `Warning: Potentially dangerous command executed`,
            "warning"
          );
          break;
        }
      }
    }

    // Write/edit path protection
    if (
      (event.toolName === "write" || event.toolName === "edit") &&
      PERMISSION_LEVEL !== "permissive"
    ) {
      const input = (event.input as { path?: string; filePath?: string }) || {};
      const filePath = (input.path || input.filePath || "").trim();

      if (!filePath) return;

      for (const pattern of PROTECTED_PATHS) {
        if (pattern.test(filePath)) {
          console.warn(
            `[kubesynapse-permissions] BLOCKED write to protected path: ${filePath}`
          );
          return {
            block: true,
            reason: `Blocked by kubesynapse permission policy. Cannot write to protected path: ${filePath}`,
          };
        }
      }
    }
  });

  pi.on("session_start", async (_event, ctx) => {
    const levelLabel =
      PERMISSION_LEVEL === "strict" ? "🔒 Strict" :
      PERMISSION_LEVEL === "moderate" ? "🛡️ Moderate" :
      READ_ONLY_MODE ? "📖 Read-only" : "🔓 Permissive";

    ctx.ui.notify(`kubesynapse permissions: ${levelLabel}`, "info");
  });
}
