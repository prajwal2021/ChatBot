"use client";

import { ArrowUpRight } from "lucide-react";
import { BrandMark } from "@/components/chat/brand-mark";
import { AgentMeta } from "@/lib/agents";

interface EmptyStateProps {
  meta: AgentMeta;
  onSuggestion: (prompt: string) => void;
}

export function EmptyState({ meta, onSuggestion }: EmptyStateProps) {
  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col items-center px-5 pb-8 pt-[12vh] text-center animate-in fade-in duration-500">
      <BrandMark size="lg" className="mb-5" />
      <h2 className="text-2xl font-semibold tracking-tight text-foreground sm:text-[1.75rem]">
        How can I help you today?
      </h2>
      <p className="mt-2 max-w-md text-sm leading-relaxed text-muted-foreground">{meta.tagline}</p>

      {meta.suggestions.length > 0 && (
        <div className="mt-8 grid w-full grid-cols-1 gap-2.5 sm:grid-cols-2">
          {meta.suggestions.map((s) => (
            <button
              key={s.prompt}
              type="button"
              onClick={() => onSuggestion(s.prompt)}
              className="group flex items-start justify-between gap-3 rounded-xl border border-border bg-card px-4 py-3 text-left shadow-xs transition-all hover:-translate-y-px hover:border-foreground/15 hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <span className="min-w-0">
                <span className="block text-sm font-medium text-foreground">{s.title}</span>
                <span className="mt-0.5 block text-[13px] leading-snug text-muted-foreground">{s.prompt}</span>
              </span>
              <ArrowUpRight className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
