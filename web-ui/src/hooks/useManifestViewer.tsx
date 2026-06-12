import { useState } from "react";
import { FileText } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PremiumModal } from "@/components/shared/PremiumModal";
import { ManifestViewer } from "@/components/shared/ManifestViewer";
import { toast } from "sonner";

interface UseManifestViewerProps {
  resourceType: "workflow" | "agent";
  resourceName: string;
  namespace?: string;
  token?: string;
}

export function useManifestViewer({
  resourceType,
  resourceName,
  namespace = "default",
  token = "",
}: UseManifestViewerProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [manifest, setManifest] = useState<Record<string, unknown> | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const fetchManifest = async () => {
    if (!token) {
      toast.error("Authentication token required");
      return;
    }

    setIsLoading(true);
    try {
      const endpoint =
        resourceType === "workflow"
          ? `/api/workflows/${namespace}/${resourceName}/manifest`
          : `/api/agents/${namespace}/${resourceName}/manifest`;

      const response = await fetch(endpoint, {
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
      });

      if (!response.ok) {
        throw new Error(`Failed to fetch manifest: ${response.statusText}`);
      }

      const data = await response.json();
      setManifest(data);
      setIsOpen(true);
    } catch (error) {
      console.error("Manifest fetch error:", error);
      toast.error(
        error instanceof Error ? error.message : "Failed to fetch manifest"
      );
    } finally {
      setIsLoading(false);
    }
  };

  const ManifestButton = () => (
    <Button
      variant="outline"
      size="sm"
      onClick={fetchManifest}
      disabled={isLoading}
      className="gap-1.5"
    >
      <FileText className="h-3.5 w-3.5" />
      {isLoading ? "Loading..." : "View Manifest"}
    </Button>
  );

  const ManifestModalComponent = () => (
    <PremiumModal
      isOpen={isOpen}
      onOpenChange={setIsOpen}
      title={`Kubernetes Manifest`}
      description={`${resourceType === "workflow" ? "Workflow" : "Agent"}: ${resourceName}`}
      size="xl"
    >
      {manifest && (
        <ManifestViewer
          manifest={manifest}
          resourceName={resourceName}
          resourceKind={
            resourceType === "workflow" ? "Workflow" : "Agent"
          }
          className="mt-4"
        />
      )}
    </PremiumModal>
  );

  return {
    isOpen,
    setIsOpen,
    manifest,
    isLoading,
    fetchManifest,
    ManifestButton,
    ManifestModalComponent,
  };
}
