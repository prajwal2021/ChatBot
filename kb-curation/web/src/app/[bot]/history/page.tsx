"use client";
import { BookOpenCheck, Files, History, Library, ListChecks, Settings } from "lucide-react";
import { useMemo, useState } from "react";
import { useApi } from "@/lib/api";
import { useBot } from "@/components/shell";
import { Card, Empty, ErrorNote, Loading, Page, PageHeader, Tabs } from "@/components/ui";
import { cn } from "@/lib/utils";

type Item = { id: number; area: "pages" | "review" | "publish" | "servicenow" | "settings"; action: string; actor: string; summary: string; detail: { urls?: string[]; note?: string }; created_at: string };
type Area = "" | Item["area"];
const AREA = {
  pages: { label: "Pages & crawling", icon: Files, color: "bg-blue-50 text-blue-700" },
  review: { label: "Review", icon: ListChecks, color: "bg-amber-50 text-amber-700" },
  publish: { label: "Publishing", icon: BookOpenCheck, color: "bg-emerald-50 text-emerald-700" },
  servicenow: { label: "ServiceNow", icon: Library, color: "bg-violet-50 text-violet-700" },
  settings: { label: "Settings", icon: Settings, color: "bg-neutral-100 text-neutral-600" },
} as const;

export default function HistoryPage() {
  const bot = useBot();
  const [area, setArea] = useState<Area>("");
  const [limit, setLimit] = useState(200);
  const { data, error } = useApi<{ counts: Record<string, number>; items: Item[] }>(`/api/chatbots/${bot}/activity?limit=${limit}${area ? `&area=${area}` : ""}`, 15000);
  const total = Object.values(data?.counts ?? {}).reduce((a, b) => a + b, 0);
  const days = useMemo(() => {
    const out: { day: string; items: Item[] }[] = [];
    data?.items.forEach((i) => {
      const day = new Date(i.created_at).toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric", year: "numeric" });
      if (out.at(-1)?.day !== day) out.push({ day, items: [] });
      out.at(-1)!.items.push(i);
    });
    return out;
  }, [data]);

  return (
    <Page>
      <PageHeader title="History" description="Everything that has been done for this chatbot, newest first: crawls, pages added or left out, review decisions, edits, published versions and settings changes, with who did it and when." />
      {error && <ErrorNote>{error}</ErrorNote>}
      <Tabs className="mb-5" value={area} onChange={(v) => { setArea(v); setLimit(200); }} items={[
        { value: "", label: "Everything", count: total },
        ...(Object.keys(AREA) as Item["area"][]).map((k) => ({ value: k as Area, label: AREA[k].label, count: data?.counts[k] ?? 0 })),
      ]} />
      {!data ? <Loading /> : data.items.length === 0 ? (
        <Card><Empty icon={<History className="size-5" />} title="Nothing recorded yet">Actions appear here as soon as someone crawls, reviews, publishes or changes a setting.</Empty></Card>
      ) : (
        <div className="space-y-6">
          {days.map((d) => (
            <div key={d.day}>
              <p className="mb-2 text-xs font-medium uppercase tracking-wider text-neutral-400">{d.day}</p>
              <Card className="divide-y divide-line">
                {d.items.map((i) => {
                  const A = AREA[i.area] ?? AREA.settings;
                  return (
                    <div key={i.id} className="flex gap-3 px-4 py-3">
                      <span className={cn("mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg", A.color)}><A.icon className="size-3.5" /></span>
                      <div className="min-w-0 flex-1">
                        <p className="text-[13px] text-neutral-800">{i.summary}</p>
                        {i.detail.note && <p className="mt-0.5 text-xs italic text-muted">“{i.detail.note}”</p>}
                        {i.detail.urls && i.detail.urls.length > 1 && (
                          <details className="mt-1 text-xs text-muted">
                            <summary className="cursor-pointer hover:text-ink">Show the {i.detail.urls.length} pages</summary>
                            <div className="mt-1 space-y-0.5 font-mono">{i.detail.urls.map((u) => <p key={u} className="truncate">{u}</p>)}</div>
                          </details>
                        )}
                        <p className="mt-0.5 text-xs text-muted">{i.actor} · {new Date(i.created_at).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}</p>
                      </div>
                    </div>
                  );
                })}
              </Card>
            </div>
          ))}
          {data.items.length >= limit && <button onClick={() => setLimit((l) => l + 300)} className="w-full rounded-xl border border-line py-2.5 text-[13px] font-medium text-neutral-600 hover:bg-subtle">Show older activity</button>}
        </div>
      )}
    </Page>
  );
}
