"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";

export interface NavigatorItem {
  id: string;
  label: string;
}

interface ChatNavigatorProps {
  items: NavigatorItem[];
  activeId: string | null;
  onJump: (id: string) => void;
}

/**
 * Right-edge rail with one bar per question in the conversation. Hovering
 * reveals the questions; clicking one scrolls to it.
 */
export function ChatNavigator({ items, activeId, onJump }: ChatNavigatorProps) {
  const [open, setOpen] = useState(false);
  if (items.length < 2) return null;

  return (
    <div
      className="absolute right-2 top-1/2 z-10 hidden -translate-y-1/2 lg:block"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget)) setOpen(false);
      }}
    >
      {/* Bars */}
      <div
        className={cn(
          "thin-scroll flex max-h-[60vh] flex-col items-end gap-2 overflow-y-auto py-2 pl-3 pr-1 transition-opacity",
          open ? "opacity-0" : "opacity-100"
        )}
        aria-hidden
      >
        {items.map((item) => (
          <span
            key={item.id}
            className={cn(
              "h-[3px] shrink-0 rounded-full transition-all",
              item.id === activeId ? "w-5 bg-foreground/70" : "w-3 bg-foreground/20"
            )}
          />
        ))}
      </div>

      {/* Expanded list */}
      <div
        className={cn(
          "absolute right-0 top-1/2 w-72 -translate-y-1/2 rounded-xl border border-border bg-popover p-1.5 text-popover-foreground shadow-lg transition-all duration-150",
          open ? "visible translate-x-0 opacity-100" : "invisible translate-x-2 opacity-0"
        )}
      >
        <p className="px-2.5 pb-1 pt-1.5 text-[11px] font-medium text-muted-foreground">
          Jump to a question
        </p>
        <nav className="thin-scroll max-h-[60vh] overflow-y-auto" aria-label="Questions in this chat">
          {items.map((item, i) => (
            <button
              key={item.id}
              type="button"
              onClick={() => {
                onJump(item.id);
                setOpen(false);
              }}
              className={cn(
                "flex w-full items-start gap-2.5 rounded-lg px-2.5 py-2 text-left text-[13px] leading-snug transition-colors hover:bg-accent focus-visible:bg-accent focus-visible:outline-none",
                item.id === activeId ? "font-medium text-foreground" : "text-muted-foreground"
              )}
            >
              <span className="mt-px w-4 shrink-0 text-right tabular-nums text-[11px] text-muted-foreground/70">
                {i + 1}
              </span>
              <span className="line-clamp-2">{item.label}</span>
            </button>
          ))}
        </nav>
      </div>
    </div>
  );
}
