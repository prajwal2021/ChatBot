"use client";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import type { Change } from "@/lib/api";
import { DiffView } from "./diff";
import { KindBadge, Stat } from "./ui";

/** Pull-request style list: one collapsible diff per knowledge entry. */
export function ChangeList({ changes, openFirst = 3 }: { changes: Change[]; openFirst?: number }) {
  return <div className="space-y-2">{changes.map((c, i) => <ChangeRow key={`${c.entry_id}-${c.change}`} c={c} startOpen={i < openFirst} />)}</div>;
}

function ChangeRow({ c, startOpen }: { c: Change; startOpen: boolean }) {
  const [open, setOpen] = useState(startOpen);
  return (
    <div className="overflow-hidden rounded-xl border border-line bg-white">
      <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-3 bg-subtle/60 px-3.5 py-2.5 text-left hover:bg-subtle">
        {open ? <ChevronDown className="size-4 shrink-0 text-neutral-400" /> : <ChevronRight className="size-4 shrink-0 text-neutral-400" />}
        <KindBadge kind={c.change} />
        <span className="min-w-0 flex-1 truncate text-[13px] font-medium">{c.title}</span>
        <span className="shrink-0 text-xs text-muted">{c.category}</span>
        <Stat added={c.added} removed={c.removed} />
      </button>
      {open && (
        <div className="border-t border-line">
          {c.meta.length > 0 && <div className="space-y-0.5 border-b border-line bg-violet-50/50 px-4 py-2 text-xs text-violet-900">{c.meta.map((m) => <p key={m}>{m}</p>)}</div>}
          {c.diff.length > 0 ? <DiffView lines={c.diff} max={80} /> : <p className="px-4 py-3 text-[13px] text-muted">The text is the same; only the details above changed.</p>}
        </div>
      )}
    </div>
  );
}
