"use client";
import { Check, CheckCheck, Copy, ExternalLink, Inbox, MessageSquare, Pencil, Plus, RotateCcw, Search, Tag, X } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { api, useApi, type Category, type Entry, type EntryDetail, type EntryStatus } from "@/lib/api";
import { useBot } from "@/components/shell";
import { DiffView } from "@/components/diff";
import { Rich } from "@/components/rich";
import { Badge, Button, CategoryChip, Empty, ErrorNote, inputCls, Loading, Stat, StatusBadge, Tabs, useToast } from "@/components/ui";
import { ago, cn, dateTime, DOT, pathOf } from "@/lib/utils";

type Cats = { categories: Category[]; uncategorized: { total: number; waiting: number } };
type Summary = { status: Record<EntryStatus, number>; labels: [string, number][]; scope: { enabled: boolean; in: number; out: number; unchecked: number; clear: number } };
type View = "queue" | "new" | "changed" | "removal" | "approved" | "rejected";

export default function ReviewPage() {
  return <Suspense><Inner /></Suspense>;
}

function Inner() {
  const bot = useBot();
  const router = useRouter();
  const params = useSearchParams();
  const toast = useToast();
  const entryId = params.get("entry");
  const [view, setView] = useState<View>((params.get("status") as View) || "queue");
  const [cat, setCat] = useState<string>("");
  const [scopeSel, setScopeSel] = useState<string | null>(params.get("scope"));
  const topic = params.get("topic") ?? "";
  const [label, setLabel] = useState("");
  const [q, setQ] = useState("");
  const [dq, setDq] = useState("");
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  useEffect(() => { const t = setTimeout(() => setDq(q), 250); return () => clearTimeout(t); }, [q]);

  const sum = useApi<Summary>(`/api/chatbots/${bot}/review-summary`);
  const scopeOn = !!sum.data?.scope.enabled;
  const scopeView = scopeSel ?? (scopeOn ? "in" : "");           // by default show only what Ryan's KB covers
  const qs = new URLSearchParams({ status: view });
  if (scopeOn && scopeView) qs.set("scope", scopeView);
  if (topic) qs.set("topic", topic);
  if (cat) qs.set("category", cat);
  if (label) qs.set("label", label);
  if (dq) qs.set("q", dq);
  const list = useApi<{ total: number; entries: Entry[] }>(`/api/chatbots/${bot}/entries?${qs}`);
  const cats = useApi<Cats>(`/api/chatbots/${bot}/categories`);
  const entries = list.data?.entries ?? [];
  const queueView = view !== "approved" && view !== "rejected";
  const catMap = useMemo(() => new Map(cats.data?.categories.map((c) => [c.id, c])), [cats.data]);

  const select = (id: number | null) => {
    const p = new URLSearchParams(params.toString());
    if (id) p.set("entry", String(id)); else p.delete("entry");
    router.replace(`/${bot}/review?${p}`, { scroll: false });
  };
  const refresh = () => { list.reload(); cats.reload(); sum.reload(); };
  const afterDecision = (id: number) => {
    const i = entries.findIndex((e) => e.id === id);
    const next = entries[i + 1] ?? entries[i - 1];
    select(queueView && next ? next.id : id);
    refresh();
  };
  const bulk = async (action: "approve" | "reject") => {
    if (action === "reject" && !confirm(`Reject ${picked.size} entries?`)) return;
    setBusy(true);
    try {
      const r = await api<{ done: number; skipped: { id: number; reason: string }[] }>(`/api/chatbots/${bot}/entries/bulk`, { body: { ids: [...picked], action } });
      toast(`${r.done} ${action === "approve" ? "approved" : "rejected"}${r.skipped.length ? ` · ${r.skipped.length} skipped (${r.skipped[0].reason})` : ""}`, r.done === 0);
      setPicked(new Set());
      select(null);
      refresh();
    } catch (e) { toast((e as Error).message, true); } finally { setBusy(false); }
  };
  const rejectOutside = async () => {
    const n = sum.data?.scope.clear ?? 0;
    if (!confirm(`Reject ${n.toLocaleString()} new entries that are clearly unrelated to Ryan's KB?\n\nThey are not deleted: they stay under Rejected, and you can reopen any of them. Borderline entries, and ones that changed or were removed on the website, are left for you to decide.`)) return;
    setBusy(true);
    try {
      const r = await api<{ done: number }>(`/api/chatbots/${bot}/entries/reject-outside`, { body: {} });
      toast(`${r.done.toLocaleString()} entries rejected`);
      select(null);
      refresh();
    } catch (e) { toast((e as Error).message, true); } finally { setBusy(false); }
  };
  const setTopic = (id: string) => {
    const p = new URLSearchParams(params.toString());
    if (id) p.set("topic", id); else p.delete("topic");
    p.delete("entry");
    router.replace(`/${bot}/review?${p}`, { scroll: false });
  };
  const st = sum.data?.status;
  const waiting = st ? st.new + st.changed + st.removal : 0;
  const allPicked = entries.length > 0 && entries.every((e) => picked.has(e.id));

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-4 border-b border-line px-6 py-3.5">
        <div className="min-w-0">
          <h1 className="text-lg font-semibold tracking-tight">Review</h1>
          <p className="hidden truncate text-[13px] text-muted 2xl:block">Check what the crawl found, fix it if needed, then approve. Only approved content can be published.</p>
        </div>
        <Tabs className="ml-auto shrink-0" value={view} onChange={(v) => { setView(v); setPicked(new Set()); }} items={[
          { value: "queue", label: "To review", count: waiting },
          { value: "new", label: "New", count: st?.new ?? 0 },
          { value: "changed", label: "Changed", count: st?.changed ?? 0 },
          { value: "removal", label: "Removed", count: st?.removal ?? 0 },
          { value: "approved", label: "Approved", count: st?.approved ?? 0 },
          { value: "rejected", label: "Rejected", count: st?.rejected ?? 0 },
        ]} />
      </div>

      <div className="flex min-h-0 flex-1">
        {/* categories */}
        <div className="scroll-thin w-[232px] shrink-0 overflow-y-auto border-r border-line p-3">
          {scopeOn && queueView && sum.data && (
            <>
              <p className="px-2 pb-1.5 text-[11px] font-medium uppercase tracking-wider text-neutral-400">Ryan&apos;s KB</p>
              <CatRow active={scopeView === "in"} onClick={() => { setScopeSel("in"); setTopic(""); }} name="Inside Ryan's KB" count={sum.data.scope.in} dot="bg-emerald-500" title="Entries that match a topic in the SME's own knowledge base" />
              <CatRow active={scopeView === "out"} onClick={() => { setScopeSel("out"); setTopic(""); }} name="Outside Ryan's KB" count={sum.data.scope.out} dot="bg-amber-500" title="Entries that match nothing the SME maintains" />
              <CatRow active={scopeView === ""} onClick={() => { setScopeSel(""); setTopic(""); }} name="Everything" count={waiting} dot="bg-neutral-300" />
              <div className="h-4" />
            </>
          )}
          <p className="px-2 pb-1.5 text-[11px] font-medium uppercase tracking-wider text-neutral-400">Categories</p>
          <CatRow active={cat === ""} onClick={() => setCat("")} name="All categories" count={queueView ? waiting : st?.[view as EntryStatus] ?? 0} />
          {cats.data?.categories.map((c) => (
            <CatRow key={c.id} active={cat === String(c.id)} onClick={() => setCat(String(c.id))} name={c.name} color={c.color} count={queueView ? c.waiting : c.total - c.waiting} title={c.description} />
          ))}
          {!!cats.data?.uncategorized.total && <CatRow active={cat === "none"} onClick={() => setCat("none")} name="Uncategorized" count={queueView ? cats.data.uncategorized.waiting : cats.data.uncategorized.total - cats.data.uncategorized.waiting} dashed />}
          {!!sum.data?.labels.length && (
            <>
              <p className="px-2 pb-1.5 pt-5 text-[11px] font-medium uppercase tracking-wider text-neutral-400">Labels</p>
              <div className="flex flex-wrap gap-1.5 px-1">
                {sum.data.labels.map(([l, n]) => (
                  <button key={l} onClick={() => setLabel(label === l ? "" : l)} className={cn("rounded-full border px-2 py-0.5 text-xs", label === l ? "border-ink bg-ink text-white" : "border-line text-neutral-600 hover:bg-subtle")}>{l} <span className="opacity-60">{n}</span></button>
                ))}
              </div>
            </>
          )}
        </div>

        {/* list */}
        <div className="flex w-[380px] shrink-0 flex-col border-r border-line">
          <div className="space-y-2 border-b border-line p-3">
            <div className="relative">
              <Search className="absolute left-3 top-2.5 size-4 text-neutral-400" />
              <input className={cn(inputCls, "pl-9")} placeholder="Search entries" value={q} onChange={(e) => setQ(e.target.value)} />
            </div>
            {topic && (
              <div className="flex items-center gap-2 rounded-lg bg-neutral-100 px-2.5 py-1.5 text-xs">
                <span className="min-w-0 flex-1 truncate">Ryan&apos;s KB topic: <b>{entries[0]?.scope?.topic ?? `#${topic}`}</b></span>
                <button aria-label="Clear topic filter" onClick={() => setTopic("")} className="rounded p-0.5 text-neutral-500 hover:text-ink"><X className="size-3.5" /></button>
              </div>
            )}
            {scopeOn && scopeView === "out" && queueView && (sum.data?.scope.out ?? 0) > 0 && !topic && (
              <div className="rounded-lg border border-amber-200 bg-amber-50 px-2.5 py-2 text-xs text-amber-900">
                These do not match Ryan&apos;s KB. {sum.data?.scope.clear.toLocaleString()} are clearly unrelated; the rest are borderline, so read those before deciding.
                {!!sum.data?.scope.clear && <Button size="sm" busy={busy} onClick={rejectOutside} className="mt-1.5 h-7 w-full">Reject the {sum.data?.scope.clear.toLocaleString()} clearly unrelated</Button>}
              </div>
            )}
            <div className="flex h-7 items-center gap-2 text-xs text-muted">
              {queueView && <input type="checkbox" aria-label="Select all" className="size-3.5 accent-black" checked={allPicked} onChange={() => setPicked(allPicked ? new Set() : new Set(entries.map((e) => e.id)))} />}
              {picked.size ? (
                <>
                  <span className="font-medium text-ink">{picked.size} selected</span>
                  <span className="ml-auto flex gap-1.5">
                    <Button size="sm" variant="primary" busy={busy} onClick={() => bulk("approve")} className="h-7"><CheckCheck className="size-3.5" /> Approve</Button>
                    <Button size="sm" busy={busy} onClick={() => bulk("reject")} className="h-7">Reject</Button>
                  </span>
                </>
              ) : (
                <span>{list.data ? `${list.data.total.toLocaleString()} ${list.data.total === 1 ? "entry" : "entries"}${list.data.total > entries.length ? ` · showing first ${entries.length}` : ""}` : ""}</span>
              )}
            </div>
          </div>
          <div className="scroll-thin flex-1 overflow-y-auto">
            {list.error && <div className="p-3"><ErrorNote>{list.error}</ErrorNote></div>}
            {list.loading && !list.data ? <Loading /> : entries.length === 0 ? (
              <Empty icon={<Inbox className="size-5" />} title={queueView ? "Nothing to review" : "Nothing here"}>{queueView ? "You are all caught up. New items appear after the next crawl finds changes." : "No entries match."}</Empty>
            ) : entries.map((e) => (
              <div key={e.id} onClick={() => select(e.id)} className={cn("flex cursor-pointer gap-2.5 border-b border-line px-3 py-3", String(e.id) === entryId ? "bg-neutral-100" : "hover:bg-subtle")}>
                {queueView && <input type="checkbox" aria-label="Select" className="mt-0.5 size-3.5 shrink-0 accent-black" checked={picked.has(e.id)} onClick={(ev) => ev.stopPropagation()} onChange={() => setPicked((s) => { const n = new Set(s); if (n.has(e.id)) n.delete(e.id); else n.add(e.id); return n; })} />}
                <div className="min-w-0 flex-1">
                  <div className="flex items-start justify-between gap-2">
                    <p className="line-clamp-2 text-[13px] font-medium leading-snug">{e.title}</p>
                    <span className={cn("mt-1 size-2 shrink-0 rounded-full", e.status === "new" ? "bg-blue-500" : e.status === "changed" ? "bg-amber-500" : e.status === "removal" ? "bg-red-500" : e.status === "approved" ? "bg-emerald-500" : "bg-neutral-300")} title={e.status} />
                  </div>
                  <p className="mt-0.5 line-clamp-2 text-xs text-muted">{e.excerpt}</p>
                  <div className="mt-1.5 flex items-center gap-2 overflow-hidden">
                    <CategoryChip cat={e.category_id ? catMap.get(e.category_id) : null} muted />
                    {e.secondary_ids.length > 0 && <span className="text-[11px] text-neutral-400">+{e.secondary_ids.length}</span>}
                    {e.duplicate_of && <Badge tone="violet" className="h-[18px] px-1.5 text-[10px]">Duplicate</Badge>}
                    {e.scope && !e.scope.in && <Badge tone="amber" className="h-[18px] px-1.5 text-[10px]" >Outside</Badge>}
                    <span className="ml-auto shrink-0 text-[11px] text-neutral-400">{ago(e.detected_at)}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* detail */}
        <div className="scroll-thin min-w-0 flex-1 overflow-y-auto bg-[#fcfcfc]">
          {entryId ? <Detail key={entryId} id={entryId} cats={cats.data?.categories ?? []} onDecided={afterDecision} onChanged={refresh} onOpen={select} /> : (
            <Empty icon={<MessageSquare className="size-5" />} title="Select an entry">Choose an entry on the left to read it, edit it, comment, and approve or reject it.</Empty>
          )}
        </div>
      </div>
    </div>
  );
}

function CatRow({ name, count, color, active, onClick, dashed, title, dot }: { name: string; count: number; color?: string; active: boolean; onClick: () => void; dashed?: boolean; title?: string; dot?: string }) {
  return (
    <button onClick={onClick} title={title} className={cn("mb-0.5 flex h-8 w-full items-center gap-2 rounded-lg px-2 text-left text-[13px]", active ? "bg-neutral-100 font-medium text-ink" : "text-neutral-600 hover:bg-subtle")}>
      <span className={cn("size-2 shrink-0 rounded-full", dot ?? (color ? DOT[color] : dashed ? "border border-dashed border-neutral-400" : "bg-ink"))} />
      <span className="flex-1 truncate">{name}</span>
      <span className={cn("text-xs tabular-nums", count ? "text-neutral-500" : "text-neutral-300")}>{count}</span>
    </button>
  );
}

const ACTIONS: Record<string, string> = {
  detected: "Found on the website", change_detected: "Change detected on the website", removal_detected: "No longer on the website", edited: "Edited",
  approved: "Approved", change_approved: "Change approved", removal_approved: "Removal approved", rejected: "Rejected", change_rejected: "Change rejected (kept the approved text)",
  removal_rejected: "Removal rejected (kept in the knowledge base)", reopened: "Reopened",
};

function Detail({ id, cats, onDecided, onChanged, onOpen }: { id: string; cats: Category[]; onDecided: (id: number) => void; onChanged: () => void; onOpen: (id: number) => void }) {
  const toast = useToast();
  const { data: e, error, setData } = useApi<EntryDetail>(`/api/entries/${id}`);
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [tab, setTab] = useState<"diff" | "new" | "old">("diff");
  const [busy, setBusy] = useState("");
  const [comment, setComment] = useState("");
  const [newLabel, setNewLabel] = useState("");
  if (error) return <div className="p-6"><ErrorNote>{error}</ErrorNote></div>;
  if (!e) return <Loading />;

  const call = async (name: string, fn: () => Promise<EntryDetail>, done?: (d: EntryDetail) => void) => {
    setBusy(name);
    try { const d = await fn(); setData(d); done?.(d); } catch (err) { toast((err as Error).message, true); } finally { setBusy(""); }
  };
  const patch = (body: object, msg?: string) => call("save", () => api<EntryDetail>(`/api/entries/${e.id}`, { method: "PATCH", body }), () => { onChanged(); if (msg) toast(msg); });
  const decide = (action: "approve" | "reject" | "reopen") => call(action, () => api<EntryDetail>(`/api/entries/${e.id}/${action}`, { body: {} }), () => {
    toast(action === "approve" ? (e.status === "removal" ? "Removal approved" : "Approved") : action === "reject" ? "Rejected" : "Back in the review queue");
    onDecided(e.id);
  });
  const waiting = e.status === "new" || e.status === "changed" || e.status === "removal";
  const canEdit = e.status !== "removal" && e.status !== "removed";
  const startEdit = () => { setTitle(e.title); setContent(e.content); setEditing(true); };
  const others = cats.filter((c) => c.id !== e.category_id && !e.secondary_ids.includes(c.id));

  return (
    <div className="mx-auto max-w-[820px] px-8 py-6">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={e.status} />
        {e.edited && <Badge tone="violet">Edited by a reviewer</Badge>}
        {e.manual_edit && !waiting && <Badge tone="violet">Differs from the website</Badge>}
        {e.reviewer && <span className="text-xs text-muted">Last reviewed by {e.reviewer}, {ago(e.reviewed_at)}</span>}
        <div className="ml-auto flex gap-2">
          {canEdit && !editing && <Button size="sm" onClick={startEdit}><Pencil className="size-3.5" /> Edit</Button>}
          {waiting && !editing && <>
            <Button size="sm" variant="danger" busy={busy === "reject"} onClick={() => decide("reject")}><X className="size-3.5" /> {e.status === "removal" ? "Keep it" : e.status === "changed" ? "Reject change" : "Reject"}</Button>
            <Button size="sm" variant="primary" busy={busy === "approve"} onClick={() => decide("approve")}><Check className="size-3.5" /> {e.status === "removal" ? "Approve removal" : e.status === "changed" ? "Approve change" : "Approve"}</Button>
          </>}
          {(e.status === "rejected" || e.status === "removed") && <Button size="sm" busy={busy === "reopen"} onClick={() => decide("reopen")}><RotateCcw className="size-3.5" /> {e.status === "removed" ? "Restore" : "Reopen"}</Button>}
        </div>
      </div>

      {e.status === "removal" && <Note tone="red">This content is no longer on the website. <b>Approve removal</b> to take it out of the knowledge base, or <b>Keep it</b> if the chatbot should still know it.</Note>}
      {e.status === "changed" && <Note tone="amber">The website changed after this entry was approved. The approved text stays live until you approve the change.</Note>}
      {e.scope && !e.scope.in && <Note tone="amber">This does not match anything in Ryan&apos;s KB{e.scope.topic ? <> (closest topic: “{e.scope.topic}”, {Math.round((e.scope.score ?? 0) * 100)}% alike)</> : null}, so the chatbot is not expected to know it. Reject it unless Ryan should be maintaining it.</Note>}
      {e.scope?.in && <p className="mt-3 text-xs text-muted">Matches Ryan&apos;s KB topic <b className="font-medium text-ink">{e.scope.topic}</b> · {Math.round((e.scope.score ?? 0) * 100)}% alike</p>}
      {e.duplicate_of && <Note tone="violet"><Copy className="mr-1 inline size-3.5" />The same text also appears on another page. <button className="font-medium underline" onClick={() => onOpen(e.duplicate_of!)}>Open the other entry</button> and keep only one, so the chatbot is not given the same answer twice.</Note>}

      {editing ? (
        <div className="mt-5 rounded-2xl border border-line bg-white p-5">
          <input className={cn(inputCls, "h-10 text-base font-semibold")} value={title} onChange={(ev) => setTitle(ev.target.value)} />
          <textarea className="mt-3 h-[360px] w-full resize-y rounded-[10px] border border-line p-3 font-mono text-[13px] leading-relaxed outline-none focus:border-neutral-400" value={content} onChange={(ev) => setContent(ev.target.value)} />
          <p className="mt-2 text-xs text-muted">One item per line. Start bullets with <code>- </code>, steps with <code>1. </code>, separate table cells with <code> | </code>, and write links as <code>[text](https://…)</code>.</p>
          <div className="mt-4 flex justify-end gap-2">
            <Button onClick={() => setEditing(false)}>Cancel</Button>
            <Button variant="primary" busy={busy === "save"} onClick={() => patch({ title, content }, waiting ? "Saved. Approve it when it is ready." : "Saved. Publish to make it live.").then(() => setEditing(false))}>Save changes</Button>
          </div>
        </div>
      ) : (
        <div className="mt-5 rounded-2xl border border-line bg-white">
          <div className="border-b border-line px-6 py-4">
            <h2 className="text-lg font-semibold leading-snug tracking-tight">{e.title}</h2>
            {e.page && (
              <a href={e.page.url} target="_blank" rel="noreferrer" className="mt-1 inline-flex max-w-full items-center gap-1.5 text-xs text-muted hover:text-ink">
                <span className="truncate">From “{e.page.title}” · <span className="font-mono">{pathOf(e.page.url)}</span></span><ExternalLink className="size-3 shrink-0" />
              </a>
            )}
          </div>
          {e.status === "changed" && e.diff ? (
            <>
              <div className="flex items-center gap-3 border-b border-line px-4 py-2.5">
                <Tabs value={tab} onChange={setTab} items={[{ value: "diff", label: "What changed" }, { value: "new", label: "New version" }, { value: "old", label: "Approved now" }]} />
                <Stat added={e.added ?? 0} removed={e.removed ?? 0} />
              </div>
              {tab === "diff" ? <DiffView lines={e.diff} /> : <div className="px-6 py-5"><Rich content={tab === "new" ? e.content : e.approved?.content ?? ""} /></div>}
            </>
          ) : (
            <div className={cn("px-6 py-5", e.status === "removal" && "opacity-60")}><Rich content={e.content} /></div>
          )}
        </div>
      )}

      {/* categories and labels */}
      <div className="mt-4 grid grid-cols-2 gap-4">
        <div className="rounded-2xl border border-line bg-white p-4">
          <p className="text-[13px] font-medium">Category</p>
          <p className="mb-2 text-xs text-muted">Where this entry sits in the document.</p>
          <select disabled={!canEdit} className={cn(inputCls, !e.category_id && "border-amber-300 bg-amber-50")} value={e.category_id ?? ""} onChange={(ev) => patch({ category_id: Number(ev.target.value) })}>
            {!e.category_id && <option value="">Choose a category…</option>}
            {cats.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <p className="mb-2 mt-4 text-[13px] font-medium">Also answers questions about</p>
          <div className="flex flex-wrap items-center gap-1.5">
            {e.secondary_ids.map((cid) => {
              const c = cats.find((x) => x.id === cid);
              return c && (
                <span key={cid} className="inline-flex h-7 items-center gap-1.5 rounded-full border border-line pl-2.5 pr-1 text-xs">
                  <span className={cn("size-2 rounded-full", DOT[c.color])} />{c.name}
                  {canEdit && <button aria-label={`Remove ${c.name}`} onClick={() => patch({ secondary_ids: e.secondary_ids.filter((x) => x !== cid) })} className="rounded-full p-0.5 text-neutral-400 hover:bg-neutral-100 hover:text-ink"><X className="size-3" /></button>}
                </span>
              );
            })}
            {canEdit && e.secondary_ids.length < 3 && (
              <select className="h-7 rounded-full border border-dashed border-neutral-300 bg-white px-2 text-xs text-neutral-500" value="" onChange={(ev) => ev.target.value && patch({ secondary_ids: [...e.secondary_ids, Number(ev.target.value)] })}>
                <option value="">+ Add category</option>
                {others.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            )}
          </div>
          <p className="mt-2 text-xs text-muted">Use this when one entry belongs under two topics. It is listed under each and tagged for the chatbot, but written into the document once.</p>
        </div>
        <div className="rounded-2xl border border-line bg-white p-4">
          <p className="text-[13px] font-medium">Labels</p>
          <p className="mb-2 text-xs text-muted">Tags that describe what kind of information this is.</p>
          <div className="flex flex-wrap items-center gap-1.5">
            {e.labels.length === 0 && <span className="text-xs text-neutral-400">No labels</span>}
            {e.labels.map((l) => (
              <span key={l} className="inline-flex h-7 items-center gap-1 rounded-full bg-neutral-100 pl-2.5 pr-1 text-xs"><Tag className="size-3 text-neutral-400" />{l}
                {canEdit && <button aria-label={`Remove ${l}`} onClick={() => patch({ labels: e.labels.filter((x) => x !== l) })} className="rounded-full p-0.5 text-neutral-400 hover:text-ink"><X className="size-3" /></button>}
              </span>
            ))}
          </div>
          {canEdit && (
            <form className="mt-3 flex gap-2" onSubmit={(ev) => { ev.preventDefault(); if (newLabel.trim()) { patch({ labels: [...e.labels, newLabel.trim()] }); setNewLabel(""); } }}>
              <input className={cn(inputCls, "h-8 text-[13px]")} placeholder="Add a label" value={newLabel} onChange={(ev) => setNewLabel(ev.target.value)} />
              <Button size="sm" type="submit" disabled={!newLabel.trim()}><Plus className="size-3.5" /></Button>
            </form>
          )}
        </div>
      </div>

      {/* comments and history */}
      <div className="mt-4 grid grid-cols-2 gap-4 pb-10">
        <div className="rounded-2xl border border-line bg-white p-4">
          <p className="mb-3 text-[13px] font-medium">Comments {e.comments.length > 0 && <span className="text-muted">({e.comments.length})</span>}</p>
          <div className="space-y-3">
            {e.comments.map((c) => (
              <div key={c.id} className="text-[13px]">
                <p><span className="font-medium">{c.author}</span> <span className="text-xs text-muted">{ago(c.created_at)}</span></p>
                <p className="whitespace-pre-wrap text-neutral-700">{c.body}</p>
              </div>
            ))}
          </div>
          <textarea className="mt-3 h-16 w-full resize-none rounded-[10px] border border-line p-2.5 text-[13px] outline-none focus:border-neutral-400" placeholder="Leave a note for other reviewers" value={comment} onChange={(ev) => setComment(ev.target.value)} />
          <div className="mt-2 flex justify-end"><Button size="sm" disabled={!comment.trim()} busy={busy === "comment"} onClick={() => call("comment", () => api<EntryDetail>(`/api/entries/${e.id}/comment`, { body: { note: comment } }), () => setComment(""))}>Comment</Button></div>
        </div>
        <div className="rounded-2xl border border-line bg-white p-4">
          <p className="mb-3 text-[13px] font-medium">History</p>
          <div className="space-y-2.5">
            {e.history.map((h) => (
              <div key={h.id} className="flex gap-2.5 text-[13px]">
                <span className={cn("mt-1.5 size-1.5 shrink-0 rounded-full", h.action.includes("approved") ? "bg-emerald-500" : h.action.includes("rejected") ? "bg-red-400" : h.action.includes("detected") ? "bg-blue-400" : "bg-neutral-300")} />
                <div><p>{ACTIONS[h.action] ?? h.action}{h.actor !== "system" && <span className="text-muted"> by {h.actor}</span>}</p><p className="text-xs text-muted" title={dateTime(h.created_at)}>{dateTime(h.created_at)}</p></div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function Note({ tone, children }: { tone: "red" | "amber" | "violet"; children: React.ReactNode }) {
  return <div className={cn("mt-4 rounded-xl border px-4 py-2.5 text-[13px]", tone === "red" ? "border-red-200 bg-red-50 text-red-800" : tone === "amber" ? "border-amber-200 bg-amber-50 text-amber-900" : "border-violet-200 bg-violet-50 text-violet-900")}>{children}</div>;
}
