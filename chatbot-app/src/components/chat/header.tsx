"use client";

import { Menu, SquarePen } from "lucide-react";
import { ThemeToggle } from "@/components/theme-toggle";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

interface ChatHeaderProps {
  conversationTitle: string;
  assistantName: string;
  onOpenSidebar: () => void;
  onNewChat: () => void;
}

export function ChatHeader({ conversationTitle, assistantName, onOpenSidebar, onNewChat }: ChatHeaderProps) {
  return (
    <header className="sticky top-0 z-20 flex h-14 shrink-0 items-center gap-2 border-b border-border/70 bg-background/85 px-3 backdrop-blur-md md:px-5">
      <HeaderButton label="Open sidebar" onClick={onOpenSidebar} className="md:hidden">
        <Menu className="h-[18px] w-[18px]" />
      </HeaderButton>

      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-semibold leading-tight text-foreground">{assistantName}</p>
        <p className="truncate text-xs leading-tight text-muted-foreground">{conversationTitle}</p>
      </div>

      <HeaderButton label="New chat" onClick={onNewChat} className="md:hidden">
        <SquarePen className="h-4 w-4" />
      </HeaderButton>
      <ThemeToggle />
    </header>
  );
}

function HeaderButton({
  label,
  onClick,
  className,
  children,
}: {
  label: string;
  onClick: () => void;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger
        onClick={onClick}
        aria-label={label}
        className={`inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-accent hover:text-foreground ${className ?? ""}`}
      >
        {children}
      </TooltipTrigger>
      <TooltipContent side="bottom" className="text-xs">
        {label}
      </TooltipContent>
    </Tooltip>
  );
}
