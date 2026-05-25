import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Box, Globe, Server, Shield } from "lucide-react";

export function McpArchitectureTab() {
  return (
    <div className="animate-fade-in space-y-4">
      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="rounded-2xl border-border/60 bg-card/55">
          <CardHeader className="pb-3">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-sky-500/25 bg-sky-500/10 text-sky-500">
                <Globe className="h-5 w-5" />
              </div>
              <div>
                <CardTitle className="text-base">Remote MCP Servers</CardTitle>
                <CardDescription className="text-sm">Zero container overhead</CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-muted-foreground">
            <p className="leading-relaxed">
              Vendor-hosted services accessed over HTTPS. The agent runtime connects directly via streamable HTTP
              transport. No pods, no images, just an API key.
            </p>
            <div className="rounded-xl border border-border/50 bg-background/60 p-3 font-mono text-xs">
              <span className="text-sky-400">Agent Pod</span> &rarr;{" "}
              <span className="text-muted-foreground">HTTPS</span> &rarr;{" "}
              <span className="text-sky-400">api.github.com/mcp</span>
            </div>
            <div className="flex flex-wrap gap-2">
              <Badge variant="secondary" className="text-xs">GitHub</Badge>
              <Badge variant="secondary" className="text-xs">Context7</Badge>
              <Badge variant="secondary" className="text-xs">Brave Search</Badge>
              <Badge variant="secondary" className="text-xs">Azure</Badge>
            </div>
          </CardContent>
        </Card>

        <Card className="rounded-2xl border-border/60 bg-card/55">
          <CardHeader className="pb-3">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-indigo-500/25 bg-indigo-500/10 text-indigo-500">
                <Server className="h-5 w-5" />
              </div>
              <div>
                <CardTitle className="text-base">Hub Servers</CardTitle>
                <CardDescription className="text-sm">Shared across all agents</CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-muted-foreground">
            <p className="leading-relaxed">
              Centrally deployed in the <code className="rounded bg-muted px-1.5 py-0.5 text-xs">mcp-hub</code>{" "}
              namespace. One instance serves all agents through the operator-managed NetworkPolicy. Ideal for shared
              databases and internal APIs.
            </p>
            <div className="rounded-xl border border-border/50 bg-background/60 p-3 font-mono text-xs">
              <span className="text-indigo-400">Agent Pod</span> &rarr;{" "}
              <span className="text-muted-foreground">ClusterIP</span> &rarr;{" "}
              <span className="text-indigo-400">github.mcp-hub.svc:8080</span>
            </div>
            <div className="flex flex-wrap gap-2">
              <Badge variant="secondary" className="text-xs">GitHub Hub</Badge>
              <Badge variant="secondary" className="text-xs">PostgreSQL</Badge>
            </div>
          </CardContent>
        </Card>

        <Card className="rounded-2xl border-border/60 bg-card/55">
          <CardHeader className="pb-3">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-amber-500/25 bg-amber-500/10 text-amber-500">
                <Box className="h-5 w-5" />
              </div>
              <div>
                <CardTitle className="text-base">Sidecar Containers</CardTitle>
                <CardDescription className="text-sm">Per-agent pod isolation</CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-muted-foreground">
            <p className="leading-relaxed">
              Run inside the agent's own pod as additional containers. Full isolation with localhost-only networking.
              Best for browser automation, local filesystem, and compute-intensive tasks.
            </p>
            <div className="rounded-xl border border-border/50 bg-background/60 p-3 font-mono text-xs">
              <span className="text-amber-400">Agent Container</span> &rarr;{" "}
              <span className="text-muted-foreground">localhost:8093</span> &rarr;{" "}
              <span className="text-amber-400">Playwright Sidecar</span>
            </div>
            <div className="flex flex-wrap gap-2">
              <Badge variant="secondary" className="text-xs">Playwright</Badge>
              <Badge variant="secondary" className="text-xs">Filesystem</Badge>
              <Badge variant="secondary" className="text-xs">Docker</Badge>
            </div>
          </CardContent>
        </Card>

        <Card className="rounded-2xl border-border/60 bg-card/55">
          <CardHeader className="pb-3">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-emerald-500/25 bg-emerald-500/10 text-emerald-500">
                <Shield className="h-5 w-5" />
              </div>
              <div>
                <CardTitle className="text-base">Security Model</CardTitle>
                <CardDescription className="text-sm">Per-agent NetworkPolicy enforcement</CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-3 text-sm text-muted-foreground">
            <p className="leading-relaxed">
              Each agent gets a Kubernetes NetworkPolicy restricting egress to only its declared MCP servers. Sidecar
              traffic stays on localhost. Hub traffic uses Kubernetes service DNS. Remote traffic is allowed to specific
              external endpoints.
            </p>
            <ul className="list-disc list-inside space-y-1 text-sm">
              <li>
                Agent policies gate{" "}
                <code className="rounded bg-muted px-1.5 py-0.5 text-xs">allowed_mcp_servers</code>
              </li>
              <li>HITL toggle per policy for tool approval</li>
              <li>Credentials stored as Kubernetes Secrets</li>
              <li>gVisor sandbox optional for untrusted workloads</li>
            </ul>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
