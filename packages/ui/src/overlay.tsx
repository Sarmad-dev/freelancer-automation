"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { useRef, type ReactNode } from "react";
import { Button } from "./button";
import { cn } from "./cn";

export const DialogRoot = Dialog.Root;
export const DialogTrigger = Dialog.Trigger;
export const DialogClose = Dialog.Close;

/**
 * Radix only restores focus to a <Dialog.Trigger>. Our dialogs are usually controlled and opened
 * from arbitrary buttons or shortcuts, so remember what had focus and give it back on close.
 */
export function useFocusRestore() {
  const previous = useRef<HTMLElement | null>(null);
  return {
    onOpenAutoFocus: () => {
      previous.current =
        document.activeElement instanceof HTMLElement ? document.activeElement : null;
    },
    onCloseAutoFocus: (event: Event) => {
      const el = previous.current;
      if (el?.isConnected) {
        event.preventDefault();
        el.focus();
      }
      previous.current = null;
    },
  };
}

const overlay =
  "fixed inset-0 z-50 bg-black/60 data-[state=open]:animate-[fos-fade-in_150ms_ease-out]";

function CloseButton() {
  return (
    <Dialog.Close asChild>
      <Button variant="ghost" size="icon" aria-label="Close" className="absolute top-3 right-3">
        <X className="size-4" aria-hidden />
      </Button>
    </Dialog.Close>
  );
}

export interface ModalProps {
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  title: string;
  description?: string;
  children?: ReactNode;
  footer?: ReactNode;
  className?: string;
}

/** Centered modal. Focus is trapped, Escape closes, focus returns to the trigger. */
export function Modal({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  className,
}: ModalProps) {
  const focus = useFocusRestore();
  return (
    <Dialog.Root
      {...(open !== undefined ? { open } : {})}
      {...(onOpenChange ? { onOpenChange } : {})}
    >
      <Dialog.Portal>
        <Dialog.Overlay className={overlay} />
        <Dialog.Content
          {...focus}
          {...(description ? {} : { "aria-describedby": undefined })}
          className={cn(
            "fixed top-1/2 left-1/2 z-50 w-[calc(100vw-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2",
            "rounded-lg border border-line bg-elevated p-6 shadow-[var(--fos-shadow-elevated)]",
            "data-[state=open]:animate-[fos-pop_150ms_ease-out]",
            className,
          )}
        >
          <Dialog.Title className="pr-8 text-base font-semibold text-fg">{title}</Dialog.Title>
          {description ? (
            <Dialog.Description className="mt-1.5 text-sm text-muted">
              {description}
            </Dialog.Description>
          ) : null}
          {children ? <div className="mt-4">{children}</div> : null}
          {footer ? <div className="mt-6 flex justify-end gap-2">{footer}</div> : null}
          <CloseButton />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
  onConfirm: () => void;
}

/** Confirmation for consequential actions. Cancel is the initially focused (safe) action. */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  destructive = false,
  onConfirm,
}: ConfirmDialogProps) {
  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      description={description}
      footer={
        <>
          <Dialog.Close asChild>
            <Button variant="secondary" autoFocus>
              {cancelLabel}
            </Button>
          </Dialog.Close>
          <Button
            variant={destructive ? "danger" : "primary"}
            onClick={() => {
              onConfirm();
              onOpenChange(false);
            }}
          >
            {confirmLabel}
          </Button>
        </>
      }
    />
  );
}

export interface DrawerProps {
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  title: string;
  description?: string;
  side?: "left" | "right";
  children?: ReactNode;
  footer?: ReactNode;
  className?: string;
  bodyClassName?: string;
}

/** Side sheet for quick edits (right) and the mobile navigation (left). */
export function Drawer({
  open,
  onOpenChange,
  title,
  description,
  side = "right",
  children,
  footer,
  className,
  bodyClassName,
}: DrawerProps) {
  const focus = useFocusRestore();
  return (
    <Dialog.Root
      {...(open !== undefined ? { open } : {})}
      {...(onOpenChange ? { onOpenChange } : {})}
    >
      <Dialog.Portal>
        <Dialog.Overlay className={overlay} />
        <Dialog.Content
          {...focus}
          {...(description ? {} : { "aria-describedby": undefined })}
          className={cn(
            "fixed inset-y-0 z-50 flex w-[min(24rem,100vw-2rem)] flex-col border-line bg-surface shadow-[var(--fos-shadow-elevated)]",
            side === "right"
              ? "right-0 border-l data-[state=open]:animate-[fos-slide-in-right_200ms_ease-out]"
              : "left-0 border-r data-[state=open]:animate-[fos-slide-in-left_200ms_ease-out]",
            className,
          )}
        >
          <div className="border-b border-line p-5 pr-14">
            <Dialog.Title className="text-base font-semibold text-fg">{title}</Dialog.Title>
            {description ? (
              <Dialog.Description className="mt-1 text-sm text-muted">
                {description}
              </Dialog.Description>
            ) : null}
          </div>
          <div className={cn("flex-1 overflow-y-auto p-5", bodyClassName)}>{children}</div>
          {footer ? (
            <div className="flex justify-end gap-2 border-t border-line p-4">{footer}</div>
          ) : null}
          <CloseButton />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
