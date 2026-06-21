import { Package, Plug } from "lucide-react";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

import { McpManagementPanel } from "./McpManagementPanel";
import { SkillsCatalogPanel } from "./SkillsCatalogPanel";

type CatalogTab = "skills" | "mcp";

interface CatalogPanelProps {
  token: string;
  namespace: string;
  onAttachSkill?: (skillId: string, files: Record<string, string>) => void;
  activeTab: CatalogTab;
  onTabChange: (tab: CatalogTab) => void;
}

export function CatalogPanel({ token, namespace, onAttachSkill, activeTab, onTabChange }: CatalogPanelProps) {
  return (
    <Tabs value={activeTab} onValueChange={(value) => onTabChange(value as CatalogTab)} className="flex h-full flex-col">
      <div className="flex shrink-0 items-center gap-3 border-b border-border/30 px-4 py-2">
        <TabsList className="h-8 gap-0.5 rounded-lg border border-border/40 bg-muted/20 p-0.5">
          <TabsTrigger
            value="mcp"
            className="h-7 gap-1.5 rounded-md px-3 text-xs data-[state=active]:bg-primary/10"
          >
            <Plug className="size-3.5" />
            MCP
          </TabsTrigger>
          <TabsTrigger
            value="skills"
            className="h-7 gap-1.5 rounded-md px-3 text-xs data-[state=active]:bg-primary/10"
          >
            <Package className="size-3.5" />
            Skills
          </TabsTrigger>
        </TabsList>
      </div>

      <TabsContent value="mcp" className="mt-0 min-h-0 flex-1 overflow-hidden">
        <McpManagementPanel token={token} namespace={namespace} />
      </TabsContent>

      <TabsContent value="skills" className="mt-0 min-h-0 flex-1 overflow-hidden">
        <SkillsCatalogPanel token={token} namespace={namespace} onAttachSkill={onAttachSkill} />
      </TabsContent>
    </Tabs>
  );
}
