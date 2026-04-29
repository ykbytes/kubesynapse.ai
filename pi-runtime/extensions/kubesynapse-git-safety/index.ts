/**
 * kubesynapse Git Safety Extension for pi
 *
 * Prevents destructive git operations (force push, branch deletion, etc.)
 * within kubesynapse agent sessions. Works alongside the permissions extension
 * but focuses specifically on git-level safety.
 *
 * Based on patterns from rhubarb-pi/safe-git and agent-stuff.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

const DANGEROUS_GIT_PATTERNS = [
  /\bgit\s+push\s+.*--force\b/,
  /\bgit\s+push\s+.*-f\b/,
  /\bgit\s+push\s+.*--delete\b/,
  /\bgit\s+branch\s+-D\b/,
  /\bgit\s+reset\s+--hard\b/,
  /\bgit\s+clean\s+-fd\b/,
  /\bgit\s+stash\s+drop\b/,
  /\bgit\s+stash\s+clear\b/,
  /\bgit\s+rebase\s+--abort\b/,
];

export default function (pi: ExtensionAPI) {
  pi.on("tool_call", async (event, ctx) => {
    if (event.toolName !== "bash") return;

    const input = (event.input as { command?: string }) || {};
    const command = (input.command || "").trim();

    if (!command) return;

    for (const pattern of DANGEROUS_GIT_PATTERNS) {
      if (pattern.test(command)) {
        console.warn(
          `[kubesynapse-git-safety] BLOCKED dangerous git command: ${command.slice(0, 200)}`
        );

        // In RPC/headless mode, always block dangerous operations.
        // In interactive mode, prompt the user for confirmation.
        if (!ctx.hasUI) {
          // Print mode — always block
          return {
            block: true,
            reason: "Blocked by kubesynapse git safety policy. Use --force-with-lease or a safer alternative.",
          };
        }

        const confirm = await ctx.ui.confirm(
          "Dangerous Git Operation",
          `This git command could cause data loss:\n\n  ${command}\n\nAllow it?`
        );

        if (!confirm) {
          return {
            block: true,
            reason: "Blocked by kubesynapse git safety policy. Use --force-with-lease or a safer alternative.",
          };
        }

        // User approved — let it through
        ctx.ui.notify("Dangerous git command allowed by user", "warning");
        break;
      }
    }
  });

  pi.on("session_start", async (_event, ctx) => {
    ctx.ui.notify("Git safety checks active", "info");
  });
};
