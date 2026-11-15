"use client";
import { ChevronDown, ChevronRight, ExternalLink, GitCompareArrows } from "lucide-react";
import { useState } from "react";
import { useApi, type PageEvent, type Run } from "@/lib/api";
import { useBot } from "@/components/shell";
import { DiffView } from "@/components/diff";
import { Badge, Card, Empty, ErrorNote, KindBadge, Loading, Page, PageHeader, Stat, Tabs } from "@/components/ui";
import { ago, cn, dateTime, duration, pathOf } from "@/lib/utils";

type Data = { runs: Run[]; run_id: number | null; events: PageEvent[] };
type Kind = "all" | "new" | "changed" | "removed";

export default function ChangesPage() {
  const bot = useBot();
  const [runId, setRunId] = useState<number | null>(null);
  const [kind, setKind] = useState<Kind>("all");
  const { data, error } = useApi<Data>(`/api/chatbots/${bot}/changes${runId ? `?run_id=${runId}` : ""}`);
  const run = data?.runs.find((r) => r.id === data.run_id);
  const count = (k: string) => data?.events.filter((e) => e.kind === k).length ?? 0;
  const events = data?.events.filter((e) => kind === "all" || e.kind === kind || (kind === "changed" && e.kind === "restored")) ?? [];

  return (
    <Page wide>
      <PageHeader title="Changes" description="What was different on the websites each time they were checked. Pick a crawl to see exactly which pages were added, updated or removed, line by line." />
      {error && <ErrorNote>{error}</ErrorNote>}
      {!data ? <Loading /> : data.runs.length === 0 ? (
        <Card><Empty icon={<GitCompareArrows className="size-5" />} title="No crawls yet">Changes appear here after the first crawl.</Empty></Card>
      ) : (
        <div className="grid grid-cols-[300px_1fr] gap-6">
          <div>
            <p className="mb-2 px-1 text-xs font-medium uppercase tracking-wider text-neutral-400">Crawls</p>
            <div className="relative space-y-1">
              {data.runs.map((r) => {
                const n = (r.stats.new ?? 0) + (r.stats.changed ?? 0) + (r.stats.removed ?? 0) + (r.stats.restored ?? 0);
                return (
                  <button key={r.id} onClick={() => { setRunId(r.id); setKind("all"); }} className={cn("flex w-full items-start gap-3 rounded-xl border px-3 py-2.5 text-left transition-colors", r.id === data.run_id ? "border-neutral-300 bg-white shadow-sm" : "border-transparent hover:bg-subtle")}>
                    <span className={cn("mt-1.5 size-2 shrink-0 rounded-full", r.status === "failed" ? "bg-red-500" : n ? "bg-ink" : "bg-neutral-300")} />
                    <span className="min-w-0 flex-1">
                      <span className="block text-[13px] font-medium">{dateTime(r.finished_at ?? r.created_at)}</span>
                      <span className="mt-0.5 flex flex-wrap gap-x-2 text-xs text-muted">
                        {r.status === "failed" ? <span className="text-red-600">Failed</span> : n === 0 ? "No changes" : <>
                          {!!r.stats.new && <span className="text-blue-700">{r.stats.new} new</span>}
                          {!!r.stats.changed && <span className="text-amber-700">{r.stats.changed} updated</span>}
                          {!!r.stats.removed && <span className="text-red-600">{r.stats.removed} removed</span>}
                        </>}
                        <span>· {r.trigger === "schedule" ? "scheduled" : r.created_by}</span>
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="min-w-0">
            {run && (
              <Card className="mb-4 p-5">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <h2 className="font-semibold">Crawl on {dateTime(run.finished_at ?? run.created_at)}</h2>
                  {run.status === "failed" ? <Badge tone="red" dot>Failed</Badge> : <Badge tone="green" dot>Completed</Badge>}
                  <span className="text-[13px] text-muted">took {duration(run.started_at, run.finished_at)} · {ago(run.finished_at)}</span>
                </div>
                {run.error && <p className="mt-2 text-[13px] text-red-600">{run.error}</p>}
                <div className="mt-4 grid grid-cols-6 gap-3">
                  {[["URLs found", run.stats.discovered, ""], ["New pages", run.stats.new, "text-blue-700"], ["Updated", run.stats.changed, "text-amber-700"], ["Removed", run.stats.removed, "text-red-600"], ["Unchanged", run.stats.unchanged, ""], ["Sent to review", (run.stats.entries_new ?? 0) + (run.stats.entries_changed ?? 0) + (run.stats.entries_removal ?? 0), ""]].map(([l, v, c]) => (
                    <div key={l as string}><p className="text-xs text-muted">{l}</p><p className={cn("mt-0.5 text-xl font-semibold tabular-nums", v ? (c as string) : "text-neutral-300")}>{((v as number) ?? 0).toLocaleString()}</p></div>
                  ))}
                </div>
              </Card>
            )}
            <div className="mb-3 flex items-center justify-between">
              <Tabs value={kind} onChange={setKind} items={[{ value: "all", label: "All", count: data.events.length }, { value: "new", label: "New", count: count("new") }, { value: "changed", label: "Updated", count: count("changed") + count("restored") }, { value: "removed", label: "Removed", count: count("removed") }]} />
              <span className="text-xs text-muted">Click a page to see its diff</span>
            </div>
            {events.length === 0 ? <Card><p className="px-5 py-10 text-center text-sm text-muted">{data.events.length ? "No pages of this kind in this crawl." : "Nothing changed on the website in this crawl."}</p></Card> : (
              <div className="space-y-2">{events.map((ev) => <EventRow key={ev.id} ev={ev} startOpen={events.length <= 3} />)}</div>
            )}
          </div>
        </div>
      )}
    </Page>
  );
}

function EventRow({ ev, startOpen }: { ev: PageEvent; startOpen: boolean }) {
  const [open, setOpen] = useState(startOpen);
  const { data } = useApi<PageEvent>(open ? `/api/events/${ev.id}` : null);
  return (
    <div className="overflow-hidden rounded-xl border border-line bg-white">
      <div role="button" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && setOpen((o) => !o)} onClick={() => setOpen((o) => !o)} className="flex cursor-pointer items-center gap-3 bg-subtle/60 px-3.5 py-2.5 hover:bg-subtle">
        {open ? <ChevronDown className="size-4 text-neutral-400" /> : <ChevronRight className="size-4 text-neutral-400" />}
        <KindBadge kind={ev.kind} />
        <div className="min-w-0 flex-1">
          <span className="text-[13px] font-medium">{ev.page.title}</span>
          <span className="ml-2 font-mono text-[11px] text-muted">{pathOf(ev.page.url)}</span>
        </div>
        <Stat added={ev.added} removed={ev.removed} />
        <DiffBar added={ev.added} removed={ev.removed} />
        <a href={ev.page.url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} aria-label="Open page" className="rounded p-1 text-neutral-400 hover:text-ink"><ExternalLink className="size-3.5" /></a>
      </div>
      {open && <div className="border-t border-line">{data?.diff ? <DiffView lines={data.diff} max={ev.kind === "changed" ? 400 : 60} /> : <p className="px-4 py-3 text-[13px] text-muted">Loading…</p>}</div>}
    </div>
  );
}

/** Five squares like GitHub's diffstat. */
function DiffBar({ added, removed }: { added: number; removed: number }) {
  const total = added + removed || 1;
  const g = Math.round((added / total) * 5);
  return <span className="flex gap-px">{[0, 1, 2, 3, 4].map((i) => <span key={i} className={cn("size-2 rounded-[2px]", i < g ? "bg-emerald-500" : removed ? "bg-red-500" : "bg-neutral-200")} />)}</span>;
}
