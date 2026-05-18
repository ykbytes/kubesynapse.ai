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
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import { SECTIONS } from "./sections";

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
      <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground">On this page</p>
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
    <div className="flex h-full flex-col overflow-hidden bg-background text-foreground">
      {/* Sticky search header */}
      <div className="shrink-0 border-b border-border bg-background px-3 py-2.5 sm:px-4 sm:py-3">
        <div className="flex items-center gap-2 sm:gap-3">
          {/* Mobile hamburger */}
          <Sheet open={mobileNavOpen} onOpenChange={setMobileNavOpen}>
            <SheetTrigger asChild>
              <Button variant="outline" size="icon" className="h-9 w-9 shrink-0 md:hidden" aria-label="Open table of contents">
                <Menu className="h-4 w-4" />
              </Button>
            </SheetTrigger>
            <SheetContent side="left" className="w-[min(18rem,calc(100vw-1rem))] border-r border-border bg-background p-0">
              <div className="flex h-full flex-col">
                <div className="flex items-center gap-2 border-b border-border px-4 py-3">
                  <BookOpen className="h-5 w-5 text-primary" aria-hidden="true" />
                  <span className="text-sm font-bold text-foreground">Documentation</span>
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
                              ? "bg-primary/15 font-semibold text-primary"
                              : "text-muted-foreground hover:bg-muted hover:text-foreground",
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
                      <p className="px-3 py-4 text-sm text-muted-foreground/70">No sections match your search.</p>
                    )}
                  </nav>
                </ScrollArea>
              </div>
            </SheetContent>
          </Sheet>

          <div className="flex min-w-0 flex-1 items-center gap-2">
            <BookOpen className="hidden h-5 w-5 shrink-0 text-primary sm:block" aria-hidden="true" />
            <h1 className="hidden text-base font-bold text-foreground sm:block">KubeSynapse Documentation</h1>
          </div>

          <div className="relative min-w-0 flex-1 max-w-none md:max-w-md">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground/60" aria-hidden="true" />
            <Input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={handleSearchKeyDown}
              placeholder="Search documentation..."
              className="h-9 border-border bg-card pl-9 text-sm text-foreground placeholder:text-muted-foreground/50"
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

      <div className="flex min-h-0 min-w-0 flex-1">
        {/* Desktop TOC sidebar */}
        <aside className="hidden w-[200px] shrink-0 border-r border-border bg-background md:flex">
          <ScrollArea className="h-full w-full">
            <nav className="space-y-0.5 p-2" aria-label="Documentation sections">
              {filteredSections.map((s) => {
                const isActive = activeSection === s.id;
                return (
                  <button
                    key={s.id}
                    onClick={() => scrollToSection(s.id)}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-[13px] transition-colors",
                      isActive
                        ? "bg-primary/15 font-semibold text-primary"
                        : "text-muted-foreground hover:bg-muted hover:text-foreground",
                    )}
                    aria-current={isActive ? "true" : undefined}
                  >
                    <s.icon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                    <span className="line-clamp-1">{s.title}</span>
                  </button>
                );
              })}
              {filteredSections.length === 0 && (
                <p className="px-3 py-4 text-sm text-muted-foreground/70">No sections match your search.</p>
              )}
            </nav>
          </ScrollArea>
        </aside>

        {/* Content area */}
        <div ref={contentRef} className="min-w-0 flex-1 overflow-x-hidden overflow-y-auto">
          <div className="mx-auto w-full max-w-5xl px-4 py-6 sm:px-6 md:px-8 md:py-8">
            {filteredSections.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-20 text-center">
                <Search className="h-10 w-10 text-muted-foreground/50" aria-hidden="true" />
                <h2 className="mt-4 text-lg font-bold text-foreground">No results found</h2>
                <p className="mt-1 text-sm text-muted-foreground">Try a different keyword or clear your search.</p>
                <Button variant="outline" size="sm" className="mt-4" onClick={() => setSearchQuery("")}>
                  Clear search
                </Button>
              </div>
            ) : (
              <div className="space-y-10 sm:space-y-12 md:space-y-14">
                {filteredSections.map((section) => (
                  <section key={section.id} id={section.id} className="min-w-0 scroll-mt-24">
                    <div className="flex flex-wrap items-center gap-2.5">
                      <section.icon className="h-5 w-5 text-primary" aria-hidden="true" />
                      <h2 className="text-lg font-bold tracking-tight text-foreground sm:text-xl">{section.title}</h2>
                    </div>
                    <div className="my-5 h-px bg-border" />
                    <div className="docs-content min-w-0 max-w-full break-words text-sm leading-7 text-foreground [overflow-wrap:anywhere] [&>*]:min-w-0 sm:text-[15px]">{section.content}</div>
                  </section>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Right sidebar — mini TOC + quick links */}
        <aside className="hidden w-[180px] shrink-0 border-l border-border bg-background xl:block">
          <ScrollArea className="h-full w-full">
            <div className="space-y-6 p-3">
              <MiniToc activeSection={activeSection} onClick={scrollToSection} />

              <div className="space-y-3">
                <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Quick Links</p>
                <nav className="space-y-1.5" aria-label="Quick links">
                  <a
                    href="https://github.com/ykbytes/kubesynapse.ai"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
                  >
                    <ExternalLink className="h-3 w-3" />
                    GitHub
                  </a>
                  <a
                    href="https://github.com/ykbytes/kubesynapse.ai/issues"
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
