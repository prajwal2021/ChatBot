"use client";
import { BookOpenCheck, Check, ChevronsUpDown, FileText, GitCompareArrows, Globe, History, LayoutDashboard, ListChecks, Plus, Target, Rocket, Settings, UserRound, Files } from "lucide-react";
import Link from "next/link";
import { useParams, usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, reviewer, useApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button, inputCls, Label, Modal, useToast } from "./ui";

type Bot = { key: string; name: string; description: string; waiting: number };

const NAV: { group?: string; items: { href: string; label: string; icon: typeof Globe; badge?: boolean }[] }[] = [
  { items: [{ href: "", label: "Overview", icon: LayoutDashboard }] },
  { group: "Collect", items: [
    { href: "/sources", label: "Sources", icon: Globe },
    { href: "/pages", label: "Pages", icon: Files },
    { href: "/changes", label: "Changes", icon: GitCompareArrows },
  ] },
  { group: "Curate", items: [
    { href: "/scope", label: "Ryan's KB", icon: Target },
    { href: "/review", label: "Review", icon: ListChecks, badge: true },
    { href: "/publish", label: "Publish", icon: Rocket },
  ] },
  { group: "Deliver", items: [
    { href: "/kb", label: "Knowledge base", icon: BookOpenCheck },
    { href: "/document", label: "Document", icon: FileText },
  ] },
  { group: "Audit", items: [{ href: "/history", label: "History", icon: History }] },
];

export function useBot(): string {
  return useParams<{ bot: string }>().bot;
}

export function Shell({ children }: { children: ReactNode }) {
  const bot = useBot();
  const path = usePathname();
  const router = useRouter();
  const toast = useToast();
  const { data: bots, reload } = useApi<Bot[]>("/api/chatbots", 8000);
  const [open, setOpen] = useState(false);
  const [adding, setAdding] = useState(false);
  const [naming, setNaming] = useState(false);
  const [who, setWho] = useState("Reviewer");
  const menu = useRef<HTMLDivElement>(null);
  const current = bots?.find((b) => b.key === bot);

  // localStorage is only available in the browser, so the name is read after mount
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => setWho(reviewer()), []);
  useEffect(() => {
    const h = (e: MouseEvent) => menu.current && !menu.current.contains(e.target as Node) && setOpen(false);
    window.addEventListener("mousedown", h);
    return () => window.removeEventListener("mousedown", h);
  }, []);

  return (
    <div className="flex h-full">
      <aside className="flex w-[244px] shrink-0 flex-col border-r border-line bg-[#fafafa]">
        <div className="flex items-center gap-2.5 px-4 pb-3 pt-4">
          <div className="flex size-7 items-center justify-center rounded-lg bg-ink text-white"><BookOpenCheck className="size-4" /></div>
          <span className="text-[15px] font-semibold tracking-tight">KB Curation</span>
        </div>

        <div className="relative px-3 pb-2" ref={menu}>
          <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-2.5 rounded-xl border border-line bg-white px-2.5 py-2 text-left hover:border-neutral-300">
            <span className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-neutral-100 text-xs font-semibold">{(current?.name ?? bot).replace(/^TTU /, "").replace(/[^A-Za-z0-9]/g, "").slice(0, 2).toUpperCase()}</span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[13px] font-medium">{current?.name ?? bot}</span>
              <span className="block text-[11px] text-muted">Chatbot</span>
            </span>
            <ChevronsUpDown className="size-3.5 text-neutral-400" />
          </button>
          {open && (
            <div className="rise absolute left-3 right-3 top-full z-30 mt-1 rounded-xl border border-line bg-white p-1 shadow-lg">
              {bots?.map((b) => (
                <button key={b.key} onClick={() => { setOpen(false); router.push(`/${b.key}`); }} className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[13px] hover:bg-neutral-100">
                  <span className="flex-1 truncate font-medium">{b.name}</span>
                  {b.waiting > 0 && <span className="text-xs tabular-nums text-muted">{b.waiting}</span>}
                  {b.key === bot && <Check className="size-3.5" />}
                </button>
              ))}
              <div className="my-1 border-t border-line" />
              <button onClick={() => { setOpen(false); setAdding(true); }} className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[13px] text-neutral-600 hover:bg-neutral-100">
                <Plus className="size-3.5" /> New chatbot
              </button>
            </div>
          )}
        </div>

        <nav className="scroll-thin flex-1 overflow-y-auto px-3 pb-3">
          {NAV.map((g, gi) => (
            <div key={gi} className="mt-3">
              {g.group && <div className="px-2.5 pb-1 text-[11px] font-medium uppercase tracking-wider text-neutral-400">{g.group}</div>}
              {g.items.map((it) => {
                const href = `/${bot}${it.href}`;
                const active = it.href === "" ? path === href : path.startsWith(href);
                return (
                  <Link key={it.href} href={href} className={cn("mb-0.5 flex h-8 items-center gap-2.5 rounded-lg px-2.5 text-[13px] font-medium transition-colors", active ? "bg-neutral-200/70 text-ink" : "text-neutral-600 hover:bg-neutral-200/40 hover:text-ink")}>
                    <it.icon className="size-4" strokeWidth={1.8} />
                    <span className="flex-1">{it.label}</span>
                    {it.badge && !!current?.waiting && <span className="rounded-full bg-ink px-1.5 py-px text-[11px] font-medium tabular-nums text-white">{current.waiting > 999 ? "999+" : current.waiting}</span>}
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>

        <div className="border-t border-line p-3">
          <Link href={`/${bot}/settings`} className={cn("mb-0.5 flex h-8 items-center gap-2.5 rounded-lg px-2.5 text-[13px] font-medium", path.endsWith("/settings") ? "bg-neutral-200/70" : "text-neutral-600 hover:bg-neutral-200/40")}>
            <Settings className="size-4" strokeWidth={1.8} /> Settings
          </Link>
          <button onClick={() => setNaming(true)} className="flex h-9 w-full items-center gap-2.5 rounded-lg px-2.5 text-left text-[13px] hover:bg-neutral-200/40">
            <span className="flex size-6 items-center justify-center rounded-full bg-neutral-200 text-neutral-600"><UserRound className="size-3.5" /></span>
            <span className="min-w-0 flex-1 truncate font-medium">{who}</span>
          </button>
        </div>
      </aside>

      <main className="scroll-thin min-w-0 flex-1 overflow-y-auto">{children}</main>

      {adding && <NewBot onClose={() => setAdding(false)} onDone={(k) => { setAdding(false); reload(); router.push(`/${k}/sources`); toast("Chatbot created. Add or check its source URLs, then run a crawl."); }} />}
      {naming && <Rename who={who} onClose={() => setNaming(false)} onDone={(n) => { setWho(n); setNaming(false); }} />}
    </div>
  );
}

function NewBot({ onClose, onDone }: { onClose: () => void; onDone: (key: string) => void }) {
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const save = async () => {
    setBusy(true);
    try {
      const r = await api<{ key: string }>("/api/chatbots", { body: { name, urls: url ? [url] : [] } });
      onDone(r.key);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal title="New chatbot" onClose={onClose} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" busy={busy} disabled={!name.trim()} onClick={save}>Create chatbot</Button></>}>
      <p className="mb-4 text-sm text-muted">Each chatbot has its own sources, categories, review queue and published knowledge base.</p>
      <Label>Name</Label>
      <input autoFocus className={inputCls} placeholder="e.g. TTU Graduate School" value={name} onChange={(e) => setName(e.target.value)} />
      <div className="h-3" />
      <Label>Website to read (optional)</Label>
      <input className={inputCls} placeholder="https://www.depts.ttu.edu/…" value={url} onChange={(e) => setUrl(e.target.value)} />
      {err && <p className="mt-3 text-sm text-red-600">{err}</p>}
    </Modal>
  );
}

function Rename({ who, onClose, onDone }: { who: string; onClose: () => void; onDone: (n: string) => void }) {
  const [name, setName] = useState(who === "Reviewer" ? "" : who);
  const save = () => { const n = name.trim() || "Reviewer"; localStorage.setItem("kb-reviewer", n); onDone(n); };
  return (
    <Modal title="Your name" onClose={onClose} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" onClick={save}>Save</Button></>}>
      <p className="mb-4 text-sm text-muted">Shown next to your approvals, edits and comments so the team can see who did what.</p>
      <input autoFocus className={inputCls} placeholder="Your name" value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && save()} />
    </Modal>
  );
}
