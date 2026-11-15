"use client";
import { BookOpenCheck, ExternalLink, Lock, Search, Tag } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";
import { useApi, type Version } from "@/lib/api";
import { useBot } from "@/components/shell";
import { ChangeList } from "@/components/changes";
import { Rich } from "@/components/rich";
import { Badge, Button, Card, Empty, inputCls, Loading, Page, PageHeader, Tabs } from "@/components/ui";
import { cn, dateTime, DOT, pathOf, plural } from "@/lib/utils";

export default function KbPage() {
  return <Suspense><Inner /></Suspense>;
}

function Inner() {
  const bot = useBot();
  const router = useRouter();
  const params = useSearchParams();
  const versions = useApi<Version[]>(`/api/chatbots/${bot}/versions`);
  const latest = versions.data?.[0]?.number;
  const number = Number(params.get("version")) || latest;
  const { data: v } = useApi<Version>(number ? `/api/chatbots/${bot}/versions/${number}` : null);
  const [cat, setCat] = useState("");
  const [q, setQ] = useState("");
  const [tab, setTab] = useState<"content" | "changes">("content");
  const [limit, setLimit] = useState(40);

  const groups = useMemo(() => {
    const m = new Map<string, { color: string; n: number; also: number }>();
    v?.items?.forEach((i) => {
      const g = m.get(i.category) ?? { color: i.color, n: 0, also: 0 };
      g.n++;
      m.set(i.category, g);
    });
    v?.items?.forEach((i) => i.secondary.forEach((s) => { const g = m.get(s); if (g) g.also++; }));
    return [...m.entries()];
  }, [v]);
  const items = useMemo(() => {
    const ql = q.toLowerCase().trim();
    return (v?.items ?? []).filter((i) => (!cat || i.category === cat || i.secondary.includes(cat)) && (!ql || `${i.title} ${i.content}`.toLowerCase().includes(ql)));
  }, [v, cat, q]);

  if (versions.data && versions.data.length === 0)
    return <Page><PageHeader title="Knowledge base" /><Card><Empty icon={<BookOpenCheck className="size-5" />} title="Nothing published yet" action={<Link href={`/${bot}/publish`}><Button variant="primary">Go to Publish</Button></Link>}>The published knowledge base appears here once the first version is published.</Empty></Card></Page>;
  if (!v) return <Page><Loading /></Page>;

  return (
    <Page wide>
      <PageHeader
        title="Knowledge base"
        description="The approved, published content exactly as the chatbot and the document receive it. This view cannot be edited: make changes in Review and publish a new version."
        actions={
          <select className="h-9 rounded-[10px] border border-line bg-white px-3 text-sm font-medium" value={v.number} onChange={(e) => router.replace(`/${bot}/kb?version=${e.target.value}`)}>
            {versions.data?.map((x) => <option key={x.id} value={x.number}>Version {x.number}{x.number === latest ? " (live)" : ""}</option>)}
          </select>
        }
      />
      <div className="mb-5 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-2xl border border-line bg-subtle px-4 py-3 text-[13px]">
        <span className="flex items-center gap-1.5 font-medium"><Lock className="size-3.5" /> Version {v.number}</span>
        {v.number === latest ? <Badge tone="green" dot>Live</Badge> : <Badge tone="outline">Older version</Badge>}
        <span className="text-muted">Published {dateTime(v.created_at)} by {v.created_by}</span>
        <span className="text-muted">{plural(v.stats.total ?? 0, "entry", "entries")}</span>
        {v.note && <span className="text-neutral-700">“{v.note}”</span>}
        <Tabs className="ml-auto" value={tab} onChange={setTab} items={[{ value: "content", label: "Content" }, { value: "changes", label: "What changed", count: v.changes?.length ?? 0 }]} />
      </div>

      {tab === "changes" ? (
        v.changes?.length ? <ChangeList changes={v.changes.slice(0, 200)} openFirst={v.changes.length > 12 ? 0 : 3} /> : <Card><p className="px-5 py-10 text-center text-sm text-muted">No changes recorded.</p></Card>
      ) : (
        <div className="grid grid-cols-[240px_1fr] items-start gap-6">
          <div className="sticky top-8">
            <button onClick={() => { setCat(""); setLimit(40); }} className={cn("mb-0.5 flex h-8 w-full items-center gap-2 rounded-lg px-2 text-left text-[13px]", !cat ? "bg-neutral-100 font-medium" : "text-neutral-600 hover:bg-subtle")}>
              <span className="size-2 rounded-full bg-ink" /><span className="flex-1">All categories</span><span className="text-xs tabular-nums text-neutral-500">{v.items?.length}</span>
            </button>
            {groups.map(([name, g]) => (
              <button key={name} onClick={() => { setCat(name); setLimit(40); }} className={cn("mb-0.5 flex h-8 w-full items-center gap-2 rounded-lg px-2 text-left text-[13px]", cat === name ? "bg-neutral-100 font-medium" : "text-neutral-600 hover:bg-subtle")}>
                <span className={cn("size-2 shrink-0 rounded-full", DOT[g.color] ?? DOT.slate)} /><span className="flex-1 truncate">{name}</span>
                <span className="text-xs tabular-nums text-neutral-500">{g.n}{g.also > 0 && <span className="text-neutral-400"> +{g.also}</span>}</span>
              </button>
            ))}
            <p className="mt-3 px-2 text-xs text-neutral-400">“+n” = entries filed elsewhere that also answer questions in this category.</p>
          </div>
          <div className="min-w-0">
            <div className="relative mb-4">
              <Search className="absolute left-3 top-2.5 size-4 text-neutral-400" />
              <input className={cn(inputCls, "pl-9")} placeholder="Search the published knowledge base" value={q} onChange={(e) => { setQ(e.target.value); setLimit(40); }} />
            </div>
            {items.length === 0 && <Card><p className="px-5 py-10 text-center text-sm text-muted">No entries match.</p></Card>}
            <div className="space-y-3">
              {items.slice(0, limit).map((i) => (
                <Card key={i.entry_id} className="px-6 py-5">
                  <div className="flex items-start justify-between gap-4">
                    <h3 className="text-[15px] font-semibold leading-snug">{i.title}</h3>
                    <span className="flex shrink-0 items-center gap-1.5 text-xs text-neutral-500"><span className={cn("size-2 rounded-full", DOT[i.color] ?? DOT.slate)} />{i.category}</span>
                  </div>
                  <Rich content={i.content} className="mt-3" />
                  <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-line pt-3 text-xs text-muted">
                    {i.secondary.map((s) => <Badge key={s} tone="outline">Also in {s}</Badge>)}
                    {i.labels.map((l) => <span key={l} className="inline-flex items-center gap-1 rounded-full bg-neutral-100 px-2 py-0.5"><Tag className="size-3" />{l}</span>)}
                    {i.manual_edit && <Badge tone="violet">Edited by a reviewer</Badge>}
                    {i.source_url && <a href={i.source_url} target="_blank" rel="noreferrer" className="ml-auto inline-flex items-center gap-1 font-mono hover:text-ink">{pathOf(i.source_url)} <ExternalLink className="size-3" /></a>}
                  </div>
                </Card>
              ))}
            </div>
            {items.length > limit && <button onClick={() => setLimit((l) => l + 80)} className="mt-3 w-full rounded-xl border border-line py-2.5 text-[13px] font-medium text-neutral-600 hover:bg-subtle">Show more ({items.length - limit} remaining)</button>}
          </div>
        </div>
      )}
    </Page>
  );
}
