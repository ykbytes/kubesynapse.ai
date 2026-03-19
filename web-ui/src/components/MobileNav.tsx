import { Bot, FlaskConical, GitBranch, Package, Menu, Settings } from "lucide-react";
import { useState } from "react";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import type { WorkspaceView } from "@/types";

interface MobileNavProps {
  activeView: WorkspaceView;
  onViewChange: (view: WorkspaceView) => void;
  sidebarContent: React.ReactNode;
}

const BOTTOM_TABS: { view: WorkspaceView; label: string; icon: typeof Bot }[] = [
  { view: "agents", label: "Agents", icon: Bot },
  { view: "workflows", label: "Flows", icon: GitBranch },
  { view: "evals", label: "Evals", icon: FlaskConical },
  { view: "catalog", label: "Catalog", icon: Package },
  { view: "settings", label: "Settings", icon: Settings },
];

export function MobileNav({ activeView, onViewChange, sidebarContent }: MobileNavProps) {
  const [sheetOpen, setSheetOpen] = useState(false);

  return (
    <>
      {/* Bottom tab bar — visible only on small screens */}
      <nav className="fixed bottom-0 inset-x-0 z-50 flex md:hidden h-14 items-center justify-around border-t border-border bg-sidebar/95 backdrop-blur-md safe-area-pb">
        <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
          <SheetTrigger asChild>
            <button
              type="button"
              className="flex flex-col items-center justify-center gap-0.5 px-2 py-1 text-muted-foreground"
              aria-label="Menu"
            >
              <Menu className="h-5 w-5" />
              <span className="text-[10px]">Menu</span>
            </button>
          </SheetTrigger>
          <SheetContent side="left" className="w-72 p-0">
            {sidebarContent}
          </SheetContent>
        </Sheet>

        {BOTTOM_TABS.map((tab) => {
          const active = activeView === tab.view;
          return (
            <button
              key={tab.view}
              type="button"
              className={`flex flex-col items-center justify-center gap-0.5 px-2 py-1 transition-colors ${
                active ? "text-primary" : "text-muted-foreground"
              }`}
              onClick={() => onViewChange(tab.view)}
            >
              <tab.icon className="h-5 w-5" />
              <span className="text-[10px]">{tab.label}</span>
            </button>
          );
        })}
      </nav>

      {/* Mobile hamburger in top-bar area — hidden if bottom nav visible */}
    </>
  );
}
