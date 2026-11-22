"use client";
import { AlertTriangle, ArrowRight, FolderTree, GitCompareArrows, Library, ListChecks, Rocket } from "lucide-react";
import Link from "next/link";
import { useApi } from "@/lib/api";
import type { SnOverview } from "@/lib/sn";
import { useBot } from "@/components/shell";
import { Badge, Button, Card, Empty, ErrorNote, Loading, Page, PageHeader } from "@/components/ui";
import { ago, cn, dateTime, plural, shortUrl } from "@/lib/utils";

export default function SnOverviewPage() {
  const bot = useBot();
  const { data: o, error } = useApi<SnOverview>(`/api/chatbots/${bot}/servicenow/overview`, 15000);

  return (
    <Page>
      <PageHeader
        title="ServiceNow knowledge"
        description="Articles imported once from ServiceNow, kept up to date from the web pages you link to each category. The AI proposes edits when a linked page changes; nothing reaches the chatbot until someone approves and publishes it."
      />
      {error && <ErrorNote>{error}</ErrorNote>}
      {!o ? (!error && <Loading />) : !o.imported ? (
        <Card><Empty icon={<Library className="size-5" />} title="Nothing imported yet">The ServiceNow articles for this chatbot have not been imported. The import is a one-time step run from a signed-in ServiceNow session.</Empty></Card>
      ) : (
        <>
          <div className="grid grid-cols-4 gap-3">
            <Tile href={`/${bot}/servicenow/review`} icon={ListChecks} label="Waiting for review" value={o.waiting} hint={[
              o.waiting_by_kind.import && `${o.waiting_by_kind.import} imported`, o.waiting_by_kind.update && `${o.waiting_by_kind.update} AI updates`,
              o.waiting_by_kind.new && `${o.waiting_by_kind.new} new`, o.waiting_by_kind.remove && `${o.waiting_by_kind.remove} removals`].filter(Boolean).join(" · ") || "All reviewed"} />
            <Tile href={`/${bot}/servicenow/kb`} icon={Library} label="Approved articles" value={o.live} hint={o.published ? `Version ${o.published.number} is live` : "Not published yet"} />
            <Tile href={`/${bot}/servicenow/categories`} icon={FolderTree} label="Linked pages" value={o.links.total} hint={o.links.error ? `${o.links.error} could not be read` : `${o.categories} categories`} warn={!!o.links.error} />
            <Tile href={`/${bot}/servicenow/publish`} icon={Rocket} label="Ready to publish" value={o.unpublished_total} hint={o.unpublished_total ? `+${o.unpublished.added} ~${o.unpublished.modified} −${o.unpublished.removed}` : "Nothing new"} />
          </div>

          <div className="mt-6 grid grid-cols-[1fr_300px] items-start gap-6">
            <Card>
              <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
                <h2 className="font-semibold">Recent page changes</h2>
                <Link href={`/${bot}/servicenow/changes`} className="text-[13px] text-muted hover:text-ink">All changes</Link>
              </div>
              {o.recent.length === 0 ? (
                <Empty icon={<GitCompareArrows className="size-5" />} title="No changes yet">
                  {o.links.total ? "Linked pages are checked on their schedule. When one changes, what the AI proposes shows up here." : "Add links to categories so their articles stay in line with the website."}
                </Empty>
              ) : (
                <div className="divide-y divide-line">
                  {o.recent.map((e) => (
                    <Link key={e.id} href={`/${bot}/servicenow/changes?event=${e.id}`} className="flex items-start gap-3 px-5 py-3 hover:bg-subtle">
                      <Badge tone={e.kind === "error" ? "red" : e.proposals ? "amber" : "neutral"}>{e.kind === "error" ? "Error" : e.kind === "audit" ? "Check" : "Changed"}</Badge>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-[13px] font-medium">{e.link.title || shortUrl(e.link.url)}</p>
                        <p className="truncate text-xs text-muted">{e.summary}</p>
                      </div>
                      <span className="shrink-0 text-xs text-muted">{ago(e.created_at)}</span>
                    </Link>
                  ))}
                </div>
              )}
            </Card>
            <Card className="p-5 text-[13px]">
              <p className="text-xs font-medium uppercase tracking-wider text-neutral-400">Import</p>
              <p className="mt-1">{plural(o.import?.articles ?? 0, "article")} from ServiceNow</p>
              <p className="text-xs text-muted">{dateTime(o.import?.at)} · {o.import?.by}</p>
              <div className="mt-4 space-y-1.5">
                {(["new", "changed", "removal", "approved", "rejected", "removed"] as const).map((s) => (
                  <div key={s} className="flex justify-between"><span className="capitalize text-muted">{s === "removal" ? "Removal proposed" : s}</span><b className={cn("tabular-nums", !o.articles[s] && "font-normal text-neutral-300")}>{o.articles[s]}</b></div>
                ))}
              </div>
              {!o.ai && (
                <div className="mt-4 flex gap-2 rounded-xl bg-amber-50 px-3 py-2.5 text-xs text-amber-900">
                  <AlertTriangle className="mt-px size-3.5 shrink-0" />
                  <span>AI is off: linked pages are still checked, but no edits are proposed.</span>
                </div>
              )}
              <Link href={`/${bot}/servicenow/review`}><Button variant="primary" className="mt-4 w-full">Review articles <ArrowRight className="size-4" /></Button></Link>
            </Card>
          </div>
        </>
      )}
    </Page>
  );
}

function Tile({ href, icon: Icon, label, value, hint, warn }: { href: string; icon: typeof Library; label: string; value: number; hint: string; warn?: boolean }) {
  return (
    <Link href={href} className="rounded-2xl border border-line bg-white p-4 hover:border-neutral-300">
      <div className="flex items-center gap-2 text-[13px] text-muted"><Icon className="size-4" />{label}</div>
      <p className="mt-2 text-2xl font-semibold tabular-nums tracking-tight">{value.toLocaleString()}</p>
      <p className={cn("mt-0.5 truncate text-xs", warn ? "text-red-600" : "text-muted")}>{hint}</p>
    </Link>
  );
}
