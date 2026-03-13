import { useState } from "react";
import { parseMcpServersText, parseMcpSidecarsText } from "@/lib/mcp";
import { parseA2APeerRefsText } from "@/lib/a2a";
import { buildSkillFiles } from "@/lib/skills";
import { buildGooseConfigFiles } from "@/lib/gooseConfig";
import type { CreateAgentPayload, RuntimeKind, TextFileDraft } from "@/types";

const DEFAULT_AGENT_NAME = "workspace-assistant";
const DEFAULT_AGENT_MODEL = "gpt-4";
const DEFAULT_SYSTEM_PROMPT =
  "You are a helpful enterprise assistant. Answer clearly, stay factual, and do not fabricate information.";

export function useAgentForm() {
  const [createAgentName, setCreateAgentName] = useState(DEFAULT_AGENT_NAME);
  const [createAgentModel, setCreateAgentModel] = useState(DEFAULT_AGENT_MODEL);
  const [createAgentSystemPrompt, setCreateAgentSystemPrompt] = useState(DEFAULT_SYSTEM_PROMPT);
  const [createAgentRuntimeKind, setCreateAgentRuntimeKind] = useState<RuntimeKind>("langgraph");
  const [createAgentMcpServersText, setCreateAgentMcpServersText] = useState("");
  const [createAgentMcpSidecarsText, setCreateAgentMcpSidecarsText] = useState("");
  const [createAgentA2AAllowedCallersText, setCreateAgentA2AAllowedCallersText] = useState("");
  const [createAgentSkillFileDrafts, setCreateAgentSkillFileDrafts] = useState<TextFileDraft[]>([]);
  const [createAgentGooseConfigFileDrafts, setCreateAgentGooseConfigFileDrafts] = useState<TextFileDraft[]>([]);
  const [isCreatingAgent, setIsCreatingAgent] = useState(false);
  const [createError, setCreateError] = useState("");

  function resetForm() {
    setCreateAgentName(DEFAULT_AGENT_NAME);
    setCreateAgentModel(DEFAULT_AGENT_MODEL);
    setCreateAgentSystemPrompt(DEFAULT_SYSTEM_PROMPT);
    setCreateAgentRuntimeKind("langgraph");
    setCreateAgentMcpServersText("");
    setCreateAgentMcpSidecarsText("");
    setCreateAgentA2AAllowedCallersText("");
    setCreateAgentSkillFileDrafts([]);
    setCreateAgentGooseConfigFileDrafts([]);
    setCreateError("");
  }

  function buildPayload(): CreateAgentPayload {
    const allowedCallers = parseA2APeerRefsText(createAgentA2AAllowedCallersText);
    const skillFiles = buildSkillFiles(createAgentSkillFileDrafts);
    const mcpServers = createAgentRuntimeKind === "langgraph" ? parseMcpServersText(createAgentMcpServersText) : [];
    const mcpSidecars = createAgentRuntimeKind !== "goose" ? parseMcpSidecarsText(createAgentMcpSidecarsText) : [];
    const gooseConfigFiles = createAgentRuntimeKind === "goose" ? buildGooseConfigFiles(createAgentGooseConfigFileDrafts) : undefined;

    return {
      name: createAgentName.trim(),
      model: createAgentModel.trim(),
      system_prompt: createAgentSystemPrompt.trim(),
      runtime_kind: createAgentRuntimeKind,
      mcp_servers: mcpServers,
      mcp_sidecars: mcpSidecars,
      a2a_config: allowedCallers.length > 0 ? { allowed_callers: allowedCallers } : undefined,
      skills: Object.keys(skillFiles).length > 0 ? { files: skillFiles } : undefined,
      goose_config_files: gooseConfigFiles,
    };
  }

  return {
    createAgentName,
    setCreateAgentName,
    createAgentModel,
    setCreateAgentModel,
    createAgentSystemPrompt,
    setCreateAgentSystemPrompt,
    createAgentRuntimeKind,
    setCreateAgentRuntimeKind,
    createAgentMcpServersText,
    setCreateAgentMcpServersText,
    createAgentMcpSidecarsText,
    setCreateAgentMcpSidecarsText,
    createAgentA2AAllowedCallersText,
    setCreateAgentA2AAllowedCallersText,
    createAgentSkillFileDrafts,
    setCreateAgentSkillFileDrafts,
    createAgentGooseConfigFileDrafts,
    setCreateAgentGooseConfigFileDrafts,
    isCreatingAgent,
    setIsCreatingAgent,
    createError,
    setCreateError,
    resetForm,
    buildPayload,
  };
}
