"use client";

import * as Dropdown from "@radix-ui/react-dropdown-menu";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { Check } from "lucide-react";
import type { ComponentPropsWithoutRef, ReactNode } from "react";
import { cn } from "./cn";

/* ---------- Dropdown menu ---------- */
export const DropdownMenu = Dropdown.Root;
export const DropdownMenuTrigger = Dropdown.Trigger;
export const DropdownMenuRadioGroup = Dropdown.RadioGroup;

const itemBase =
  "relative flex cursor-default items-center gap-2 rounded-sm px-2.5 py-1.5 text-sm text-fg outline-none select-none " +
  "data-[highlighted]:bg-elevated data-[disabled]:pointer-events-none data-[disabled]:opacity-50";

export function DropdownMenuContent({
  className,
  align = "end",
  sideOffset = 6,
  ...props
}: ComponentPropsWithoutRef<typeof Dropdown.Content>) {
  return (
    <Dropdown.Portal>
      <Dropdown.Content
        align={align}
        sideOffset={sideOffset}
        className={cn(
          "z-50 min-w-48 rounded-md border border-line bg-surface p-1 shadow-[var(--fos-shadow-elevated)]",
          "data-[state=open]:animate-[fos-pop_120ms_ease-out]",
          className,
        )}
        {...props}
      />
    </Dropdown.Portal>
  );
}
export function DropdownMenuItem({
  className,
  ...props
}: ComponentPropsWithoutRef<typeof Dropdown.Item>) {
  return <Dropdown.Item className={cn(itemBase, className)} {...props} />;
}
export function DropdownMenuLabel({
  className,
  ...props
}: ComponentPropsWithoutRef<typeof Dropdown.Label>) {
  return (
    <Dropdown.Label
      className={cn("px-2.5 py-1.5 text-xs font-medium text-muted", className)}
      {...props}
    />
  );
}
export function DropdownMenuSeparator() {
  return <Dropdown.Separator className="my-1 h-px bg-line" />;
}
export function DropdownMenuRadioItem({
  className,
  children,
  ...props
}: ComponentPropsWithoutRef<typeof Dropdown.RadioItem>) {
  return (
    <Dropdown.RadioItem className={cn(itemBase, "pl-8", className)} {...props}>
      <Dropdown.ItemIndicator className="absolute left-2.5">
        <Check className="size-4 text-accent" aria-hidden />
      </Dropdown.ItemIndicator>
      {children}
    </Dropdown.RadioItem>
  );
}

/* ---------- Tabs ---------- */
export const Tabs = TabsPrimitive.Root;
export function TabsList({
  className,
  ...props
}: ComponentPropsWithoutRef<typeof TabsPrimitive.List>) {
  return (
    <TabsPrimitive.List className={cn("flex gap-1 border-b border-line", className)} {...props} />
  );
}
export function TabsTrigger({
  className,
  ...props
}: ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        "-mb-px border-b-2 border-transparent px-3 py-2 text-sm font-medium text-muted transition-colors",
        "hover:text-fg data-[state=active]:border-accent data-[state=active]:text-fg",
        className,
      )}
      {...props}
    />
  );
}
export function TabsContent({
  className,
  ...props
}: ComponentPropsWithoutRef<typeof TabsPrimitive.Content>) {
  return <TabsPrimitive.Content className={cn("pt-4", className)} {...props} />;
}

/* ---------- Tooltip ---------- */
export const TooltipProvider = TooltipPrimitive.Provider;

/** Supplementary label for a focusable element. Never put essential information only in a tooltip. */
export function Tooltip({
  content,
  children,
  side = "right",
}: {
  content: ReactNode;
  children: ReactNode;
  side?: "top" | "right" | "bottom" | "left";
}) {
  return (
    <TooltipPrimitive.Root>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          side={side}
          sideOffset={6}
          className="z-50 rounded-sm border border-line bg-elevated px-2 py-1 text-xs text-fg shadow-[var(--fos-shadow-elevated)]"
        >
          {content}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}
