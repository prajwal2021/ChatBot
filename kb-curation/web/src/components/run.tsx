"use client";
import { Loader2, Play } from "lucide-react";
import { useState } from "react";
import { api, type Run } from "@/lib/api";
import { pathOf } from "@/lib/utils";
import { Button, useToast } from "./ui";

export function CrawlButton({ bot, active, onStarted, sourceId, label = "Check for updates", variant = "primary" }: { bot: string; active?: boolean; onStarted?: () => void; sourceId?: number; label?: string; variant?: "primary" | "secondary" }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try {
      await api(`/api/chatbots/${bot}/crawl`, { body: { source_id: sourceId ?? null } });
      onStarted?.();
    } catch (e) {
      toast((e as Error).message, true);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Button variant={variant} size={variant === "primary" ? "md" : "sm"} onClick={run} busy={busy} disabled={active}>
      {!busy && <Play className="size-3.5" />} {active ? "Crawl in progress…" : label}
    </Button>
  );
}

const STAGE: Record<string, string> = { queued: "Waiting to start", discovering: "Finding and reading pages", verifying: "Checking every page is working and useful", comparing: "Comparing with the last crawl", categorising: "Sorting new content into categories", done: "Finished" };

/** Live progress of the crawl that is running right now. */
export function RunProgress({ run }: { run: Run }) {
  const p = run.progress ?? {};
  const comparing = run.stage === "comparing";
  const verifying = run.stage === "verifying";
  const done = comparing ? p.applied ?? 0 : p.fetched ?? 0;
  const total = Math.max(p.found ?? 0, 1);
  const pct = run.stage === "categorising" ? 97 : run.status === "queued" ? 2 : Math.min(98, Math.max(4, (done / total) * 100));
  return (
    <div className="rise mb-6 rounded-2xl border border-line bg-white p-4">
      <div className="flex items-center gap-3">
        <span className="flex size-8 items-center justify-center rounded-full bg-ink text-white"><Loader2 className="size-4 animate-spin" /></span>
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-3">
            <p className="font-medium">{STAGE[run.stage] ?? "Working"}…</p>
            <p className="shrink-0 text-xs tabular-nums text-muted">{done.toLocaleString()} of {total.toLocaleString()} {comparing ? "compared" : verifying ? "pages verified" : "addresses opened"}</p>
          </div>
          <p className="truncate font-mono text-xs text-muted">{p.current ? pathOf(p.current) : "Preparing…"}</p>
        </div>
      </div>
      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-neutral-100">
        <div className="progress-live h-full rounded-full bg-ink transition-[width] duration-700" style={{ width: `${pct}%` }} />
      </div>
      <div className="mt-2.5 flex gap-4 text-xs text-muted">
        {["Find pages", "Verify each page", "Detect changes", "Sort for review"].map((s, i) => {
          const at = run.stage === "categorising" ? 3 : run.stage === "comparing" ? 2 : verifying ? 1 : run.status === "queued" ? -1 : 0;
          return <span key={s} className={i <= at ? "font-medium text-ink" : ""}>{i + 1}. {s}</span>;
        })}
      </div>
    </div>
  );
}
