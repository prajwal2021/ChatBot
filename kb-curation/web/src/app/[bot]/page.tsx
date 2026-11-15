"use client";
import { ArrowRight, BookOpenCheck, ChevronRight, Files, FileText, Globe, ListChecks, Rocket } from "lucide-react";
import Link from "next/link";
import { useApi, type Overview, type Run } from "@/lib/api";
import { useBot } from "@/components/shell";
import { CrawlButton, RunProgress } from "@/components/run";
import { Badge, Card, Empty, ErrorNote, KindBadge, Loading, Page, PageHeader, Stat } from "@/components/ui";
import { ago, cn, dateTime, pathOf, plural, shortDate } from "@/lib/utils";

export default function OverviewPage() {
  const bot = useBot();
  const { data, error, reload } = useApi<Overview>(`/api/chatbots/${bot}/overview`, 2500);
  if (error && !data) return <Page><ErrorNote>{error}</ErrorNote></Page>;
  if (!data) return <Page><Loading /></Page>;
  const fresh = !data.last_run && !data.active_run;
  const steps = [
    { href: "sources", icon: Globe, label: "Sources", value: data.sources, sub: plural(data.sources, "website") + " watched", tone: "" },
    { href: "pages", icon: Files, label: "Pages", value: data.pages.active, sub: data.last_run ? `verified · ${data.pages.skipped} failed checks` : "not crawled yet", tone: "" },
    { href: "review", icon: ListChecks, label: "Review", value: data.waiting, sub: data.waiting ? "waiting for a reviewer" : "nothing waiting", tone: data.waiting ? "amber" : "" },
    { href: "publish", icon: Rocket, label: "Publish", value: data.unpublished_total, sub: data.unpublished_total ? "approved, not yet published" : "everything is published", tone: data.unpublished_total ? "blue" : "" },
    { href: "kb", icon: BookOpenCheck, label: "Knowledge base", value: data.published ? `v${data.published.number}` : "—", sub: data.published ? `${plural(data.published.stats.total ?? 0, "entry", "entries")} live` : "not published yet", tone: data.published ? "green" : "" },
  ];
  return (
    <Page>
      <PageHeader title={data.chatbot.name} description={data.chatbot.description} actions={<CrawlButton bot={bot} active={!!data.active_run} onStarted={reload} label={fresh ? "Run first crawl" : "Check for updates"} />} />
      {data.active_run && <RunProgress run={data.active_run} />}

      <div className="grid grid-cols-5 gap-0 overflow-hidden rounded-2xl border border-line">
        {steps.map((s, i) => (
          <Link key={s.href} href={`/${bot}/${s.href}`} className="group relative border-r border-line bg-white p-4 transition-colors last:border-0 hover:bg-subtle">
            <div className="flex items-center gap-2 text-[13px] font-medium text-neutral-500">
              <s.icon className="size-4" strokeWidth={1.8} /> {s.label}
              <ArrowRight className="ml-auto size-3.5 opacity-0 transition-opacity group-hover:opacity-100" />
            </div>
            <div className="mt-3 flex items-center gap-2">
              <span className="text-[28px] font-semibold leading-none tracking-tight tabular-nums">{typeof s.value === "number" ? s.value.toLocaleString() : s.value}</span>
              {s.tone && <span className={cn("size-2 rounded-full", s.tone === "amber" ? "bg-amber-500" : s.tone === "blue" ? "bg-blue-500" : "bg-emerald-500")} />}
            </div>
            <p className="mt-1.5 text-xs text-muted">{s.sub}</p>
            {i < 4 && <ChevronRight className="absolute -right-2 top-1/2 z-10 size-4 -translate-y-1/2 rounded-full border border-line bg-white p-px text-neutral-400" />}
          </Link>
        ))}
      </div>

      {fresh ? (
        <Card className="mt-6">
          <Empty icon={<Globe className="size-5" />} title="Nothing collected yet" action={<CrawlButton bot={bot} onStarted={reload} label="Run first crawl" />}>
            The first crawl reads every page under this chatbot&apos;s source websites, sorts the content into categories and puts it in the review queue.
          </Empty>
        </Card>
      ) : (
        <>
          <div className="mt-6 grid grid-cols-5 gap-6">
            <Card className="col-span-3 p-5">
              <div className="flex items-baseline justify-between">
                <h2 className="font-semibold">Website changes per crawl</h2>
                <Legend />
              </div>
              <p className="mt-0.5 text-[13px] text-muted">Pages that were new, updated or removed each time the sites were checked.</p>
              <RunChart runs={data.runs} />
            </Card>
            <Card className="col-span-2 p-5">
              <div className="flex items-center justify-between">
                <h2 className="font-semibold">Review queue</h2>
                <Link href={`/${bot}/review`} className="text-[13px] font-medium text-neutral-600 hover:text-ink">Open review →</Link>
              </div>
              <div className="mt-4 space-y-3.5">
                {([["new", "New content", "bg-blue-500"], ["changed", "Changed on the website", "bg-amber-500"], ["removal", "Removed from the website", "bg-red-500"]] as const).map(([k, label, color]) => {
                  const n = data.entries[k];
                  const max = Math.max(data.waiting, 1);
                  return (
                    <Link key={k} href={`/${bot}/review?status=${k}`} className="block">
                      <div className="flex justify-between text-[13px]"><span className="text-neutral-700">{label}</span><span className="font-medium tabular-nums">{n.toLocaleString()}</span></div>
                      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-neutral-100"><div className={cn("h-full rounded-full", color)} style={{ width: `${(n / max) * 100}%` }} /></div>
                    </Link>
                  );
                })}
              </div>
              <div className="mt-5 grid grid-cols-2 gap-3 border-t border-line pt-4 text-[13px]">
                <div><p className="text-muted">Approved</p><p className="text-lg font-semibold tabular-nums">{data.entries.approved.toLocaleString()}</p></div>
                <div><p className="text-muted">Rejected</p><p className="text-lg font-semibold tabular-nums">{data.entries.rejected.toLocaleString()}</p></div>
              </div>
            </Card>
          </div>

          <div className="mt-6 grid grid-cols-5 gap-6">
            <Card className="col-span-3">
              <div className="flex items-center justify-between px-5 pt-5">
                <h2 className="font-semibold">Latest changes on the website</h2>
                <Link href={`/${bot}/changes`} className="text-[13px] font-medium text-neutral-600 hover:text-ink">All changes →</Link>
              </div>
              <div className="mt-3 divide-y divide-line border-t border-line">
                {data.recent.length === 0 && <p className="px-5 py-6 text-sm text-muted">No changes detected yet.</p>}
                {data.recent.map((ev) => (
                  <Link key={ev.id} href={`/${bot}/pages?page=${ev.page.id}`} className="flex items-center gap-3 px-5 py-2.5 hover:bg-subtle">
                    <KindBadge kind={ev.kind} />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[13px] font-medium">{ev.page.title}</p>
                      <p className="truncate font-mono text-[11px] text-muted">{pathOf(ev.page.url)}</p>
                    </div>
                    <Stat added={ev.added} removed={ev.removed} />
                    <span className="w-16 shrink-0 text-right text-xs text-muted">{ago(ev.created_at)}</span>
                  </Link>
                ))}
              </div>
            </Card>
            <Card className="col-span-2 p-5">
              <h2 className="font-semibold">Published knowledge base</h2>
              {data.published ? (
                <>
                  <div className="mt-3 flex items-center gap-2">
                    <span className="text-2xl font-semibold tracking-tight">Version {data.published.number}</span>
                    <Badge tone="green" dot>Live</Badge>
                  </div>
                  <p className="mt-1 text-[13px] text-muted">Published {dateTime(data.published.created_at)} by {data.published.created_by}</p>
                  <div className="mt-4 space-y-2 border-t border-line pt-4 text-[13px]">
                    <Row label="Entries"><b className="tabular-nums">{(data.published.stats.total ?? 0).toLocaleString()}</b></Row>
                    <Row label="Approved changes not yet published">{data.unpublished_total ? <Link className="font-medium text-blue-700" href={`/${bot}/publish`}>{data.unpublished_total} to publish →</Link> : "None"}</Row>
                    <Row label="Google Doc">{data.document.gdoc_url ? (data.document.synced_version === data.published.number ? "Up to date" : "Not synced") : <Link className="font-medium text-neutral-700" href={`/${bot}/document`}>Not linked →</Link>}</Row>
                  </div>
                </>
              ) : (
                <div className="mt-3 text-[13px] text-muted">
                  <FileText className="mb-2 size-5 text-neutral-400" />
                  Nothing published yet. Approve entries in <Link href={`/${bot}/review`} className="font-medium text-ink underline">Review</Link>, then publish the first version.
                </div>
              )}
            </Card>
          </div>
        </>
      )}
    </Page>
  );
}

const Row = ({ label, children }: { label: string; children: React.ReactNode }) => <div className="flex justify-between gap-3"><span className="text-muted">{label}</span><span>{children}</span></div>;

const Legend = () => (
  <div className="flex gap-3 text-xs text-muted">
    {[["bg-blue-500", "New"], ["bg-amber-500", "Updated"], ["bg-red-500", "Removed"]].map(([c, l]) => <span key={l} className="flex items-center gap-1.5"><span className={cn("size-2 rounded-sm", c)} />{l}</span>)}
  </div>
);

function RunChart({ runs }: { runs: Run[] }) {
  const H = 132;
  const max = Math.max(1, ...runs.map((r) => (r.stats.new ?? 0) + (r.stats.changed ?? 0) + (r.stats.removed ?? 0)));
  const h = (v: number) => (v ? Math.max(3, (Math.sqrt(v) / Math.sqrt(max)) * H) : 0);     // square-root scale keeps small crawls visible
  if (!runs.length) return <p className="py-10 text-center text-sm text-muted">The chart fills in after the first crawl.</p>;
  return (
    <div className="mt-5 flex items-end gap-2" style={{ height: H + 40 }}>
      {runs.map((r) => {
        const parts = [["new", "bg-blue-500"], ["changed", "bg-amber-500"], ["removed", "bg-red-500"]] as const;
        const total = parts.reduce((s, [k]) => s + (r.stats[k] ?? 0), 0);
        const scale = total ? h(total) / parts.reduce((s, [k]) => s + (r.stats[k] ?? 0), 0) : 0;
        return (
          <div key={r.id} className="group flex min-w-0 flex-1 flex-col items-center" title={`${dateTime(r.finished_at)} — ${r.stats.new ?? 0} new, ${r.stats.changed ?? 0} updated, ${r.stats.removed ?? 0} removed, ${r.stats.unchanged ?? 0} unchanged`}>
            <span className="mb-1 text-[11px] font-medium tabular-nums text-neutral-500">{total || ""}</span>
            <div className="flex w-full max-w-10 flex-col-reverse overflow-hidden rounded-md">
              {total === 0 && <div className="h-[3px] bg-neutral-200" />}
              {parts.map(([k, c]) => (r.stats[k] ? <div key={k} className={c} style={{ height: Math.max(2, (r.stats[k] ?? 0) * scale) }} /> : null))}
            </div>
            <span className="mt-2 truncate text-[11px] text-muted">{shortDate(r.finished_at ?? r.created_at)}</span>
            <span className="truncate text-[10px] text-neutral-400">{new Date(r.finished_at ?? r.created_at).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}</span>
          </div>
        );
      })}
    </div>
  );
}
