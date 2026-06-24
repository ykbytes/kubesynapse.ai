import type { ReactNode } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { AlertTriangle, Info } from "lucide-react";

interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: "destructive" | "default";
  children?: ReactNode;
  onConfirm: () => void;
}

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  variant = "default",
  children,
  onConfirm,
}: ConfirmDialogProps) {
  const isDestructive = variant === "destructive";
  const Icon = isDestructive ? AlertTriangle : Info;
  const dialogTitleId = "confirm-dialog-title";
  const dialogDescId = "confirm-dialog-description";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="sm:max-w-[400px]"
        aria-labelledby={dialogTitleId}
        aria-describedby={dialogDescId}
      >
        <DialogHeader>
          <div className="flex items-center gap-2.5">
            <div
              className={`rounded-xl p-2.5 ring-1 shadow-md animate-bounce-in ${isDestructive ? "bg-destructive/15 ring-destructive/30 shadow-destructive/15" : "bg-primary/15 ring-primary/30 shadow-primary/15"}`}
              aria-hidden="true"
            >
              <Icon className={`h-4 w-4 ${isDestructive ? "text-destructive" : "text-primary"}`} />
            </div>
            <DialogTitle id={dialogTitleId}>{title}</DialogTitle>
          </div>
          <DialogDescription id={dialogDescId} className="pt-1">
            {description}
          </DialogDescription>
        </DialogHeader>
        {children ? <div className="pt-1">{children}</div> : null}
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            aria-label={cancelLabel}
          >
            {cancelLabel}
          </Button>
          <Button
            variant={variant === "destructive" ? "destructive" : "default"}
            aria-label={confirmLabel}
            onClick={() => {
              onConfirm();
              onOpenChange(false);
            }}
          >
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
