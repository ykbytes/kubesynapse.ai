import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  BookOpen,
  Search,
  Menu,
  X,
  ChevronRight,
  ExternalLink,
  Bug,
} from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import { SECTIONS } from "./docs/sections";

/* ── Mini TOC helper ── */
function MiniToc({
  activeSection,
  onClick,
}: {
  activeSection: string;
  onClick: (id: string) => void;
}) {
  const section = SECTIONS.find((s) => s.id === activeSection);
  if (!section?.subsections?.length) return null;

  return (
    <div className="space-y-3">
      <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">On this page</p>
      <nav className="space-y-1" aria-label="On this page">
        {section.subsections.map((sub) => (
          <button
            key={sub.id}
            onClick={() => onClick(sub.id)}
            className="block w-full text-left text-sm text-muted-foreground transition-colors hover:text-foreground"
          >
            {sub.title}
          </button>
        ))}
      </nav>
    </div>
  );
}

/* ── Main component ── */
export function DocumentationPanel() {
  const [searchQuery, setSearchQuery] = useState("");
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [activeSection, setActiveSection] = useState(SECTIONS[0]?.id ?? "");
  const contentRef = useRef<HTMLDivElement>(null);

  const filteredSections = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return SECTIONS;
    return SECTIONS.filter(
      (s) => s.title.toLowerCase().includes(q) || s.searchText.toLowerCase().includes(q),
    );
  }, [searchQuery]);

  // Scroll spy with IntersectionObserver
  useEffect(() => {
    if (filteredSections.length === 0) return;
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio);
        if (visible.length > 0) {
          setActiveSection(visible[0].target.id);
        }
      },
      { root: contentRef.current, rootMargin: "-80px 0px -60% 0px", threshold: [0, 0.25, 0.5, 1] },
    );

    filteredSections.forEach((s) => {
      const el = document.getElementById(s.id);
      if (el) observer.observe(el);
    });

    return () => observer.disconnect();
  }, [filteredSections]);

  const scrollToSection = useCallback((id: string) => {
    const el = document.getElementById(id);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
      setActiveSection(id.split("-")[0]);
      setMobileNavOpen(false);
    }
  }, []);

  const handleSearchKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter" && filteredSections.length > 0) {
        scrollToSection(filteredSections[0].id);
      }
    },
    [filteredSections, scrollToSection],
  );

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Sticky search header */}
      <div className="shrink-0 border-b border-border/60 bg-background/95 px-4 py-3 backdrop-blur-sm">
        <div className="flex items-center gap-3">
          {/* Mobile hamburger */}
          <Sheet open={mobileNavOpen} onOpenChange={setMobileNavOpen}>
            <SheetTrigger asChild>
              <Button variant="outline" size="icon" className="h-9 w-9 shrink-0 md:hidden" aria-label="Open table of contents">
                <Menu className="h-4 w-4" />
              </Button>
            </SheetTrigger>
            <SheetContent side="left" className="w-[min(18rem,calc(100vw-1rem))] border-r border-border/70 bg-background/98 p-0 backdrop-blur-sm">
              <div className="flex h-full flex-col">
                <div className="flex items-center gap-2 border-b border-border/60 px-4 py-3">
                  <BookOpen className="h-5 w-5 text-primary" aria-hidden="true" />
                  <span className="text-sm font-semibold text-foreground">Documentation</span>
                </div>
                <ScrollArea className="flex-1">
                  <nav className="space-y-0.5 p-2" aria-label="Documentation sections">
                    {filteredSections.map((s) => {
                      const isActive = activeSection === s.id;
                      return (
                        <button
                          key={s.id}
                          onClick={() => scrollToSection(s.id)}
                          className={cn(
                            "flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition-colors",
                            isActive
                              ? "bg-primary/10 font-medium text-primary"
                              : "text-muted-foreground hover:bg-accent/50 hover:text-foreground",
                          )}
                          aria-current={isActive ? "true" : undefined}
                        >
                          <s.icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                          <span className="line-clamp-1">{s.title}</span>
                          {isActive && <ChevronRight className="ml-auto h-3.5 w-3.5 shrink-0" aria-hidden="true" />}
                        </button>
                      );
                    })}
                    {filteredSections.length === 0 && (
                      <p className="px-3 py-4 text-sm text-muted-foreground">No sections match your search.</p>
                    )}
                  </nav>
                </ScrollArea>
              </div>
            </SheetContent>
          </Sheet>

          <div className="flex min-w-0 flex-1 items-center gap-2">
            <BookOpen className="hidden h-5 w-5 shrink-0 text-primary sm:block" aria-hidden="true" />
            <h1 className="hidden text-base font-semibold text-foreground sm:block">kubesynapse Documentation</h1>
          </div>

          <div className="relative min-w-0 flex-1 md:max-w-md">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
            <Input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={handleSearchKeyDown}
              placeholder="Search documentation..."
              className="h-9 border-border/60 bg-card/60 pl-9 text-sm"
              aria-label="Search documentation"
            />
            {searchQuery && (
              <Button
                variant="ghost"
                size="icon"
                className="absolute right-1 top-1/2 h-7 w-7 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                onClick={() => setSearchQuery("")}
                aria-label="Clear search"
              >
                <X className="h-3.5 w-3.5" />
              </Button>
            )}
          </div>
        </div>
      </div>

      <div className="flex min-h-0 flex-1">
        {/* Desktop TOC sidebar */}
        <aside className="hidden w-[170px] shrink-0 border-r border-border/60 bg-card/30 md:flex">
          <ScrollArea className="h-full w-full">
            <nav className="space-y-0 p-1" aria-label="Documentation sections">
              {filteredSections.map((s) => {
                const isActive = activeSection === s.id;
                return (
                  <button
                    key={s.id}
                    onClick={() => scrollToSection(s.id)}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-sm transition-colors",
                      isActive
                        ? "bg-primary/10 font-medium text-primary"
                        : "text-foreground/70 hover:bg-accent/50 hover:text-foreground",
                    )}
                    aria-current={isActive ? "true" : undefined}
                  >
                    <s.icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                    <span className="line-clamp-1">{s.title}</span>
                  </button>
                );
              })}
              {filteredSections.length === 0 && (
                <p className="px-3 py-4 text-sm text-muted-foreground">No sections match your search.</p>
              )}
            </nav>
          </ScrollArea>
        </aside>

        {/* Content area */}
        <ScrollArea ref={contentRef} className="flex-1">
          <div className="px-4 py-4 sm:px-5 md:px-6">
            {filteredSections.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-20 text-center">
                <Search className="h-10 w-10 text-muted-foreground/40" aria-hidden="true" />
                <h2 className="mt-4 text-lg font-semibold text-foreground">No results found</h2>
                <p className="mt-1 text-sm text-muted-foreground">Try a different keyword or clear your search.</p>
                <Button variant="outline" size="sm" className="mt-4" onClick={() => setSearchQuery("")}>
                  Clear search
                </Button>
              </div>
            ) : (
              <div className="space-y-10">
                {filteredSections.map((section) => (
                  <section key={section.id} id={section.id} className="scroll-mt-24 animate-fade-in">
                    <div className="flex items-center gap-2">
                      <section.icon className="h-5 w-5 text-primary" aria-hidden="true" />
                      <h2 className="text-xl font-semibold tracking-tight text-foreground">{section.title}</h2>
                    </div>
                    <Separator className="my-3" />
                    <div className="text-base leading-6 text-foreground/80">{section.content}</div>
                  </section>
                ))}
              </div>
            )}
          </div>
        </ScrollArea>

        {/* Right sidebar — mini TOC + quick links */}
        <aside className="hidden w-[140px] shrink-0 border-l border-border/60 bg-card/30 xl:block">
          <ScrollArea className="h-full w-full">
            <div className="space-y-4 p-2">
              <MiniToc activeSection={activeSection} onClick={scrollToSection} />

              <div className="space-y-3">
                <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Quick Links</p>
                <nav className="space-y-1" aria-label="Quick links">
                  <a
                    href="https://github.com/kubesynapse/kubesynapse"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
                  >
                    <ExternalLink className="h-3 w-3" />
                    GitHub
                  </a>
                  <a
                    href="https://github.com/kubesynapse/kubesynapse/issues"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
                  >
                    <Bug className="h-3 w-3" />
                    Report Issue
                  </a>
                </nav>
              </div>
            </div>
          </ScrollArea>
        </aside>
      </div>
    </div>
  );
}
