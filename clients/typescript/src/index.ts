/**
 * kubesynapse TypeScript SDK
 *
 * Usage:
 *   import { KubeSynapseClient } from "@kubesynapse/client";
 *   const client = new KubeSynapseClient("http://localhost:8080");
 *   const agents = await client.listAgents();
 */

export { KubeSynapseClient, KubeSynapseError } from "./client.js";
export type {
  Agent,
  AgentCreate,
  AgentList,
  AgentPolicy,
  AgentStatus,
  AgentWorkflow,
  AgentWorkflowCreate,
  AgentWorkflowStatus,
  HealthStatus,
  StepResult,
  WorkflowStep,
} from "./models.js";
