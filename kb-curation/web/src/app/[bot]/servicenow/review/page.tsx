"use client";
import { Check, CheckCheck, ExternalLink, Inbox, Link2, Pencil, RotateCcw, Search, Sparkles, X } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { api, useApi, type EntryStatus } from "@/lib/api";
import { KIND_LABEL, type SnArticle, type SnArticleDetail, type SnCategory } from "@/lib/sn";
import { useBot } from "@/components/shell";
import { DiffView } from "@/components/diff";
import { Rich } from "@/components/rich";
import { Badge, Button, Empty, ErrorNote, inputCls, Loading, Modal, Stat, StatusBadge, Tabs, useToast } from "@/components/ui";
import { ago, cn, dateTime, shortUrl } from "@/lib/utils";

type View = "queue" | "approved" | "rejected" | "removed";
type Summary = { status: Record<EntryStatus, number>; labels: [string, number][]; kinds: Record<string, number> };
const PAGE = 100;

export default function SnReviewPage() {
  return <Suspense><Inner /></Suspense>;
}

function Inner() {
  const bot = useBot();
  const router = useRouter();
  const params = useSearchParams();
  const toast = useToast();
  const articleId = Number(params.get("article")) || null;
  const [view, setView] = useState<View>((params.get("status") as View) || "queue");
  const [kind, setKind] = useState("");
  const [cat, setCat] = useState("");
  const [label, setLabel] = useState("");
  const [q, setQ] = useState("");
  const [dq, setDq] = useState("");
  const [limit, setLimit] = useState(PAGE);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [confirm, setConfirm] = useState<"approve" | "reject" | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { const t = setTimeout(() => setDq(q), 250); return () => clearTimeout(t); }, [q]);

  const qs = new URLSearchParams({ status: view, limit: String(limit) });
  if (kind) qs.set("kind", kind);
  if (cat) qs.set("category", cat);
  if (label) qs.set("label", label);
  if (dq) qs.set("q", dq);
  const key = qs.toString();
  // selections never carry over to a different list: what is ticked is always what is on screen
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => setPicked(new Set()), [view, kind, cat, label, dq]);

  const list = useApi<{ total: number; articles: SnArticle[] }>(`/api/chatbots/${bot}/servicenow/articles?${key}`);
  const sum = useApi<Summary>(`/api/chatbots/${bot}/servicenow/review-summary`);
  const cats = useApi<{ categories: SnCategory[] }>(`/api/chatbots/${bot}/servicenow/categories`);
  const rows = list.data?.articles ?? [];
  const stale = list.loading && !!list.data;
  const queue = view === "queue";

  const select = (id: number | null) => {
    const p = new URLSearchParams(params.toString());
    if (id) p.set("article", String(id)); else p.delete("article");
    router.replace(`/${bot}/servicenow/review?${p}`, { scroll: false });
  };
  const refresh = () => { list.reload(); sum.reload(); };
  const afterDecision = (id: number) => {
    const i = rows.findIndex((a) => a.id === id);
    const next = rows[i + 1] ?? rows[i - 1];
    refresh();
    if (queue) select(next && next.id !== id ? next.id : null);
  };
  const bulk = async (action: "approve" | "reject") => {
    setBusy(true);
    try {
      const r = await api<{ done: number; skipped: { reason: string }[] }>(`/api/chatbots/${bot}/servicenow/articles/bulk`, { body: { ids: [...picked], action } });
      toast(`${action === "approve" ? "Approved" : "Rejected"} ${r.done}` + (r.skipped.length ? ` · ${r.skipped.length} skipped (${r.skipped[0].reason})` : ""), r.skipped.length > 0);
      setPicked(new Set());
      setConfirm(null);
      refresh();
    } catch (e) { toast((e as Error).message, true); } finally { setBusy(false); }
  };
  const s = sum.data?.status;
  const allPicked = rows.length > 0 && rows.every((a) => picked.has(a.id));

  return (
    <div className="flex h-full">
      <section className="flex w-[440px] shrink-0 flex-col border-r border-line">
        <div className="space-y-2.5 border-b border-line px-4 pb-3 pt-5">
          <h1 className="text-lg font-semibold tracking-tight">ServiceNow review</h1>
          <Tabs value={view} onChange={(v) => { setView(v); setLimit(PAGE); }} items={[
            { value: "queue", label: "Waiting", count: s ? s.new + s.changed + s.removal : undefined },
            { value: "approved", label: "Approved", count: s?.approved }, { value: "rejected", label: "Rejected", count: s?.rejected },
            { value: "removed", label: "Removed", count: s?.removed },
          ]} />
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-neutral-400" />
            <input className={cn(inputCls, "pl-9")} placeholder="Search title, text or KB number" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <div className="grid grid-cols-3 gap-2">
            <select className="h-8 min-w-0 rounded-lg border border-line bg-white px-2 text-xs" value={kind} onChange={(e) => { setKind(e.target.value); setLimit(PAGE); }}>
              <option value="">Any source</option>
              {Object.entries(KIND_LABEL).map(([k, v]) => <option key={k} value={k}>{v.label}{sum.data?.kinds[k] ? ` (${sum.data.kinds[k]})` : ""}</option>)}
            </select>
            <select className="h-8 min-w-0 rounded-lg border border-line bg-white px-2 text-xs" value={cat} onChange={(e) => { setCat(e.target.value); setLimit(PAGE); }}>
              <option value="">All categories</option>
              <option value="0">Uncategorized</option>
              {cats.data?.categories.filter((c) => c.total > 0 || c.links.length > 0).map((c) => <option key={c.id} value={c.id}>{"· ".repeat(c.depth)}{c.name} ({c.total})</option>)}
            </select>
            <select className="h-8 min-w-0 rounded-lg border border-line bg-white px-2 text-xs" value={label} onChange={(e) => { setLabel(e.target.value); setLimit(PAGE); }}>
              <option value="">Any label</option>
              {sum.data?.labels.map(([l, n]) => <option key={l} value={l}>{l} ({n})</option>)}
            </select>
          </div>
        </div>

        {queue && rows.length > 0 && (
          <div className="flex items-center gap-2 border-b border-line bg-subtle/60 px-4 py-2">
            <input type="checkbox" checked={allPicked} onChange={() => setPicked(allPicked ? new Set() : new Set(rows.map((a) => a.id)))} aria-label="Select all shown" />
            <span className="flex-1 text-xs text-muted">{picked.size ? `${picked.size} selected` : `${list.data?.total ?? 0} articles`}</span>
            {picked.size > 0 && <>
              <Button size="sm" onClick={() => setConfirm("reject")}><X className="size-3.5" /> Reject</Button>
              <Button size="sm" variant="primary" onClick={() => setConfirm("approve")}><CheckCheck className="size-3.5" /> Approve</Button>
            </>}
          </div>
        )}

        <div className={cn("scroll-thin flex-1 overflow-y-auto", stale && "opacity-60")}>
          {list.error && <div className="p-4"><ErrorNote>{list.error}</ErrorNote></div>}
          {!list.data ? (!list.error && <Loading />) : rows.length === 0 ? (
            <Empty icon={<Inbox className="size-5" />} title={queue ? "Nothing waiting" : "Nothing here"}>{queue ? "Imported articles and AI proposals show up here for review." : "No articles match these filters."}</Empty>
          ) : (
            <>
              {rows.map((a) => (
                <div key={a.id} onClick={() => select(a.id)} className={cn("flex cursor-pointer gap-3 border-b border-line px-4 py-3", a.id === articleId ? "bg-neutral-100" : "hover:bg-subtle")}>
                  {queue && <input type="checkbox" className="mt-1" checked={picked.has(a.id)} onClick={(e) => e.stopPropagation()} onChange={() => setPicked((p) => { const n = new Set(p); if (n.has(a.id)) n.delete(a.id); else n.add(a.id); return n; })} />}
                  <div className="min-w-0 flex-1">
                    <div className="mb-1 flex items-center gap-1.5">
                      {a.kind && queue && <Badge tone={KIND_LABEL[a.kind].tone}>{KIND_LABEL[a.kind].label}</Badge>}
                      {!queue && <StatusBadge status={a.status} />}
                      {a.number && <span className="font-mono text-[11px] text-muted">{a.number}</span>}
                    </div>
                    <p className="line-clamp-2 text-[13px] font-medium">{a.title}</p>
                    <p className="truncate text-xs text-muted">{a.category ?? "Uncategorized"}</p>
                  </div>
                </div>
              ))}
              {(list.data.total ?? 0) > rows.length && (
                <button onClick={() => setLimit((l) => l + PAGE)} className="w-full py-3 text-[13px] font-medium text-neutral-600 hover:bg-subtle">Show more ({list.data.total - rows.length} remaining)</button>
              )}
            </>
          )}
        </div>
      </section>

      <section className="min-w-0 flex-1 overflow-y-auto">
        {articleId ? <Detail key={articleId} id={articleId} bot={bot} cats={cats.data?.categories ?? []} onDecided={afterDecision} onChanged={refresh} /> : (
          <Empty icon={<Inbox className="size-5" />} title="Pick an article">Choose an article on the left to read it, see what changed and decide.</Empty>
        )}
      </section>

      {confirm && (
        <Modal title={`${confirm === "approve" ? "Approve" : "Reject"} ${picked.size} articles?`} onClose={() => setConfirm(null)} footer={<><Button onClick={() => setConfirm(null)}>Cancel</Button><Button variant={confirm === "approve" ? "primary" : "danger"} busy={busy} onClick={() => bulk(confirm)}>{confirm === "approve" ? "Approve" : "Reject"} {picked.size}</Button></>}>
          <p className="text-sm text-muted">{confirm === "approve" ? "Each selected proposal becomes the approved text and will go out with the next published version." : "Each selected proposal is set aside. Approved text stays as it was."} Only the {picked.size} ticked articles in the list are affected.</p>
        </Modal>
      )}
    </div>
  );
}

function Detail({ id, bot, cats, onDecided, onChanged }: { id: number; bot: string; cats: SnCategory[]; onDecided: (id: number) => void; onChanged: () => void }) {
  const toast = useToast();
  const { data: a, error, setData, reload } = useApi<SnArticleDetail>(`/api/servicenow/articles/${id}`);
  const [tab, setTab] = useState<"text" | "diff" | "original">("text");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState({ title: "", content: "", category_id: "" });
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const catName = useMemo(() => new Map(cats.map((c) => [c.id, c.path])), [cats]);

  useEffect(() => {
    // open on the diff when there is one: that is what a reviewer decides on
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (a) setTab(a.diff?.length ? "diff" : "text");
  }, [a?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (error) return <div className="p-8"><ErrorNote>{error}</ErrorNote></div>;
  if (!a) return <Loading />;

  const act = async (action: "approve" | "reject" | "reopen") => {
    setBusy(action);
    try {
      await api(`/api/servicenow/articles/${a.id}/${action}`, { body: { note } });
      toast(action === "approve" ? "Approved" : action === "reject" ? "Rejected" : "Back in review");
      setNote("");
      onDecided(a.id);
      reload();
    } catch (e) { toast((e as Error).message, true); } finally { setBusy(null); }
  };
  const save = async () => {
    setBusy("save");
    try {
      const d = await api<SnArticleDetail>(`/api/servicenow/articles/${a.id}`, { method: "PATCH", body: { title: draft.title, content: draft.content, category_id: draft.category_id ? Number(draft.category_id) : null } });
      setData(d);
      setEditing(false);                                       // only closes once the save worked
      onChanged();
      toast("Saved");
    } catch (e) { toast((e as Error).message, true); } finally { setBusy(null); }
  };
  const waiting = a.status === "new" || a.status === "changed" || a.status === "removal";
  const k = a.kind ? KIND_LABEL[a.kind] : null;

  return (
    <div className="mx-auto max-w-[860px] px-8 py-7">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <StatusBadge status={a.status} />
        {k && waiting && <Badge tone={k.tone}>{k.label}</Badge>}
        {a.labels.map((l) => <Badge key={l} tone={l.startsWith("Expired") || l === "Internal only" ? "red" : "outline"}>{l}</Badge>)}
      </div>
      <h2 className="text-xl font-semibold tracking-tight">{a.title}</h2>
      <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-muted">
        <span>{a.category_id ? catName.get(a.category_id) ?? a.category : "Uncategorized"}</span>
        {a.number && a.kb_url && <a href={a.kb_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-mono text-xs hover:text-ink">{a.number} <ExternalLink className="size-3" /></a>}
        {a.sn_state && <span>ServiceNow: {a.sn_state.replace("_", " ")}</span>}
        {a.reviewer && <span>Last decided by {a.reviewer} {ago(a.reviewed_at)}</span>}
      </p>

      {a.reason && (
        <div className="mt-4 rounded-xl border border-violet-200 bg-violet-50/60 px-4 py-3 text-[13px] text-violet-950">
          <p className="mb-1 flex items-center gap-1.5 font-medium"><Sparkles className="size-3.5" /> Why the AI proposed this</p>
          <p>{a.reason}</p>
          {a.link && (
            <p className="mt-1.5 flex flex-wrap gap-x-3 text-xs">
              <a href={a.link.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 underline"><Link2 className="size-3" />{a.link.title || shortUrl(a.link.url)}</a>
              {a.event_id && <Link href={`/${bot}/servicenow/changes?event=${a.event_id}`} className="underline">See the page change</Link>}
            </p>
          )}
        </div>
      )}

      {editing ? (
        <div className="mt-5 space-y-3">
          <input className={inputCls} value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
          <select className={inputCls} value={draft.category_id} onChange={(e) => setDraft({ ...draft, category_id: e.target.value })}>
            <option value="">Uncategorized</option>
            {cats.map((c) => <option key={c.id} value={c.id}>{c.path}</option>)}
          </select>
          <textarea className="h-[420px] w-full rounded-[10px] border border-line p-3 font-mono text-[12.5px] leading-relaxed outline-none focus:border-neutral-400" value={draft.content} onChange={(e) => setDraft({ ...draft, content: e.target.value })} />
          <p className="text-xs text-muted">One item per line: “## ” headings, “- ” bullets, “1. ” steps, “a | b” table rows, [text](url) links. Keep image lines as they are.</p>
          <div className="flex justify-end gap-2"><Button onClick={() => setEditing(false)}>Cancel</Button><Button variant="primary" busy={busy === "save"} onClick={save}>Save</Button></div>
        </div>
      ) : (
        <>
          <div className="mt-5 flex items-center justify-between">
            <Tabs value={tab} onChange={setTab} items={[
              { value: "text", label: waiting && a.status !== "removal" ? "Proposed text" : "Text" },
              ...(a.diff?.length ? [{ value: "diff" as const, label: a.diff_base === "servicenow" ? "Changes vs ServiceNow" : "Changes vs approved" }] : []),
              ...(a.sn_content ? [{ value: "original" as const, label: "ServiceNow original" }] : []),
            ]} />
            {a.diff && tab === "diff" && <Stat added={a.added ?? 0} removed={a.removed ?? 0} />}
          </div>
          <div className="mt-3 rounded-2xl border border-line bg-white">
            {tab === "diff" && a.diff ? <DiffView lines={a.diff} className="py-2" /> : (
              <div className="px-6 py-5"><Rich content={(tab === "original" ? a.sn_content : a.status === "removal" ? a.approved?.content : a.content) || "(empty)"} /></div>
            )}
          </div>
        </>
      )}

      {!editing && (
        <div className="sticky bottom-0 mt-5 flex flex-wrap items-center gap-2 border-t border-line bg-white/95 py-4 backdrop-blur">
          {waiting ? (
            <>
              <input className={cn(inputCls, "w-auto min-w-0 flex-1")} placeholder="Note for the history (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
              {a.status !== "removal" && <Button onClick={() => { setDraft({ title: a.title, content: a.content, category_id: a.category_id ? String(a.category_id) : "" }); setEditing(true); }}><Pencil className="size-3.5" /> Edit</Button>}
              <Button busy={busy === "reject"} onClick={() => act("reject")}><X className="size-3.5" /> {a.status === "removal" ? "Keep article" : "Reject"}</Button>
              <Button variant="primary" busy={busy === "approve"} onClick={() => act("approve")}><Check className="size-3.5" /> {a.status === "removal" ? "Approve removal" : "Approve"}</Button>
            </>
          ) : a.status === "approved" ? (
            <Button onClick={() => { setDraft({ title: a.title, content: a.content, category_id: a.category_id ? String(a.category_id) : "" }); setEditing(true); }}><Pencil className="size-3.5" /> Edit approved text</Button>
          ) : (
            <Button busy={busy === "reopen"} onClick={() => act("reopen")}><RotateCcw className="size-3.5" /> Reopen</Button>
          )}
        </div>
      )}

      {a.history.length > 0 && (
        <details className="mt-6 text-[13px]">
          <summary className="cursor-pointer font-medium text-neutral-600 hover:text-ink">History ({a.history.length})</summary>
          <div className="mt-2 space-y-1.5">
            {a.history.map((h) => <p key={h.id} className="text-xs text-muted"><span className="text-neutral-700">{h.action.replace(/_/g, " ")}</span> · {h.actor} · {dateTime(h.created_at)}{typeof h.detail.reason === "string" && ` · ${h.detail.reason}`}{typeof h.detail.note === "string" && h.detail.note && ` · “${h.detail.note}”`}</p>)}
          </div>
        </details>
      )}
    </div>
  );
}
