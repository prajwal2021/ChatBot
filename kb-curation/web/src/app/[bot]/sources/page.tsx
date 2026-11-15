"use client";
import { ExternalLink, Globe, Plus, Trash2, X } from "lucide-react";
import { useState } from "react";
import { api, useApi, type Overview, type Run } from "@/lib/api";
import { useBot } from "@/components/shell";
import { CrawlButton, RunProgress } from "@/components/run";
import { Badge, Button, Card, Empty, ErrorNote, inputCls, Label, Loading, Modal, Page, PageHeader, useToast } from "@/components/ui";
import { ago, dateTime, duration, shortUrl } from "@/lib/utils";

type Source = { id: number; url: string; label: string; max_pages: number; exclude: string[]; schedule_hours: number | null; next_run_at: string | null; last_run_at: string | null; pages: number; skipped: number; removed: number };
const SCHEDULES = [[0, "Manual only"], [6, "Every 6 hours"], [12, "Every 12 hours"], [24, "Every day"], [168, "Every week"]] as const;

export default function SourcesPage() {
  const bot = useBot();
  const toast = useToast();
  const { data: ov, reload: reloadOv } = useApi<Overview>(`/api/chatbots/${bot}/overview`, 2500);
  const active = ov?.active_run ?? null;
  const { data: sources, error, reload } = useApi<Source[]>(`/api/chatbots/${bot}/sources`, active ? 3000 : 15000);
  const { data: runs, reload: reloadRuns } = useApi<Run[]>(`/api/chatbots/${bot}/runs`, active ? 3000 : 15000);
  const [adding, setAdding] = useState(false);
  const refresh = () => { reload(); reloadOv(); reloadRuns(); };

  const patch = async (s: Source, body: object) => {
    try { await api(`/api/sources/${s.id}`, { method: "PATCH", body }); reload(); } catch (e) { toast((e as Error).message, true); }
  };
  const remove = async (s: Source) => {
    if (!confirm(`Stop watching ${shortUrl(s.url)}?\n\nPages already collected stay in the system.`)) return;
    await api(`/api/sources/${s.id}`, { method: "DELETE" });
    reload();
  };

  return (
    <Page>
      <PageHeader
        title="Sources"
        description="The official websites this chatbot learns from. Pages are found two ways: by following every link from the home page, and from the site's sitemap.xml. Every page is then verified (it must load and contain useful information) before anything reaches Review. PDFs, images and other files are ignored."
        actions={<><Button onClick={() => setAdding(true)}><Plus className="size-4" /> Add source</Button><CrawlButton bot={bot} active={!!active} onStarted={refresh} /></>}
      />
      {active && <RunProgress run={active} />}
      {error && <ErrorNote>{error}</ErrorNote>}
      {!sources ? <Loading /> : sources.length === 0 ? (
        <Card><Empty icon={<Globe className="size-5" />} title="No sources yet" action={<Button variant="primary" onClick={() => setAdding(true)}><Plus className="size-4" /> Add source</Button>}>Add the address of the website this chatbot should learn from.</Empty></Card>
      ) : (
        <div className="space-y-3">
          {sources.map((s) => (
            <Card key={s.id} className="p-5">
              <div className="flex items-start gap-4">
                <div className="flex size-10 shrink-0 items-center justify-center rounded-xl border border-line bg-subtle"><Globe className="size-5 text-neutral-500" strokeWidth={1.6} /></div>
                <div className="min-w-0 flex-1">
                  <a href={s.url} target="_blank" rel="noreferrer" className="group inline-flex max-w-full items-center gap-1.5 font-medium hover:underline">
                    <span className="truncate">{shortUrl(s.url)}</span><ExternalLink className="size-3.5 shrink-0 text-neutral-400" />
                  </a>
                  <p className="mt-0.5 text-[13px] text-muted">{s.last_run_at ? `Last checked ${ago(s.last_run_at)}` : "Never checked"}{s.schedule_hours && s.next_run_at ? ` · next check ${ago(s.next_run_at)}` : ""}</p>
                </div>
                <div className="flex items-center gap-2">
                  <CrawlButton bot={bot} sourceId={s.id} active={!!active} onStarted={refresh} label="Check now" variant="secondary" />
                  <button onClick={() => remove(s)} aria-label="Remove source" className="rounded-lg p-2 text-neutral-400 hover:bg-red-50 hover:text-red-600"><Trash2 className="size-4" /></button>
                </div>
              </div>
              <div className="mt-4 grid grid-cols-5 gap-4 border-t border-line pt-4 text-[13px]">
                <Metric label="Pages tracked" value={s.pages} />
                <Metric label="Failed verification" value={s.skipped} />
                <Metric label="Removed pages" value={s.removed} />
                <div>
                  <p className="text-muted">Check automatically</p>
                  <select className="mt-1 h-8 w-full rounded-lg border border-line bg-white px-2 text-[13px]" value={s.schedule_hours ?? 0} onChange={(e) => patch(s, { set_schedule: true, schedule_hours: Number(e.target.value) || null })}>
                    {SCHEDULES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                </div>
                <div>
                  <p className="text-muted">Page limit</p>
                  <select className="mt-1 h-8 w-full rounded-lg border border-line bg-white px-2 text-[13px]" value={s.max_pages} onChange={(e) => patch(s, { max_pages: Number(e.target.value) })}>
                    {[250, 500, 1000, 2500, 5000].map((v) => <option key={v} value={v}>{v.toLocaleString()} pages</option>)}
                  </select>
                </div>
              </div>
              <Exclude source={s} onSave={(exclude) => patch(s, { exclude })} />
            </Card>
          ))}
        </div>
      )}

      <h2 className="mb-3 mt-10 font-semibold">Crawl history</h2>
      <Card className="overflow-hidden">
        {!runs?.length ? <p className="px-5 py-8 text-center text-sm text-muted">No crawls yet.</p> : (
          <table className="w-full text-left text-[13px]">
            <thead className="border-b border-line bg-subtle text-xs text-muted">
              <tr>{["When", "Started by", "Duration", "Addresses", "Failed checks", "New", "Updated", "Removed", "Unchanged", "For review", "Result"].map((h) => <th key={h} className="px-4 py-2.5 font-medium first:pl-5">{h}</th>)}</tr>
            </thead>
            <tbody className="divide-y divide-line">
              {runs.map((r) => (
                <tr key={r.id} className="hover:bg-subtle">
                  <td className="py-2.5 pl-5 pr-4 font-medium" title={dateTime(r.created_at)}>{dateTime(r.created_at)}</td>
                  <td className="px-4 text-muted">{r.trigger === "schedule" ? "Schedule" : r.created_by}</td>
                  <td className="px-4 tabular-nums text-muted">{duration(r.started_at, r.finished_at)}</td>
                  <td className="px-4 tabular-nums">{r.stats.discovered ?? "—"}</td>
                  <td className="px-4 tabular-nums text-muted">{r.stats.rejected ?? "—"}</td>
                  <Num v={r.stats.new} c="text-blue-700" /><Num v={r.stats.changed} c="text-amber-700" /><Num v={r.stats.removed} c="text-red-600" />
                  <td className="px-4 tabular-nums text-muted">{r.stats.unchanged ?? "—"}</td>
                  <td className="px-4 tabular-nums">{r.status === "done" ? (r.stats.entries_new ?? 0) + (r.stats.entries_changed ?? 0) + (r.stats.entries_removal ?? 0) : "—"}</td>
                  <td className="px-4">{r.status === "done" ? <Badge tone="green" dot>Done</Badge> : r.status === "failed" ? <span title={r.error ?? ""}><Badge tone="red" dot>Failed</Badge></span> : <Badge tone="blue" dot>Running</Badge>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      {adding && <AddSource bot={bot} onClose={() => setAdding(false)} onDone={() => { setAdding(false); reload(); toast("Source added. Run a crawl to collect its pages."); }} />}
    </Page>
  );
}

function Exclude({ source, onSave }: { source: Source; onSave: (list: string[]) => void }) {
  const [v, setV] = useState("");
  const add = () => { const x = v.trim(); if (x && !source.exclude.includes(x)) onSave([...source.exclude, x]); setV(""); };
  return (
    <div className="mt-4 border-t border-line pt-4 text-[13px]">
      <p className="font-medium">Parts of the site to leave out</p>
      <p className="text-xs text-muted">Any address containing one of these is never read, e.g. <code>/newsletter/</code> or <code>/about/staff/</code>. Applies from the next crawl; content already collected from those pages is proposed for removal.</p>
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        {source.exclude.map((x) => (
          <span key={x} className="inline-flex h-7 items-center gap-1 rounded-full bg-neutral-100 pl-2.5 pr-1 font-mono text-xs">{x}
            <button aria-label={`Remove ${x}`} onClick={() => onSave(source.exclude.filter((y) => y !== x))} className="rounded-full p-0.5 text-neutral-400 hover:text-ink"><X className="size-3" /></button>
          </span>
        ))}
        <form onSubmit={(e) => { e.preventDefault(); add(); }} className="flex gap-1.5">
          <input className="h-7 w-44 rounded-full border border-dashed border-neutral-300 px-2.5 font-mono text-xs outline-none focus:border-neutral-500" placeholder="/path-to-skip/" value={v} onChange={(e) => setV(e.target.value)} />
          {v.trim() && <Button size="sm" type="submit" className="h-7">Add</Button>}
        </form>
      </div>
    </div>
  );
}

const Metric = ({ label, value }: { label: string; value: number }) => <div><p className="text-muted">{label}</p><p className="mt-1 text-lg font-semibold tabular-nums">{value.toLocaleString()}</p></div>;
const Num = ({ v, c }: { v?: number; c: string }) => <td className={`px-4 tabular-nums ${v ? `font-medium ${c}` : "text-neutral-300"}`}>{v ?? "—"}</td>;

function AddSource({ bot, onClose, onDone }: { bot: string; onClose: () => void; onDone: () => void }) {
  const [url, setUrl] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try { await api(`/api/chatbots/${bot}/sources`, { body: { url } }); onDone(); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <Modal title="Add source" onClose={onClose} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" busy={busy} disabled={!url.trim()} onClick={save}>Add source</Button></>}>
      <Label>Website address</Label>
      <input autoFocus className={inputCls} placeholder="https://www.depts.ttu.edu/k12/" value={url} onChange={(e) => setUrl(e.target.value)} onKeyDown={(e) => e.key === "Enter" && save()} />
      <p className="mt-2 text-[13px] text-muted">Every page whose address starts with this one is included. Files such as PDFs are skipped.</p>
      {err && <p className="mt-3 text-sm text-red-600">{err}</p>}
    </Modal>
  );
}
