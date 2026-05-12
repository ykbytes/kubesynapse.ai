import { Activity, Radar } from "lucide-react";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

import { ExecutionObservatory } from "./ExecutionObservatory";
import { IntelligenceDashboard } from "./IntelligenceDashboard";

type IntelligenceTab = "intelligence" | "observatory";

interface IntelligencePanelProps {
  activeTab: IntelligenceTab;
  onTabChange: (tab: IntelligenceTab) => void;
}

export function IntelligencePanel({ activeTab, onTabChange }: IntelligencePanelProps) {
  return (
    <Tabs value={activeTab} onValueChange={(value) => onTabChange(value as IntelligenceTab)} className="flex flex-col gap-4">
      <TabsList className="h-auto w-fit gap-1 rounded-2xl border border-border/60 bg-background/80 p-1">
        <TabsTrigger
          value="observatory"
          className="gap-2 rounded-xl px-3 py-2 text-sm data-[state=active]:bg-primary/10 data-[state=active]:text-foreground data-[state=active]:shadow-none"
        >
          <Activity className="h-4 w-4" />
          Observatory
        </TabsTrigger>
        <TabsTrigger
          value="intelligence"
          className="gap-2 rounded-xl px-3 py-2 text-sm data-[state=active]:bg-primary/10 data-[state=active]:text-foreground data-[state=active]:shadow-none"
        >
          <Radar className="h-4 w-4" />
          Intelligence
        </TabsTrigger>
      </TabsList>

      <TabsContent value="observatory" className="mt-0">
        <ExecutionObservatory />
      </TabsContent>

      <TabsContent value="intelligence" className="mt-0">
        <IntelligenceDashboard />
      </TabsContent>
    </Tabs>
  );
}