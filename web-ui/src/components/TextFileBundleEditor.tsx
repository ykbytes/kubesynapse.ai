import { FileText, PlusCircle, Trash2 } from "lucide-react";

import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { TextFileDraft } from "../types";

interface TextFileBundleEditorProps {
  title: string;
  description: string;
  entries: TextFileDraft[];
  addLabel: string;
  emptyMessage: string;
  pathHint: string;
  contentHint: string;
  onAdd: () => void;
  onChange: (entries: TextFileDraft[]) => void;
}

export function TextFileBundleEditor({
  title,
  description,
  entries,
  addLabel,
  emptyMessage,
  pathHint,
  contentHint,
  onAdd,
  onChange,
}: TextFileBundleEditorProps) {
  function updateEntry(id: string, patch: Partial<TextFileDraft>) {
    onChange(entries.map((entry) => (entry.id === id ? { ...entry, ...patch } : entry)));
  }

  function removeEntry(id: string) {
    onChange(entries.filter((entry) => entry.id !== id));
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="space-y-0.5">
          <h4 className="text-sm font-medium text-foreground">{title}</h4>
          <p className="text-xs text-muted-foreground">{description}</p>
        </div>
        <Button variant="outline" size="sm" className="h-7 gap-1.5 text-xs" onClick={onAdd}>
          <PlusCircle className="h-3.5 w-3.5" />
          {addLabel}
        </Button>
      </div>

      {entries.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-md border border-dashed border-border py-6 text-center">
          <FileText className="h-5 w-5 text-muted-foreground" />
          <p className="text-xs text-muted-foreground max-w-xs">{emptyMessage}</p>
        </div>
      ) : (
        <Accordion type="multiple" defaultValue={entries.map((e) => e.id)} className="space-y-2">
          {entries.map((entry, index) => (
            <AccordionItem key={entry.id} value={entry.id} className="rounded-md border border-border px-3">
              <div className="flex items-center justify-between">
                <AccordionTrigger className="py-2 text-sm font-medium hover:no-underline">
                  {entry.path.trim() || `${title} ${index + 1}`}
                </AccordionTrigger>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 text-muted-foreground hover:text-destructive"
                  onClick={() => removeEntry(entry.id)}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
              <AccordionContent className="space-y-3 pb-3">
                <div className="space-y-1.5">
                  <Label className="text-xs">Relative path</Label>
                  <Input
                    value={entry.path}
                    onChange={(e) => updateEntry(entry.id, { path: e.target.value })}
                    className="h-8 text-xs font-mono"
                  />
                  <p className="text-[11px] text-muted-foreground">{pathHint}</p>
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs">File contents</Label>
                  <Textarea
                    value={entry.content}
                    onChange={(e) => updateEntry(entry.id, { content: e.target.value })}
                    rows={9}
                    className="font-mono text-xs"
                  />
                  <p className="text-[11px] text-muted-foreground">{contentHint}</p>
                </div>
              </AccordionContent>
            </AccordionItem>
          ))}
        </Accordion>
      )}
    </div>
  );
}