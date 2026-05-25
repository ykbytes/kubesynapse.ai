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
    <Tabs value={activeTab} onValueChange={(value) => onTabChange(value as CatalogTab)} className="flex flex-col gap-4">
      <TabsList className="h-auto w-fit gap-1 rounded-2xl border border-border/60 bg-background/80 p-1">
        <TabsTrigger
          value="mcp"
          className="gap-2 rounded-xl px-3 py-2 text-sm data-[state=active]:bg-primary/10 data-[state=active]:text-foreground data-[state=active]:shadow-none"
        >
          <Plug className="h-4 w-4" />
          MCP
        </TabsTrigger>
        <TabsTrigger
          value="skills"
          className="gap-2 rounded-xl px-3 py-2 text-sm data-[state=active]:bg-primary/10 data-[state=active]:text-foreground data-[state=active]:shadow-none"
        >
          <Package className="h-4 w-4" />
          Skills
        </TabsTrigger>
      </TabsList>

      <TabsContent value="mcp" className="mt-0">
        <McpManagementPanel token={token} namespace={namespace} />
      </TabsContent>

      <TabsContent value="skills" className="mt-0">
        <SkillsCatalogPanel token={token} onAttachSkill={onAttachSkill} />
      </TabsContent>
    </Tabs>
  );
}