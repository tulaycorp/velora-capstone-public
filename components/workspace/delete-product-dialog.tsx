"use client";

import { useState } from "react";
import { LoaderCircle, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { deleteProduct } from "@/lib/backend-api";

type DeleteProductDialogProps = {
  productId: string;
  productTitle: string;
  buttonLabel: string;
  ariaLabel?: string;
  disabled?: boolean;
  className?: string;
  hasProviderRecord?: boolean;
  iconOnly?: boolean;
  onDeleted?: (productId: string) => void;
};

export function DeleteProductDialog({
  productId,
  productTitle,
  buttonLabel,
  ariaLabel,
  disabled = false,
  className,
  hasProviderRecord = false,
  iconOnly = false,
  onDeleted
}: DeleteProductDialogProps) {
  const [open, setOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleDelete() {
    setDeleting(true);
    setError(null);
    try {
      await deleteProduct(productId);
      setOpen(false);
      onDeleted?.(productId);
    } catch (deleteError) {
      setError(
        deleteError instanceof Error
          ? deleteError.message
          : "Unable to delete this product from Velora."
      );
    } finally {
      setDeleting(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (deleting) {
          return;
        }
        setOpen(nextOpen);
        if (!nextOpen) {
          setError(null);
        }
      }}
    >
      <Button
        variant="outline"
        size={iconOnly ? "icon" : "default"}
        className={[
          "border-red-500/30 bg-transparent text-red-300 hover:bg-red-500/10 hover:text-red-200",
          className
        ]
          .filter(Boolean)
          .join(" ")}
        aria-label={ariaLabel ?? buttonLabel}
        title={ariaLabel ?? buttonLabel}
        disabled={disabled}
        onClick={() => setOpen(true)}
      >
        <Trash2 className="h-4 w-4" />
        {iconOnly ? <span className="sr-only">{buttonLabel}</span> : buttonLabel}
      </Button>

      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Delete product</DialogTitle>
          <DialogDescription>
            Remove <span className="text-foreground">{productTitle}</span> from Velora.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 rounded-md border border-red-500/20 bg-red-500/5 p-4">
          <p className="text-sm leading-6 text-muted-foreground">
            This will remove this product from the Velora database and it can no longer be edited on Velora.
          </p>
          {hasProviderRecord ? (
            <p className="text-sm leading-6 text-muted-foreground">
              Any provider or storefront listing already created outside Velora is not deleted by this action.
            </p>
          ) : null}
        </div>

        {error ? (
          <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {error}
          </div>
        ) : null}

        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)} disabled={deleting}>
            Keep product
          </Button>
          <Button
            className="border-red-500 bg-red-500 text-white hover:bg-red-500/90"
            onClick={() => void handleDelete()}
            disabled={deleting}
          >
            {deleting ? <LoaderCircle className="animate-spin" /> : <Trash2 className="h-4 w-4" />}
            Delete product
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
