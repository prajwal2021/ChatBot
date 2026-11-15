"use client";
import type { DiffLine } from "@/lib/api";
import { cn } from "@/lib/utils";

/** GitHub-style line diff: green additions, red removals, grey context. */
export function DiffView({ lines, className, max = 400 }: { lines: DiffLine[]; className?: string; max?: number }) {
  if (!lines.length) return <p className="px-4 py-3 text-[13px] text-muted">No text changes.</p>;
  const shown = lines.slice(0, max);
  return (
    <div className={cn("overflow-x-auto font-mono text-[12.5px] leading-[1.65]", className)}>
      {shown.map((l, i) =>
        l.t === "@" ? (
          <div key={i} className="border-y border-line bg-subtle px-4 py-0.5 text-[11px] text-neutral-400 first:border-t-0">{l.s.startsWith("@@") ? "⋯" : l.s}</div>
        ) : (
          <div key={i} className={cn("flex", l.t === "+" && "bg-emerald-50", l.t === "-" && "bg-red-50")}>
            <span className={cn("w-7 shrink-0 select-none text-center", l.t === "+" ? "text-emerald-600" : l.t === "-" ? "text-red-500" : "text-neutral-300")}>{l.t === " " ? "" : l.t === "-" ? "−" : "+"}</span>
            <span className={cn("min-w-0 flex-1 whitespace-pre-wrap break-words py-px pr-4", l.t === "+" ? "text-emerald-900" : l.t === "-" ? "text-red-900" : "text-neutral-600")}>{l.s || " "}</span>
          </div>
        ),
      )}
      {lines.length > max && <div className="border-t border-line bg-subtle px-4 py-1.5 text-xs text-muted">{lines.length - max} more lines not shown</div>}
    </div>
  );
}
