"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { Command } from "cmdk";
import type { ReactNode } from "react";
import { useFocusRestore } from "./overlay";

export interface CommandItem {
  id: string;
  label: string;
  /** Extra search terms. */
  keywords?: string[];
  icon?: ReactNode;
  hint?: string;
  onSelect: () => void;
}
export interface CommandGroup {
  heading: string;
  items: CommandItem[];
}

/** Ctrl/⌘+K palette. Actions only; record search arrives with the data features. */
export function CommandPalette({
  open,
  onOpenChange,
  groups,
  footer,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  groups: CommandGroup[];
  footer?: ReactNode;
}) {
  const focus = useFocusRestore();
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/60 data-[state=open]:animate-[fos-fade-in_150ms_ease-out]" />
        <Dialog.Content
          {...focus}
          aria-describedby={undefined}
          className="fixed top-[15vh] left-1/2 z-50 w-[calc(100vw-2rem)] max-w-xl -translate-x-1/2 overflow-hidden rounded-lg border border-line bg-elevated shadow-[var(--fos-shadow-elevated)] data-[state=open]:animate-[fos-pop_150ms_ease-out]"
        >
          <Dialog.Title className="sr-only">Command palette</Dialog.Title>
          <Command label="Command palette" loop>
            <Command.Input
              placeholder="Type a command or page name…"
              className="h-12 w-full border-b border-line bg-transparent px-4 text-sm text-fg outline-none placeholder:text-muted"
            />
            <Command.List className="max-h-80 overflow-y-auto p-2">
              <Command.Empty className="px-3 py-6 text-center text-sm text-muted">
                No matching commands.
              </Command.Empty>
              {groups.map((g) => (
                <Command.Group
                  key={g.heading}
                  heading={g.heading}
                  className="[&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted"
                >
                  {g.items.map((item) => (
                    <Command.Item
                      key={item.id}
                      value={`${g.heading} ${item.label}`}
                      keywords={item.keywords ?? []}
                      onSelect={() => {
                        onOpenChange(false);
                        item.onSelect();
                      }}
                      className="flex cursor-default items-center gap-3 rounded-md px-3 py-2 text-sm text-fg data-[selected=true]:bg-surface"
                    >
                      <span className="text-muted" aria-hidden>
                        {item.icon}
                      </span>
                      <span className="flex-1">{item.label}</span>
                      {item.hint ? <span className="text-xs text-muted">{item.hint}</span> : null}
                    </Command.Item>
                  ))}
                </Command.Group>
              ))}
            </Command.List>
          </Command>
          {footer ? (
            <div className="border-t border-line px-4 py-2 text-xs text-muted">{footer}</div>
          ) : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
