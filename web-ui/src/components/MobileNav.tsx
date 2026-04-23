import { Bot, GitBranch, Menu, MessageSquare, Radar } from "lucide-react";
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
  { view: "chat", label: "Chat", icon: MessageSquare },
  { view: "intelligence", label: "Intel", icon: Radar },
];

export function MobileNav({ activeView, onViewChange, sidebarContent }: MobileNavProps) {
  const [sheetOpen, setSheetOpen] = useState(false);
  const primaryViews = new Set(BOTTOM_TABS.map((tab) => tab.view));
  const moreActive = !primaryViews.has(activeView);

  return (
    <>
      {/* Bottom tab bar — visible only on small screens */}
      <nav className="fixed inset-x-0 bottom-0 z-50 flex h-16 items-center gap-1 border-t border-sidebar-border/80 bg-sidebar/92 px-2 backdrop-blur-xl shadow-[0_-10px_28px_-20px_oklch(0_0_0_/_0.55)] md:hidden safe-area-pb">
        {BOTTOM_TABS.map((tab) => {
          const active = activeView === tab.view;
          return (
            <button
              key={tab.view}
              type="button"
              className={`flex min-w-0 flex-1 flex-col items-center justify-center gap-1 rounded-xl px-2 py-2 transition-colors duration-150 ease-productive ${
                active ? "bg-sidebar-accent/85 text-primary shadow-sm" : "text-muted-foreground hover:bg-sidebar-accent/70 hover:text-sidebar-accent-foreground"
              }`}
              onClick={() => {
                setSheetOpen(false);
                onViewChange(tab.view);
              }}
            >
              <tab.icon className="h-5 w-5" />
              <span className="text-[10px] font-medium uppercase tracking-[0.16em]">{tab.label}</span>
            </button>
          );
        })}

        <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
          <SheetTrigger asChild>
            <button
              type="button"
              className={`flex min-w-0 flex-1 flex-col items-center justify-center gap-1 rounded-xl px-2 py-2 transition-colors duration-150 ease-productive ${
                moreActive ? "bg-sidebar-accent/85 text-primary shadow-sm" : "text-muted-foreground hover:bg-sidebar-accent/70 hover:text-sidebar-accent-foreground"
              }`}
              aria-label="More views"
            >
              <Menu className="h-5 w-5" />
              <span className="text-[10px] font-medium uppercase tracking-[0.16em]">More</span>
            </button>
          </SheetTrigger>
          <SheetContent side="left" className="w-[min(18rem,calc(100vw-1rem))] border-r border-sidebar-border/70 bg-sidebar/96 p-0 backdrop-blur-xl">
            {sidebarContent}
          </SheetContent>
        </Sheet>
      </nav>

      {/* Mobile hamburger in top-bar area — hidden if bottom nav visible */}
    </>
  );
}
