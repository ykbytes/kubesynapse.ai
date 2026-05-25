/**
 * kubesynapse Artifacts Extension for pi
 *
 * Automatically saves agent outputs (files, responses) to the kubesynapse
 * artifact system. Tracks file modifications and posts summaries to
 * the API gateway for workflow integration.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

const ARTIFACT_PATH = process.env.ARTIFACT_PATH || "/artifacts/run.json";
const ARTIFACT_JOURNAL_PATH =
  process.env.ARTIFACT_JOURNAL_PATH || "/artifacts/journal.json";
const API_GATEWAY_URL =
  process.env.API_GATEWAY_URL || "http://kubesynapse-api-gateway.kubesynapse.svc.cluster.local:8000";
const API_TOKEN = process.env.API_GATEWAY_SHARED_TOKEN || "";
const TARGET_NAME = process.env.TARGET_NAME || "";
const TARGET_NAMESPACE = process.env.TARGET_NAMESPACE || "default";
const WORKER_KIND = process.env.WORKER_KIND || "workflow";
const RUN_ID = process.env.WORKFLOW_RUN_ID || process.env.EVAL_RUN_ID || "";

import { mkdirSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import { dirname } from "node:path";

// --- Helpers ---
function ensureDir(filePath: string): void {
  const dir = dirname(filePath);
  if (!existsSync(dir)) {
    mkdirSync(dir, { recursive: true });
  }
}

function loadArtifact(): Record<string, unknown> {
  try {
    if (existsSync(ARTIFACT_PATH)) {
      return JSON.parse(readFileSync(ARTIFACT_PATH, "utf-8"));
    }
  } catch {}
  return {};
}

function saveArtifact(data: Record<string, unknown>): void {
  ensureDir(ARTIFACT_PATH);
  writeFileSync(ARTIFACT_PATH, JSON.stringify(data, null, 2), "utf-8");
}

function appendJournal(entry: Record<string, unknown>): void {
  try {
    ensureDir(ARTIFACT_JOURNAL_PATH);
    const line = JSON.stringify({ ...entry, timestamp: new Date().toISOString() });
    writeFileSync(ARTIFACT_JOURNAL_PATH, line + "\n", "utf-8");
  } catch {}
}

// Track files modified by the agent
const modifiedFiles = new Set<string>();

export default function (pi: ExtensionAPI) {
  // Track writes
  pi.on("tool_execution_end", async (event) => {
    if (event.toolName === "write" || event.toolName === "edit") {
      const input = event.input as { path?: string; filePath?: string } || {};
      const filePath = input.path || input.filePath || "";
      if (filePath && !event.isError) {
        modifiedFiles.add(filePath);
      }
    }
  });

  // Save artifacts on agent end
  pi.on("agent_end", async (event) => {
    const artifact = loadArtifact();

    artifact.runId = RUN_ID;
    artifact.targetName = TARGET_NAME;
    artifact.targetNamespace = TARGET_NAMESPACE;
    artifact.workerKind = WORKER_KIND;
    artifact.modifiedFiles = [...modifiedFiles];

    // Extract last assistant message
    const lastAssistant = [...event.messages].reverse().find(
      (m) => m.role === "assistant"
    );

    if (lastAssistant && lastAssistant.role === "assistant") {
      const textBlocks = lastAssistant.content.filter(
        (c) => c.type === "text"
      );
      const response = textBlocks.map((c) => (c as { text: string }).text).join("\n");
      artifact.response = response;
    }

    saveArtifact(artifact);
    appendJournal({
      event: "agent_end",
      runId: RUN_ID,
      fileCount: modifiedFiles.size,
      files: [...modifiedFiles].slice(0, 100), // Cap to avoid huge journal
    });
  });
}
