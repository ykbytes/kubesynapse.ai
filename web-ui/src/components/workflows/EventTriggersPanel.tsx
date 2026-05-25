import { useState } from "react";
import { Webhook, Zap } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { WebhookManager } from "./WebhookManager";
import { TriggerManager } from "./TriggerManager";

export function EventTriggersPanel() {
  const [tab, setTab] = useState("webhooks");

  return (
    <div className="flex h-full flex-col gap-3 animate-fade-in">
      <Tabs value={tab} onValueChange={setTab} className="flex h-full flex-col gap-3">
        <div className="flex items-center justify-between">
          <TabsList className="h-auto gap-1.5 rounded-xl border border-border/70 bg-card/55 p-1">
            <TabsTrigger
              value="webhooks"
              className="gap-2 rounded-lg px-3 py-2 text-xs data-[state=active]:bg-primary/10 data-[state=active]:text-foreground data-[state=active]:shadow-none"
            >
              <Webhook className="h-3.5 w-3.5" />
              Webhooks
            </TabsTrigger>
            <TabsTrigger
              value="triggers"
              className="gap-2 rounded-lg px-3 py-2 text-xs data-[state=active]:bg-primary/10 data-[state=active]:text-foreground data-[state=active]:shadow-none"
            >
              <Zap className="h-3.5 w-3.5" />
              Triggers
            </TabsTrigger>
          </TabsList>
        </div>
        <TabsContent value="webhooks" className="mt-0 flex min-h-0 flex-1 flex-col">
          <WebhookManager />
        </TabsContent>
        <TabsContent value="triggers" className="mt-0 flex min-h-0 flex-1 flex-col overflow-auto">
          <TriggerManager />
        </TabsContent>
      </Tabs>
    </div>
  );
}
