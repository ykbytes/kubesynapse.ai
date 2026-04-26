import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronsUpDown, Loader2, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Badge } from "@/components/ui/badge";
import { useConnection } from "@/contexts/ConnectionContext";
import { fetchProviderCatalog } from "@/lib/api";
import type { ProviderCatalogModel } from "@/types";

interface ModelSelectorProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  className?: string;
  /** Show validation error styling */
  invalid?: boolean;
}

export function ModelSelector({
  value,
  onChange,
  placeholder = "Select a model…",
  className,
  invalid,
}: ModelSelectorProps) {
  const { token } = useConnection();
  const [open, setOpen] = useState(false);
  const [models, setModels] = useState<ProviderCatalogModel[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const fetchedRef = useRef(false);

  const loadModels = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const result = await fetchProviderCatalog(token);
      setModels(result);
    } catch {
      setError("Failed to load models");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    if (!fetchedRef.current) {
      fetchedRef.current = true;
      void loadModels();
    }
  }, [loadModels]);

  const handleOpenChange = useCallback(
    (nextOpen: boolean) => {
      setOpen(nextOpen);
      if (nextOpen) void loadModels();
    },
    [loadModels],
  );

  const selectedProvider = useMemo(
    () => models.find((model) => model.model_ref === value || `${model.provider_id}/${model.model_id}` === value),
    [models, value],
  );

  const groupedProviders = useMemo(() => {
    const groups = new Map<string, { label: string; items: ProviderCatalogModel[] }>();
    for (const model of models) {
      const existing = groups.get(model.provider_id);
      if (existing) {
        existing.items.push(model);
        continue;
      }
      groups.set(model.provider_id, { label: model.provider_label, items: [model] });
    }
    return Array.from(groups.entries()).map(([providerId, group]) => ({ providerId, ...group }));
  }, [models]);

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          className={cn(
            "w-full justify-between font-normal text-sm h-9",
            !value && "text-muted-foreground",
            invalid && "border-destructive focus-visible:ring-destructive",
            className,
          )}
        >
          <span className="truncate">
            {value ? (
              <span className="flex items-center gap-2">
                <span className="truncate">{value}</span>
                {selectedProvider && (
                  <Badge variant="outline" className="text-[10px] shrink-0">
                    {selectedProvider.provider_label}
                  </Badge>
                )}
              </span>
            ) : (
              placeholder
            )}
          </span>
          <ChevronsUpDown className="ml-2 h-3.5 w-3.5 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[--radix-popover-trigger-width] p-0" align="start">
        <Command>
          <CommandInput placeholder="Search models…" />
          <CommandList>
            {loading ? (
              <div className="flex items-center justify-center gap-2 py-6 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Loading…
              </div>
            ) : error ? (
              <div className="flex flex-col items-center gap-2 py-6 text-sm text-muted-foreground">
                <span>{error}</span>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 gap-1"
                  onClick={() => void loadModels()}
                >
                  <RefreshCw className="h-3 w-3" />
                  Retry
                </Button>
              </div>
              ) : (
                <>
                  <CommandEmpty>No models found.</CommandEmpty>
                  {groupedProviders.map((provider) => (
                    <CommandGroup key={provider.providerId} heading={provider.label}>
                      {provider.items.map((model) => (
                        <CommandItem
                          key={model.model_ref}
                          value={model.model_ref}
                          onSelect={() => {
                            onChange(model.model_ref === value ? "" : model.model_ref);
                            setOpen(false);
                          }}
                        >
                          <Check
                            className={cn(
                              "h-3.5 w-3.5 shrink-0",
                              value === model.model_ref ? "opacity-100" : "opacity-0",
                            )}
                          />
                          <div className="min-w-0 flex-1">
                            <span className="truncate font-medium text-sm">{model.model_ref}</span>
                            {model.description ? (
                              <p className="truncate text-[11px] text-muted-foreground">{model.description}</p>
                            ) : null}
                          </div>
                        </CommandItem>
                      ))}
                    </CommandGroup>
                  ))}
                </>
              )}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
