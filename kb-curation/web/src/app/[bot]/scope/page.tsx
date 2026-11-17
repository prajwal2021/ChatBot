"use client";
import { ArrowRight, CheckCircle2, CircleSlash, RefreshCw, Target } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { api, useApi } from "@/lib/api";
import { useBot } from "@/components/shell";
import { Badge, Button, Card, Drawer, Empty, ErrorNote, Loading, Page, PageHeader, useToast } from "@/components/ui";
import { cn } from "@/lib/utils";

type Topic = { id: number; name: string; group: string; words: number; matched: number; waiting: number; approved: number };
type Scope = { enabled: boolean; threshold: number; default_threshold: number; ai: boolean; outside: { waiting: number; approved: number }; topics: Topic[] };

export default function ScopePage() {
  const bot = useBot();
  const toast = useToast();
  const { data, error, setData } = useApi<Scope>(`/api/chatbots/${bot}/scope`);
  const [busy, setBusy] = useState("");
  const [open, setOpen] = useState<Topic | null>(null);
  const [thr, setThr] = useState<number | null>(null);

  const run = async (name: string, fn: () => Promise<Scope>, msg: string) => {
    setBusy(name);
    try { setData(await fn()); toast(msg); setThr(null); } catch (e) { toast((e as Error).message, true); } finally { setBusy(""); }
  };
  if (error) return <Page><ErrorNote>{error}</ErrorNote></Page>;
  if (!data) return <Loading />;

  const groups = [...new Set(data.topics.map((t) => t.group))];
  const gaps = data.topics.filter((t) => t.matched === 0);
  const covered = data.topics.length - gaps.length;
  const t = thr ?? data.threshold;

  return (
    <Page>
      <PageHeader title="Ryan's KB" description="The topics Ryan maintains by hand. Every entry found on the website is compared with them, so the chatbot only receives what Ryan expects, and you can see which of his topics the website does not cover."
        actions={data.enabled && <Button busy={busy === "match"} onClick={() => run("match", () => api<Scope>(`/api/chatbots/${bot}/scope/match`, { body: {} }), "Entries compared again")}>{busy !== "match" && <RefreshCw className="size-4" />} Compare again</Button>} />

      {!data.enabled ? (
        <Card><Empty icon={<Target className="size-5" />} title="Ryan's KB is not loaded for this chatbot">
          Load his document from the backend folder, then come back:
          <code className="mt-3 block rounded-lg bg-subtle px-3 py-2 text-left text-xs">python -m app.scope_import {bot} /path/to/kb.pdf</code>
        </Empty></Card>
      ) : (
        <>
          <div className="grid grid-cols-4 gap-4">
            <Tile label="Topics Ryan maintains" value={data.topics.length} />
            <Tile label="Found on the website" value={covered} note={`${Math.round((covered / data.topics.length) * 100)}% of his topics`} tone="green" />
            <Tile label="Not found on the website" value={gaps.length} note="may need a source or a manual entry" tone={gaps.length ? "amber" : undefined} />
            <Tile label="Outside Ryan's KB" value={data.outside.waiting} note="waiting, not part of his topics" tone={data.outside.waiting ? "amber" : undefined} href={`/${bot}/review?scope=out`} />
          </div>

          <Card className="mt-4 flex items-center gap-6 px-5 py-4">
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">How closely an entry must match</p>
              <p className="text-xs text-muted">Entries that are clearly close or clearly far are decided by this value. Borderline ones are read by an AI and judged on what they say, so the slider does not move those. Nothing is deleted either way.</p>
            </div>
            <input type="range" min={0.4} max={0.8} step={0.01} value={t} onChange={(e) => setThr(Number(e.target.value))} className="w-56 accent-black" aria-label="Match strictness" />
            <span className="w-10 text-right text-sm tabular-nums">{t.toFixed(2)}</span>
            <Button disabled={thr === null || thr === data.threshold} busy={busy === "thr"} onClick={() => run("thr", () => api<Scope>(`/api/chatbots/${bot}/scope`, { method: "PUT", body: { threshold: t } }), "Saved")}>Save</Button>
          </Card>

          {groups.map((g) => (
            <div key={g} className="mt-6">
              <p className="pb-2 text-[11px] font-medium uppercase tracking-wider text-neutral-400">{g}</p>
              <Card className="overflow-hidden">
                <table className="w-full text-left text-[13px]">
                  <thead className="border-b border-line bg-subtle text-xs text-muted">
                    <tr><th className="px-4 py-2.5 font-medium">Topic in Ryan&apos;s KB</th><th className="w-28 px-4 py-2.5 font-medium">Website</th><th className="w-24 px-4 py-2.5 text-right font-medium">Entries</th><th className="w-24 px-4 py-2.5 text-right font-medium">To review</th><th className="w-24 px-4 py-2.5 text-right font-medium">Approved</th><th className="w-10" /></tr>
                  </thead>
                  <tbody>
                    {data.topics.filter((x) => x.group === g).map((x) => (
                      <tr key={x.id} onClick={() => setOpen(x)} className="cursor-pointer border-b border-line last:border-0 hover:bg-subtle">
                        <td className="px-4 py-2.5"><span className="font-medium">{x.name}</span><span className="ml-2 text-xs text-muted">{x.words.toLocaleString()} words</span></td>
                        <td className="px-4 py-2.5">{x.matched === 0 ? <Badge tone="amber"><CircleSlash className="size-3" /> Not found</Badge> : <Badge tone="green"><CheckCircle2 className="size-3" /> Found</Badge>}</td>
                        <td className="px-4 py-2.5 text-right tabular-nums">{x.matched}</td>
                        <td className={cn("px-4 py-2.5 text-right tabular-nums", !x.waiting && "text-neutral-300")}>{x.waiting}</td>
                        <td className={cn("px-4 py-2.5 text-right tabular-nums", !x.approved && "text-neutral-300")}>{x.approved}</td>
                        <td className="px-2"><ArrowRight className="size-4 text-neutral-300" /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>
            </div>
          ))}
        </>
      )}
      {open && <TopicDrawer topic={open} onClose={() => setOpen(null)} />}
    </Page>
  );
}

function Tile({ label, value, note, tone, href }: { label: string; value: number; note?: string; tone?: "green" | "amber"; href?: string }) {
  const inner = (
    <Card className={cn("h-full p-4", href && "hover:bg-subtle")}>
      <p className="text-xs text-muted">{label}</p>
      <p className={cn("mt-1 text-[26px] font-semibold tracking-tight", tone === "amber" && "text-amber-600", tone === "green" && "text-emerald-600")}>{value.toLocaleString()}</p>
      {note && <p className="text-xs text-muted">{note}</p>}
    </Card>
  );
  return href ? <Link href={href}>{inner}</Link> : inner;
}

function TopicDrawer({ topic, onClose }: { topic: Topic; onClose: () => void }) {
  const bot = useBot();
  const { data } = useApi<{ text: string; truncated: boolean }>(`/api/scope-topics/${topic.id}`);
  return (
    <Drawer title={topic.name} subtitle={`${topic.group} · ${topic.words.toLocaleString()} words in Ryan's KB`} onClose={onClose}>
      <div className="space-y-4 p-5">
        <div className="flex items-center gap-2">
          <Badge tone={topic.matched ? "green" : "amber"}>{topic.matched ? `${topic.matched} entries found on the website` : "Nothing found on the website"}</Badge>
          {topic.matched > 0 && <Link href={`/${bot}/review?topic=${topic.id}&scope=in`}><Button size="sm">Open in Review <ArrowRight className="size-3.5" /></Button></Link>}
        </div>
        {topic.matched === 0 && <p className="text-[13px] text-muted">None of the pages we collected cover this topic. It may live on a page that is not a source yet, behind a login, or only in Ryan&apos;s document.</p>}
        <p className="text-[11px] font-medium uppercase tracking-wider text-neutral-400">What Ryan&apos;s KB says</p>
        {!data ? <Loading /> : <pre className="whitespace-pre-wrap rounded-xl border border-line bg-subtle p-4 font-sans text-[13px] leading-relaxed text-neutral-700">{data.text}{data.truncated ? "\n\n…" : ""}</pre>}
      </div>
    </Drawer>
  );
}
