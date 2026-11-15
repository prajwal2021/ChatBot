"use client";
import { ArrowDownUp, Ban, CircleCheck, CircleX, ExternalLink, FileX2, Plus, Search, ShieldCheck, Undo2 } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";
import { api, useApi, type Entry, type PageEvent, type PageRow } from "@/lib/api";
import { useBot } from "@/components/shell";
import { DiffView } from "@/components/diff";
import { Badge, Button, Card, Drawer, Empty, ErrorNote, inputCls, KindBadge, Label, Loading, Modal, Page, PageHeader, Stat, StatusBadge, Tabs, useToast, type Tone } from "@/components/ui";
import { ago, cn, dateTime, pathOf, plural } from "@/lib/utils";

type Filter = "active" | "sitemap" | "recent" | "excluded" | "removed" | "skipped" | "error";
type Sort = "changed" | "url" | "changes" | "entries";
const PAGE_STATUS: Record<string, { label: string; tone: Tone }> = {
  active: { label: "Tracked", tone: "green" }, removed: { label: "Removed", tone: "red" }, skipped: { label: "Failed checks", tone: "red" }, error: { label: "Broken link", tone: "amber" }, excluded: { label: "Left out", tone: "neutral" },
};

export default function PagesPage() {
  return <Suspense><Inner /></Suspense>;
}

function Inner() {
  const bot = useBot();
  const router = useRouter();
  const params = useSearchParams();
  const openId = params.get("page");
  const toast = useToast();
  const { data, error, reload } = useApi<{ last_run_id: number | null; pages: PageRow[] }>(`/api/chatbots/${bot}/pages`, 10000);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const act = async (ids: number[], action: "exclude" | "include") => {
    if (action === "exclude" && !confirm(`Stop crawling ${ids.length === 1 ? "this page" : `these ${ids.length} pages`}?\n\nContent from ${ids.length === 1 ? "it" : "them"} that is waiting for review is dropped. Content that is already approved stays in the knowledge base until you approve its removal in Review.`)) return;
    setBusy(true);
    try {
      const r = await api<{ done: number; removal_proposals: number }>(`/api/chatbots/${bot}/pages/bulk`, { body: { ids, action } });
      toast(action === "exclude" ? `${r.done} ${r.done === 1 ? "page" : "pages"} left out of crawling${r.removal_proposals ? ` · ${r.removal_proposals} approved entries need a removal decision in Review` : ""}` : `${r.done} ${r.done === 1 ? "page" : "pages"} put back. ${r.done === 1 ? "It" : "They"} will be read at the next check.`);
      setPicked(new Set());
      reload();
    } catch (e) { toast((e as Error).message, true); } finally { setBusy(false); }
  };
  const [filter, setFilter] = useState<Filter>("active");
  const [sort, setSort] = useState<Sort>("changed");
  const [q, setQ] = useState("");
  const [limit, setLimit] = useState(150);

  const counts = useMemo(() => {
    const c = { active: 0, sitemap: 0, recent: 0, excluded: 0, removed: 0, skipped: 0, error: 0 };
    data?.pages.forEach((p) => { c[p.status]++; if (p.changed_in_last_run) c.recent++; if (p.status === "active" && p.found_via === "sitemap") c.sitemap++; });
    return c;
  }, [data]);

  const rows = useMemo(() => {
    const ql = q.toLowerCase().trim();
    const list = (data?.pages ?? []).filter((p) => (filter === "recent" ? p.changed_in_last_run : filter === "sitemap" ? p.status === "active" && p.found_via === "sitemap" : p.status === filter) && (!ql || p.url.toLowerCase().includes(ql) || p.title.toLowerCase().includes(ql)));
    const t = (s: string | null) => (s ? new Date(s).getTime() : 0);
    return list.sort((a, b) => sort === "url" ? a.url.localeCompare(b.url) : sort === "changes" ? b.change_count - a.change_count : sort === "entries" ? b.entries - a.entries : t(b.last_changed_at) - t(a.last_changed_at) || a.url.localeCompare(b.url));
  }, [data, filter, sort, q]);

  const open = (id: number | null) => router.replace(id ? `/${bot}/pages?page=${id}` : `/${bot}/pages`, { scroll: false });
  const isFile = filter === "skipped" || filter === "error";
  const canPick = true;
  const shownRows = rows.slice(0, limit);
  const allPicked = shownRows.length > 0 && shownRows.every((p) => picked.has(p.id));
  const toggle = (id: number) => setPicked((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });

  return (
    <Page>
      <PageHeader title="Pages" description="Every page being crawled for this chatbot. New pages that appear on the websites are added automatically; you decide which ones stay by leaving pages out, putting them back, or adding a page by hand." actions={<Button variant="primary" onClick={() => setAdding(true)}><Plus className="size-4" /> Add page</Button>} />
      {error && <ErrorNote>{error}</ErrorNote>}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Tabs value={filter} onChange={(v) => { setFilter(v); setLimit(150); setPicked(new Set()); }} items={[
          { value: "active", label: "Crawled", count: counts.active },
          { value: "sitemap", label: "Not linked", count: counts.sitemap },
          { value: "recent", label: "New or changed in last crawl", count: counts.recent },
          { value: "excluded", label: "Left out", count: counts.excluded },
          { value: "removed", label: "Removed", count: counts.removed },
          { value: "skipped", label: "Failed verification", count: counts.skipped },
          { value: "error", label: "Broken", count: counts.error },
        ]} />
      </div>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        {picked.size > 0 ? (
          <div className="flex h-9 items-center gap-2 rounded-[10px] bg-ink pl-3.5 pr-1.5 text-[13px] text-white">
            <span className="font-medium">{picked.size} selected</span>
            {filter === "excluded" || filter === "removed" || filter === "error" || filter === "skipped"
              ? <Button size="sm" busy={busy} onClick={() => act([...picked], "include")} className="h-7 border-0"><Undo2 className="size-3.5" /> Put back into crawling</Button>
              : <Button size="sm" busy={busy} onClick={() => act([...picked], "exclude")} className="h-7 border-0"><Ban className="size-3.5" /> Leave out of crawling</Button>}
            <button onClick={() => setPicked(new Set())} className="px-2 text-neutral-300 hover:text-white">Clear</button>
          </div>
        ) : <span className="text-[13px] text-muted">{rows.length.toLocaleString()} {rows.length === 1 ? "page" : "pages"}{canPick && rows.length > 0 ? " · tick pages to leave them out or put them back" : ""}</span>}
        <div className="relative ml-auto w-64">
          <Search className="absolute left-3 top-2.5 size-4 text-neutral-400" />
          <input className={cn(inputCls, "pl-9")} placeholder="Search title or address" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <label className="flex h-9 items-center gap-1.5 rounded-[10px] border border-line px-2.5 text-[13px] text-neutral-600">
          <ArrowDownUp className="size-3.5" />
          <select className="bg-transparent outline-none" value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
            <option value="changed">Recently changed</option><option value="changes">Changes most often</option><option value="entries">Most entries</option><option value="url">Address A–Z</option>
          </select>
        </label>
      </div>
      {filter === "skipped" && <p className="mb-4 flex gap-2.5 rounded-xl border border-line bg-subtle px-4 py-2.5 text-[13px] text-neutral-600"><ShieldCheck className="mt-0.5 size-4 shrink-0" /><span>Every page is verified automatically on each crawl: it must load, not be an error page, contain real text, not be a copy of another page, and be judged useful for this chatbot. These pages failed, so nothing from them reaches Review. A page is re-verified whenever its content changes. If one was rejected by mistake, tick it and choose <b>Put back into crawling</b>; it is then kept regardless of the checks.</span></p>}
      {filter === "sitemap" && <p className="mb-4 rounded-xl border border-line bg-subtle px-4 py-2.5 text-[13px] text-neutral-600">These pages are live but nothing on the website links to them; they were found only in the site&apos;s sitemap. Some are real (for example program pages reached through a search box), others are forgotten leftovers. Their entries carry the label <b>Not linked on site</b> in Review. To drop a whole group, add its path under Sources → Parts of the site to leave out.</p>}

      <Card className="overflow-hidden">
        {!data ? <Loading /> : rows.length === 0 ? (
          <Empty icon={<FileX2 className="size-5" />} title={data.pages.length ? "Nothing here" : "No pages collected yet"}>{data.pages.length ? "No pages match this filter." : "Run a crawl from Sources to collect the website's pages."}</Empty>
        ) : (
          <table className="w-full table-fixed text-left text-[13px]">
            <thead className="border-b border-line bg-subtle text-xs text-muted">
              <tr>
                {canPick && <th className="w-10 pl-5"><input type="checkbox" aria-label="Select all shown" className="size-3.5 accent-black" checked={allPicked} onChange={() => setPicked(allPicked ? new Set() : new Set(shownRows.map((p) => p.id)))} /></th>}
                <th className={cn("py-2.5 pr-3 font-medium", canPick ? "pl-2" : "pl-5")}>Page</th>
                {isFile ? <th className="w-[45%] px-3 font-medium">{filter === "skipped" ? "Why it failed" : "Problem"}</th> : <>
                  <th className="w-[125px] px-3 font-medium">Status</th>
                  <th className="w-[150px] px-3 font-medium">Entries</th>
                  <th className="w-[150px] px-3 font-medium">Last changed</th>
                  <th className="w-[90px] px-3 font-medium">Updates</th>
                </>}
                <th className="w-[120px] px-3 pr-5 font-medium">Last checked</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {shownRows.map((p) => (
                <tr key={p.id} onClick={() => open(p.id)} className={cn("cursor-pointer hover:bg-subtle", String(p.id) === openId && "bg-subtle", picked.has(p.id) && "bg-blue-50/50")}>
                  {canPick && <td className="pl-5" onClick={(e) => e.stopPropagation()}><input type="checkbox" aria-label={`Select ${p.title}`} className="size-3.5 accent-black" checked={picked.has(p.id)} onChange={() => toggle(p.id)} /></td>}
                  <td className={cn("py-2.5 pr-3", canPick ? "pl-2" : "pl-5")}>
                    <p className="flex items-center gap-2 font-medium"><span className="truncate">{p.title || decodeURIComponent(p.url.replace(/\/$/, "").split("/").pop() ?? p.url)}</span>
                      {p.kept_by_person && p.status === "active" && <Badge tone="outline" className="h-[18px] shrink-0 px-1.5 text-[10px]">Kept by a reviewer</Badge>}
                      {p.new_in_last_run && <Badge tone="blue" className="h-[18px] shrink-0 px-1.5 text-[10px]">New</Badge>}
                      {p.found_via === "manual" && <Badge tone="outline" className="h-[18px] shrink-0 px-1.5 text-[10px]">Added by hand</Badge>}
                    </p>
                    <p className="truncate font-mono text-[11px] text-muted">{pathOf(p.url)}</p>
                  </td>
                  {isFile ? <td className="px-3 text-neutral-600"><span className="line-clamp-2">{(p.reason ?? "").replace("Did not pass verification: ", "")}</span></td> : <>
                    <td className="px-3">{p.status === "active" && p.found_via === "sitemap" ? <Badge tone="violet" dot>Sitemap only</Badge> : p.status === "active" ? <Badge tone="green"><CircleCheck className="size-3" />Verified</Badge> : <Badge tone={PAGE_STATUS[p.status].tone} dot>{PAGE_STATUS[p.status].label}</Badge>}</td>
                    <td className="whitespace-nowrap px-3 tabular-nums">{p.entries}{p.waiting > 0 && <span className="ml-1.5 rounded-full bg-amber-50 px-1.5 py-0.5 text-[11px] font-medium text-amber-700">{p.waiting} to review</span>}</td>
                    <td className="px-3">
                      <span className="flex items-center gap-1.5">
                        {p.changed_in_last_run && <span className={cn("size-1.5 shrink-0 rounded-full", p.last_change_kind === "new" ? "bg-blue-500" : p.last_change_kind === "removed" ? "bg-red-500" : "bg-amber-500")} />}
                        <span title={dateTime(p.last_changed_at)}>{ago(p.last_changed_at)}</span>
                      </span>
                    </td>
                    <td className="px-3 tabular-nums text-muted">{p.change_count || "—"}</td>
                  </>}
                  <td className="px-3 pr-5 text-muted" title={dateTime(p.last_crawled_at)}>{p.last_crawled_at ? ago(p.last_crawled_at) : "not opened"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {rows.length > limit && <button onClick={() => setLimit((l) => l + 300)} className="w-full border-t border-line py-3 text-[13px] font-medium text-neutral-600 hover:bg-subtle">Show more ({(rows.length - limit).toLocaleString()} remaining)</button>}
      </Card>
      {openId && <PageDrawer id={openId} bot={bot} onClose={() => open(null)} onAct={(id, a) => act([id], a)} />}
      {adding && <AddPage bot={bot} onClose={() => setAdding(false)} onDone={() => { setAdding(false); reload(); toast("Page added. It will be read at the next check (Sources → Check for updates)."); }} />}
    </Page>
  );
}

type Detail = PageRow & { events: PageEvent[]; entries: Entry[]; checks: { name: string; ok: boolean; note: string }[] };

function AddPage({ bot, onClose, onDone }: { bot: string; onClose: () => void; onDone: () => void }) {
  const [url, setUrl] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try { await api(`/api/chatbots/${bot}/pages`, { body: { url } }); onDone(); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <Modal title="Add a page" onClose={onClose} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" busy={busy} disabled={!url.trim()} onClick={save}>Add page</Button></>}>
      <p className="mb-4 text-sm text-muted">Use this for a page the crawl did not find on its own, or one on another website that this chatbot should also know. It is checked for changes like every other page.</p>
      <Label>Page address</Label>
      <input autoFocus className={inputCls} placeholder="https://www.depts.ttu.edu/…" value={url} onChange={(e) => setUrl(e.target.value)} onKeyDown={(e) => e.key === "Enter" && save()} />
      {err && <p className="mt-3 text-sm text-red-600">{err}</p>}
    </Modal>
  );
}

function PageDrawer({ id, bot, onClose, onAct }: { id: string; bot: string; onClose: () => void; onAct: (id: number, action: "exclude" | "include") => Promise<void> }) {
  const { data, reload } = useApi<Detail>(`/api/pages/${id}`);
  const [tab, setTab] = useState<"checks" | "history" | "entries">("checks");
  return (
    <Drawer onClose={onClose} title={data?.title ?? "Page"} subtitle={data && <a href={data.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-mono text-xs hover:underline">{data.url} <ExternalLink className="size-3" /></a>}>
      {!data ? <Loading /> : (
        <>
          <div className="grid grid-cols-4 gap-3 text-[13px]">
            <Info label="Status"><Badge tone={PAGE_STATUS[data.status].tone} dot>{PAGE_STATUS[data.status].label}</Badge></Info>
            <Info label="First seen">{dateTime(data.first_seen_at)}</Info>
            <Info label="Last changed">{ago(data.last_changed_at)}</Info>
            <Info label="Last checked">{ago(data.last_crawled_at)}</Info>
          </div>
          {data.reason && <p className="mt-3 rounded-lg bg-subtle px-3 py-2 text-[13px] text-neutral-600">{data.reason}</p>}
          <div className="mt-3">
            {data.status === "active" ? <Button size="sm" onClick={() => onAct(data.id, "exclude").then(reload)}><Ban className="size-3.5" /> Leave this page out of crawling</Button>
              : <Button size="sm" onClick={() => onAct(data.id, "include").then(reload)}><Undo2 className="size-3.5" /> {data.status === "skipped" ? "Keep this page anyway (overrule the checks)" : "Put this page back into crawling"}</Button>}
          </div>
          <Tabs className="mt-5" value={tab} onChange={setTab} items={[{ value: "checks", label: "Verification" }, { value: "history", label: "Change history", count: data.events.length }, { value: "entries", label: "Knowledge entries", count: data.entries.length }]} />
          {tab === "checks" ? (
            <div className="mt-4 divide-y divide-line rounded-xl border border-line">
              {data.checks.length === 0 && <p className="px-4 py-6 text-sm text-muted">{data.status === "excluded" ? "This page was left out by a person, so it is not verified." : "Not verified yet. It is checked at the next crawl."}</p>}
              {data.checks.map((c) => (
                <div key={c.name} className="flex gap-3 px-4 py-3">
                  {c.ok ? <CircleCheck className="mt-0.5 size-4 shrink-0 text-emerald-600" /> : <CircleX className="mt-0.5 size-4 shrink-0 text-red-600" />}
                  <div><p className="text-[13px] font-medium">{c.name}</p><p className={cn("text-xs", c.ok ? "text-muted" : "text-red-700")}>{c.note}</p></div>
                </div>
              ))}
              {data.kept_by_person && <p className="bg-subtle px-4 py-2.5 text-xs text-neutral-600">A reviewer chose to keep this page, so it stays even if a check fails.</p>}
            </div>
          ) : tab === "history" ? (
            <div className="mt-4 space-y-4">
              {data.events.length === 0 && <p className="text-sm text-muted">No changes recorded.</p>}
              {data.events.map((ev) => (
                <div key={ev.id} className="relative pl-6">
                  <span className="absolute left-[7px] top-6 h-[calc(100%-4px)] w-px bg-line" />
                  <span className={cn("absolute left-0 top-1.5 size-[15px] rounded-full border-[3px] border-white ring-1 ring-line", ev.kind === "new" ? "bg-blue-500" : ev.kind === "removed" ? "bg-red-500" : ev.kind === "restored" ? "bg-emerald-500" : "bg-amber-500")} />
                  <div className="flex items-center gap-2 text-[13px]">
                    <KindBadge kind={ev.kind} /><span className="font-medium">{dateTime(ev.created_at)}</span><Stat added={ev.added} removed={ev.removed} />
                  </div>
                  {ev.diff ? <div className="mt-2 overflow-hidden rounded-xl border border-line"><DiffView lines={ev.diff} max={ev.kind === "new" ? 40 : 300} /></div>
                    : <p className="mt-1 text-xs text-muted">{plural(ev.added, "line")} of content when the page was first read.</p>}
                </div>
              ))}
            </div>
          ) : (
            <div className="mt-4 divide-y divide-line rounded-xl border border-line">
              {data.entries.length === 0 && <p className="px-4 py-6 text-sm text-muted">No knowledge entries came from this page.</p>}
              {data.entries.map((e) => (
                <Link key={e.id} href={`/${bot}/review?entry=${e.id}`} className="block px-4 py-3 hover:bg-subtle">
                  <div className="flex items-center justify-between gap-3"><p className="truncate text-[13px] font-medium">{e.title}</p><StatusBadge status={e.status} /></div>
                  <p className="mt-0.5 line-clamp-2 text-xs text-muted">{e.excerpt}</p>
                </Link>
              ))}
            </div>
          )}
        </>
      )}
    </Drawer>
  );
}

const Info = ({ label, children }: { label: string; children: React.ReactNode }) => <div className="rounded-xl border border-line px-3 py-2"><p className="text-xs text-muted">{label}</p><div className="mt-0.5 font-medium">{children}</div></div>;
