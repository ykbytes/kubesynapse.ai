import type { A2APeerRef } from "../types";

const K8S_NAME_RE = /^[a-z0-9]([-a-z0-9]*[a-z0-9])?$/;

export const A2A_ALLOWED_CALLERS_PLACEHOLDER = "default/workspace-assistant\nteam-b/research-agent";

export function isValidK8sName(value: string): boolean {
  return K8S_NAME_RE.test(value);
}

export function formatA2APeerRef(peerRef: A2APeerRef): string {
  return `${peerRef.namespace}/${peerRef.name}`;
}

export function stringifyA2APeerRefs(peerRefs: A2APeerRef[] | undefined): string {
  return (peerRefs ?? []).map((peerRef) => formatA2APeerRef(peerRef)).join("\n");
}

export function parseA2APeerRefsText(text: string): A2APeerRef[] {
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
  const peers: A2APeerRef[] = [];
  const seen = new Set<string>();

  for (const line of lines) {
    const separatorIndex = line.indexOf("/");
    if (separatorIndex <= 0 || separatorIndex === line.length - 1 || line.indexOf("/", separatorIndex + 1) !== -1) {
      throw new Error(`A2A caller entries must use namespace/name syntax. Invalid value: ${line}`);
    }

    const namespace = line.slice(0, separatorIndex).trim();
    const name = line.slice(separatorIndex + 1).trim();
    if (!isValidK8sName(namespace)) {
      throw new Error(`A2A caller namespace must be a lowercase Kubernetes name. Invalid value: ${namespace}`);
    }
    if (!isValidK8sName(name)) {
      throw new Error(`A2A caller name must be a lowercase Kubernetes name. Invalid value: ${name}`);
    }

    const identity = `${namespace}/${name}`;
    if (seen.has(identity)) {
      continue;
    }
    seen.add(identity);
    peers.push({ namespace, name });
  }

  return peers;
}
