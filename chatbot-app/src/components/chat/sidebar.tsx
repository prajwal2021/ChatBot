"use client";

import { useEffect, useRef, useState } from "react";
import {
  MoreHorizontal,
  PanelLeftClose,
  PanelLeftOpen,
  Pencil,
  Pin,
  PinOff,
  Search,
  SquarePen,
  Star,
  StarOff,
  Trash2,
  X,
} from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { BrandMark } from "@/components/chat/brand-mark";
import { cn } from "@/lib/utils";
import { Conversation } from "@/types/chat";

interface SidebarProps {
  conversations: Conversation[];
  activeId: string;
  agentLabel: string;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  onTogglePin: (id: string) => void;
  onToggleFavorite: (id: string) => void;
  onRename: (id: string, title: string) => void;
  collapsed: boolean;
  onToggle: () => void;
  mobileOpen: boolean;
  onMobileClose: () => void;
}

export function Sidebar({
  conversations,
  activeId,
  agentLabel,
  onSelect,
  onNew,
  onDelete,
  onTogglePin,
  onToggleFavorite,
  onRename,
  collapsed,
  onToggle,
  mobileOpen,
  onMobileClose,
}: SidebarProps) {
  const [searchQuery, setSearchQuery] = useState("");

  const query = searchQuery.trim().toLowerCase();
  const visible = conversations
    // Chats with no question yet (including greeting-only chats saved by the
    // previous UI) are placeholders — only the open one is listed.
    .filter((c) => c.messages.some((m) => m.role === "user") || c.id === activeId)
    .filter((c) => !query || c.title.toLowerCase().includes(query))
    .sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime());
  const sections = buildSections(visible);

  const itemHandlers = { onSelect, onDelete, onTogglePin, onToggleFavorite, onRename };

  return (
    <>
      {/* Mobile backdrop */}
      <div
        className={cn(
          "fixed inset-0 z-30 bg-black/40 backdrop-blur-[1px] transition-opacity md:hidden",
          mobileOpen ? "opacity-100" : "pointer-events-none opacity-0"
        )}
        onClick={onMobileClose}
        aria-hidden
      />

      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex w-[280px] flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground transition-[transform,width] duration-300 ease-in-out",
          "md:static md:z-auto md:translate-x-0",
          mobileOpen ? "translate-x-0 shadow-xl" : "-translate-x-full",
          collapsed ? "md:w-[60px]" : "md:w-[280px]"
        )}
        aria-label="Conversations"
      >
        {/* Brand row */}
        <div className="flex h-14 shrink-0 items-center gap-2 px-3">
          <div className={cn("flex min-w-0 flex-1 items-center gap-2.5", collapsed && "md:hidden")}>
            <BrandMark size="sm" />
            <div className="min-w-0 leading-tight">
              <p className="truncate text-sm font-semibold">{agentLabel}</p>
              <p className="truncate text-[11px] text-muted-foreground">Texas Tech University</p>
            </div>
          </div>
          <IconButton
            label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            onClick={onToggle}
            className={cn("hidden md:inline-flex", collapsed && "mx-auto")}
          >
            {collapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
          </IconButton>
          <IconButton label="Close sidebar" onClick={onMobileClose} className="md:hidden">
            <X className="h-4 w-4" />
          </IconButton>
        </div>

        {/* New chat + search */}
        <div className={cn("space-y-2 px-3 pb-2", collapsed && "md:px-2")}>
          {collapsed ? (
            <IconButton label="New chat" onClick={onNew} className="hidden md:mx-auto md:flex">
              <SquarePen className="h-4 w-4" />
            </IconButton>
          ) : null}
          <button
            type="button"
            onClick={onNew}
            className={cn(
              "flex h-9 w-full items-center gap-2 rounded-lg border border-sidebar-border bg-background px-3 text-sm font-medium shadow-xs transition-colors hover:bg-sidebar-accent",
              collapsed && "md:hidden"
            )}
          >
            <SquarePen className="h-4 w-4 text-muted-foreground" />
            New chat
          </button>
          <div className={cn("relative", collapsed && "md:hidden")}>
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <input
              type="text"
              placeholder="Search chats"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="h-8 w-full rounded-lg bg-sidebar-accent/60 pl-8 pr-3 text-sm text-sidebar-foreground placeholder:text-muted-foreground focus:bg-background focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>
        </div>

        {/* Conversation list */}
        <nav className={cn("thin-scroll flex-1 overflow-y-auto px-2 pb-3", collapsed && "md:hidden")}>
          {sections.length === 0 ? (
            <p className="px-3 py-6 text-center text-xs text-muted-foreground">
              {query ? "No chats match your search." : "Your conversations will appear here."}
            </p>
          ) : (
            sections.map((section) => (
              <div key={section.label} className="mt-3 first:mt-1">
                <p className="mb-1 flex items-center gap-1.5 px-2.5 text-[11px] font-medium text-muted-foreground">
                  {section.icon}
                  {section.label}
                </p>
                {section.items.map((c) => (
                  <ConversationItem key={c.id} conversation={c} active={c.id === activeId} {...itemHandlers} />
                ))}
              </div>
            ))
          )}
        </nav>
        {collapsed && <div className="hidden flex-1 md:block" />}

        <div className={cn("border-t border-sidebar-border px-4 py-3 text-[11px] leading-snug text-muted-foreground", collapsed && "md:hidden")}>
          Chats are saved in this browser for 7 days.
        </div>
      </aside>
    </>
  );
}

// ── Item ────────────────────────────────────────────────────────────────────

function ConversationItem({
  conversation,
  active,
  onSelect,
  onDelete,
  onTogglePin,
  onToggleFavorite,
  onRename,
}: {
  conversation: Conversation;
  active: boolean;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onTogglePin: (id: string) => void;
  onToggleFavorite: (id: string) => void;
  onRename: (id: string, title: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(conversation.title);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!editing) return;
    // Wait for the menu to finish closing so it doesn't steal focus back.
    const t = setTimeout(() => inputRef.current?.select(), 30);
    return () => clearTimeout(t);
  }, [editing]);

  const startEditing = () => {
    setDraft(conversation.title);
    setEditing(true);
  };

  const commit = () => {
    const next = draft.trim();
    if (next && next !== conversation.title) onRename(conversation.id, next);
    setEditing(false);
  };

  if (editing) {
    return (
      <div className="px-1 py-0.5">
        <input
          ref={inputRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") commit();
            if (e.key === "Escape") setEditing(false);
          }}
          maxLength={80}
          aria-label="Rename chat"
          className="h-8 w-full rounded-md border border-ring bg-background px-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
        />
      </div>
    );
  }

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onSelect(conversation.id)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect(conversation.id);
        }
      }}
      onDoubleClick={startEditing}
      className={cn(
        "group relative flex h-9 cursor-pointer items-center gap-2 rounded-lg px-2.5 text-sm outline-none transition-colors",
        "hover:bg-sidebar-accent focus-visible:ring-2 focus-visible:ring-ring",
        active && "bg-sidebar-accent font-medium"
      )}
      title={conversation.title}
    >
      <span className="min-w-0 flex-1 truncate">{conversation.title}</span>

      <DropdownMenu>
        <DropdownMenuTrigger
          className={cn(
            "inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-muted-foreground transition hover:bg-background hover:text-foreground",
            "opacity-0 group-hover:opacity-100 focus-visible:opacity-100 data-[popup-open]:opacity-100",
            active && "opacity-100"
          )}
          onClick={(e) => e.stopPropagation()}
          aria-label="Chat options"
        >
          <MoreHorizontal className="h-4 w-4" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-48">
          <DropdownMenuItem
            className="gap-2"
            onClick={(e) => {
              e.stopPropagation();
              onTogglePin(conversation.id);
            }}
          >
            {conversation.pinned ? <PinOff className="h-4 w-4" /> : <Pin className="h-4 w-4" />}
            {conversation.pinned ? "Unpin" : "Pin"}
          </DropdownMenuItem>
          <DropdownMenuItem
            className="gap-2"
            onClick={(e) => {
              e.stopPropagation();
              onToggleFavorite(conversation.id);
            }}
          >
            {conversation.favorite ? <StarOff className="h-4 w-4" /> : <Star className="h-4 w-4" />}
            {conversation.favorite ? "Remove from favorites" : "Add to favorites"}
          </DropdownMenuItem>
          <DropdownMenuItem
            className="gap-2"
            onClick={(e) => {
              e.stopPropagation();
              startEditing();
            }}
          >
            <Pencil className="h-4 w-4" />
            Rename
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem
            variant="destructive"
            className="gap-2"
            onClick={(e) => {
              e.stopPropagation();
              onDelete(conversation.id);
            }}
          >
            <Trash2 className="h-4 w-4" />
            Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

function IconButton({
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
        className={cn(
          "inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-foreground",
          className
        )}
      >
        {children}
      </TooltipTrigger>
      <TooltipContent side="right" className="text-xs">
        {label}
      </TooltipContent>
    </Tooltip>
  );
}

// ── Grouping ──────────────────────────────────────────────────────────────────

interface Section {
  label: string;
  icon?: React.ReactNode;
  items: Conversation[];
}

function buildSections(conversations: Conversation[]): Section[] {
  const pinned = conversations.filter((c) => c.pinned);
  const favorites = conversations.filter((c) => !c.pinned && c.favorite);
  const rest = conversations.filter((c) => !c.pinned && !c.favorite);

  const sections: Section[] = [];
  if (pinned.length) sections.push({ label: "Pinned", icon: <Pin className="h-3 w-3" />, items: pinned });
  if (favorites.length)
    sections.push({ label: "Favorites", icon: <Star className="h-3 w-3" />, items: favorites });

  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  const sevenDaysAgo = new Date(today);
  sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7);

  const byDate: Record<string, Conversation[]> = {};
  const order = ["Today", "Yesterday", "Previous 7 days", "Older"];
  for (const c of rest) {
    const d = new Date(c.updatedAt);
    const label =
      d >= today ? "Today" : d >= yesterday ? "Yesterday" : d >= sevenDaysAgo ? "Previous 7 days" : "Older";
    (byDate[label] ??= []).push(c);
  }
  for (const label of order) {
    if (byDate[label]?.length) sections.push({ label, items: byDate[label] });
  }
  return sections;
}
