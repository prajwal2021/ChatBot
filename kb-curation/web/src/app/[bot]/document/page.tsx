"use client";
import { AlertTriangle, Bot, Braces, Download, ExternalLink, FileText, FileType, Link2, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { api, API, useApi, type Item, type Version } from "@/lib/api";
import { useBot } from "@/components/shell";
import { Rich } from "@/components/rich";
import { Badge, Button, Card, Empty, inputCls, Loading, Modal, Page, PageHeader, Tabs, useToast } from "@/components/ui";
import { ago, dateTime, plural } from "@/lib/utils";

type Doc = { gdoc_url: string | null; gdoc_id: string | null; google_connected: boolean; service_email: string | null; synced_version: number | null; synced_at: string | null; error: string | null; latest_version: number | null; published_at: string | null };

export default function DocumentPage() {
  const bot = useBot();
  const toast = useToast();
  const doc = useApi<Doc>(`/api/chatbots/${bot}/document`);
  const d = doc.data;
  const { data: v } = useApi<Version>(d?.latest_version ? `/api/chatbots/${bot}/versions/${d.latest_version}` : null);
  const { data: bots } = useApi<{ key: string; name: string }[]>("/api/chatbots");
  const name = bots?.find((b) => b.key === bot)?.name ?? "";
  const [tab, setTab] = useState<"preview" | "gdoc">("preview");
  const [url, setUrl] = useState<string | null>(null);
  const [busy, setBusy] = useState("");
  const [warn, setWarn] = useState(false);
  const [full, setFull] = useState(false);

  const groups = useMemo(() => {
    const out: { category: string; items: Item[] }[] = [];
    (v?.items ?? []).forEach((i) => {
      if (out.at(-1)?.category !== i.category) out.push({ category: i.category, items: [] });
      out.at(-1)!.items.push(i);
    });
    return out;
  }, [v]);

  const run = async (nameOf: string, fn: () => Promise<Doc>, ok: string) => {
    setBusy(nameOf);
    try { doc.setData(await fn()); toast(ok); } catch (e) { toast((e as Error).message, true); doc.reload(); } finally { setBusy(""); }
  };
  const link = () => run("link", () => api<Doc>(`/api/chatbots/${bot}/document`, { method: "PUT", body: { gdoc_url: url ?? "" } }), url ? "Google Doc linked" : "Google Doc unlinked").then(() => setUrl(null));
  const sync = () => run("sync", () => api<Doc>(`/api/chatbots/${bot}/document/sync`, { body: {} }), "Google Doc updated");
  const exp = (f: string) => `${API}/api/chatbots/${bot}/export?format=${f}`;

  if (!d) return <Page><Loading /></Page>;
  const upToDate = d.gdoc_url && d.synced_version === d.latest_version && !d.error;
  let shown = 0;

  return (
    <Page wide>
      <PageHeader
        title="Document"
        description="The published knowledge base as one shareable document. It is written by the system from approved entries, each under its category."
        actions={d.latest_version && <a href={exp("docx")}><Button><Download className="size-4" /> Download Word file</Button></a>}
      />
      {!d.latest_version ? (
        <Card><Empty icon={<FileText className="size-5" />} title="No document yet" action={<Link href={`/${bot}/publish`}><Button variant="primary">Go to Publish</Button></Link>}>The document is created when the first version is published.</Empty></Card>
      ) : (
        <div className="grid grid-cols-[1fr_320px] items-start gap-6">
          <div className="min-w-0">
            <div className="mb-4 flex items-center gap-3">
              <Tabs value={tab} onChange={setTab} items={[{ value: "preview", label: "Preview" }, { value: "gdoc", label: "Google Doc" }]} />
              <span className="text-[13px] text-muted">Version {d.latest_version} · published {dateTime(d.published_at)}</span>
            </div>

            <div className="mb-4 flex gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-[13px] text-amber-900">
              <AlertTriangle className="mt-0.5 size-4 shrink-0" />
              <p><b>Do not edit this document directly.</b> It is rewritten every time a version is published, so edits made in Word or Google Docs are lost and the document stops matching what was approved. Make changes in <Link href={`/${bot}/review`} className="font-medium underline">Review</Link> and publish; they will appear here automatically.</p>
            </div>

            {tab === "preview" ? (
              <div className="rounded-2xl border border-line bg-neutral-100 p-6">
                <div className="mx-auto max-w-[800px] rounded-sm bg-white px-16 py-14 shadow-sm">
                  <h1 className="text-[28px] font-semibold tracking-tight">{name} Knowledge Base</h1>
                  <p className="mt-1 text-xs italic text-neutral-500">Version {v?.number} · Published {dateTime(v?.created_at)} · {plural(v?.items?.length ?? 0, "entry", "entries")}</p>
                  {!v ? <Loading /> : groups.map((g) => {
                    if (!full && shown >= 25) return null;
                    return (
                      <section key={g.category}>
                        <h2 className="mb-1 mt-9 border-b border-neutral-200 pb-1.5 text-xl font-semibold text-neutral-900">{g.category}</h2>
                        {g.items.map((i) => {
                          if (!full && shown >= 25) return null;
                          shown++;
                          return (
                            <article key={i.entry_id}>
                              <h3 className="mb-1.5 mt-5 text-[15px] font-semibold text-neutral-800">{i.title}</h3>
                              <Rich content={i.content} className="text-[13.5px]" />
                              <p className="mt-2 text-[11px] italic text-neutral-500">
                                {i.source_url && <>Source: <a href={i.source_url} target="_blank" rel="noreferrer" className="text-blue-700 underline">{i.source_url}</a></>}
                                {i.secondary.length > 0 && <span className="ml-3">Also relevant to: {i.secondary.join(", ")}</span>}
                              </p>
                            </article>
                          );
                        })}
                      </section>
                    );
                  })}
                  {!full && (v?.items?.length ?? 0) > 25 && <div className="mt-10 border-t border-dashed border-neutral-300 pt-6 text-center"><Button onClick={() => setFull(true)}>Show the full document ({(v!.items!.length - 25).toLocaleString()} more entries)</Button></div>}
                </div>
              </div>
            ) : d.gdoc_id ? (
              <div className="overflow-hidden rounded-2xl border border-line">
                <div className="flex items-center gap-3 border-b border-line bg-subtle px-4 py-2.5 text-[13px]">
                  <FileType className="size-4 text-blue-600" /><span className="font-medium">Google Doc</span>
                  {upToDate ? <Badge tone="green" dot>Matches version {d.latest_version}</Badge> : <Badge tone="amber" dot>Not updated to version {d.latest_version}</Badge>}
                  <span className="ml-auto flex gap-2">
                    <a href={`https://docs.google.com/document/d/${d.gdoc_id}/preview`} target="_blank" rel="noreferrer"><Button size="sm"><ExternalLink className="size-3.5" /> Open read-only</Button></a>
                    <Button size="sm" variant="ghost" onClick={() => setWarn(true)}>Edit in Google Docs…</Button>
                  </span>
                </div>
                <iframe title="Google Doc" src={`https://docs.google.com/document/d/${d.gdoc_id}/preview`} className="h-[820px] w-full bg-white" />
              </div>
            ) : (
              <Card><Empty icon={<Link2 className="size-5" />} title="No Google Doc linked">Link a Google Doc on the right and every published version is written into it, so the team always has one shareable, up-to-date copy.</Empty></Card>
            )}
          </div>

          <div className="sticky top-8 space-y-4">
            <Card className="p-5">
              <div className="flex items-center gap-2"><FileType className="size-4 text-blue-600" /><h2 className="font-semibold">Google Doc</h2></div>
              {d.gdoc_url && url === null ? (
                <>
                  <p className="mt-2 text-[13px]">{upToDate ? <Badge tone="green" dot>Up to date · v{d.synced_version}</Badge> : d.synced_version ? <Badge tone="amber" dot>Shows v{d.synced_version}, latest is v{d.latest_version}</Badge> : <Badge tone="amber" dot>Not written yet</Badge>}</p>
                  {d.synced_at && <p className="mt-1.5 text-xs text-muted">Last written {ago(d.synced_at)}</p>}
                  {d.error && <p className="mt-2 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">{d.error}</p>}
                  {!d.google_connected && <p className="mt-2 rounded-lg bg-subtle px-3 py-2 text-xs text-neutral-600">Google access is not set up on the server yet, so the Doc cannot be written automatically. Until then, download the Word file and use File → Open in Google Docs.</p>}
                  <div className="mt-3 flex gap-2">
                    <Button size="sm" variant="primary" busy={busy === "sync"} disabled={!d.google_connected} onClick={sync}><RefreshCw className="size-3.5" /> Update now</Button>
                    <Button size="sm" onClick={() => setUrl(d.gdoc_url ?? "")}>Change link</Button>
                  </div>
                </>
              ) : (
                <>
                  <p className="mt-2 text-[13px] text-muted">Paste the link of the Google Doc that should hold this knowledge base.</p>
                  <input className={`${inputCls} mt-3`} placeholder="https://docs.google.com/document/d/…" value={url ?? ""} onChange={(e) => setUrl(e.target.value)} />
                  {d.service_email && <p className="mt-2 text-xs text-muted">Share the Doc with <span className="font-mono">{d.service_email}</span> as Editor.</p>}
                  <div className="mt-3 flex gap-2">
                    <Button size="sm" variant="primary" busy={busy === "link"} disabled={!url && !d.gdoc_url} onClick={link}>{url ? "Link document" : d.gdoc_url ? "Unlink" : "Link document"}</Button>
                    {d.gdoc_url && <Button size="sm" onClick={() => setUrl(null)}>Cancel</Button>}
                  </div>
                </>
              )}
            </Card>

            <Card className="p-5">
              <h2 className="font-semibold">Download</h2>
              <div className="mt-3 space-y-1.5">
                {[["docx", "Word document", "For sharing and printing", FileText], ["md", "Markdown", "Plain text with headings", FileType], ["json", "JSON feed", "One record per entry", Braces]].map(([f, t, s, Icon]) => {
                  const I = Icon as typeof FileText;
                  return (
                    <a key={f as string} href={exp(f as string)} className="flex items-center gap-3 rounded-xl border border-line px-3 py-2 hover:bg-subtle">
                      <I className="size-4 text-neutral-500" /><span className="flex-1"><span className="block text-[13px] font-medium">{t as string}</span><span className="block text-xs text-muted">{s as string}</span></span><Download className="size-3.5 text-neutral-400" />
                    </a>
                  );
                })}
              </div>
            </Card>

            <Card className="p-5">
              <div className="flex items-center gap-2"><Bot className="size-4" /><h2 className="font-semibold">Chatbot feed</h2><Badge tone="outline">Next phase</Badge></div>
              <p className="mt-2 text-[13px] text-muted">The chatbot should read the JSON feed, not the document. Each entry arrives as one clean chunk with its category, labels and source link, so answers can be traced back to a page. The document stays as the copy people read and share.</p>
              <p className="mt-3 break-all rounded-lg bg-subtle px-3 py-2 font-mono text-[11px] text-neutral-600">GET {exp("json")}</p>
            </Card>
          </div>
        </div>
      )}

      {warn && d.gdoc_id && (
        <Modal title="Edit the Google Doc directly?" onClose={() => setWarn(false)} footer={<><Button variant="primary" onClick={() => setWarn(false)}>Cancel</Button><a href={`https://docs.google.com/document/d/${d.gdoc_id}/edit`} target="_blank" rel="noreferrer" onClick={() => setWarn(false)}><Button variant="danger">Open for editing anyway</Button></a></>}>
          <div className="space-y-3 text-sm text-neutral-700">
            <p>Edits made in Google Docs are <b>not saved to the knowledge base</b>:</p>
            <ul className="list-disc space-y-1 pl-5">
              <li>They are overwritten the next time a version is published.</li>
              <li>The chatbot never sees them.</li>
              <li>The document will no longer match what reviewers approved.</li>
            </ul>
            <p>To change the content, edit the entry in <Link href={`/${bot}/review`} className="font-medium underline">Review</Link> and publish. The document updates by itself.</p>
          </div>
        </Modal>
      )}
    </Page>
  );
}
