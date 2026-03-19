import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronsUpDown, Loader2, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Badge } from "@/components/ui/badge";
import { useConnection } from "@/contexts/ConnectionContext";
import { fetchLLMProviders } from "@/lib/api";
import type { LLMProvider } from "@/types";

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
  const [providers, setProviders] = useState<LLMProvider[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const fetchedRef = useRef(false);

  const loadModels = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const result = await fetchLLMProviders(token);
      setProviders(result);
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

  // Find which provider the selected model belongs to
  const selectedProvider = useMemo(
    () => providers.find((p) => p.models.some((m) => m.model_name === value)),
    [providers, value],
  );

  // Only show providers that have models
  const activeProviders = useMemo(
    () => providers.filter((p) => p.models.length > 0),
    [providers],
  );

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
                    {selectedProvider.label}
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
                {activeProviders.map((prov) => (
                  <CommandGroup key={prov.key_name} heading={prov.label}>
                    {prov.models.map((m) => (
                      <CommandItem
                        key={m.id || m.model_name}
                        value={m.model_name}
                        onSelect={(v) => {
                          onChange(v === value ? "" : v);
                          setOpen(false);
                        }}
                      >
                        <Check
                          className={cn(
                            "h-3.5 w-3.5 shrink-0",
                            value === m.model_name ? "opacity-100" : "opacity-0",
                          )}
                        />
                        <span className="truncate font-medium text-sm">
                          {m.model_name}
                        </span>
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
