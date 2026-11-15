"use client";
import { useCallback, useEffect, useRef, useState } from "react";

export const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8010";

export function reviewer(): string {
  if (typeof window === "undefined") return "Reviewer";
  return localStorage.getItem("kb-reviewer") || "Reviewer";
}

export async function api<T = unknown>(path: string, opts: { method?: string; body?: unknown } = {}): Promise<T> {
  const r = await fetch(API + path, {
    method: opts.method ?? (opts.body ? "POST" : "GET"),
    headers: { "Content-Type": "application/json", "X-Reviewer": reviewer() },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
    cache: "no-store",
  });
  if (!r.ok) {
    let msg = `Request failed (${r.status})`;
    try {
      const j = await r.json();
      if (typeof j.detail === "string") msg = j.detail;
    } catch {}
    throw new Error(msg);
  }
  return r.json();
}

/** Fetch `path` (skipped when null). `refresh` re-fetches every N ms without flashing the loading state. */
export function useApi<T>(path: string | null, refresh?: number) {
  const [data, setData] = useState<T | undefined>();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(!!path);
  const current = useRef(path);
  const load = useCallback(async () => {
    if (!path) return;
    try {
      const d = await api<T>(path);
      if (current.current === path) {
        setData(d);
        setError(null);
      }
    } catch (e) {
      if (current.current === path) setError(e instanceof Error && e.message !== "Failed to fetch" ? e.message : "Cannot reach the KB Curation server. Is the backend running on port 8010?");
    } finally {
      if (current.current === path) setLoading(false);
    }
  }, [path]);
  useEffect(() => {
    current.current = path;
    if (!path) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- reset when the request is switched off
      setData(undefined);
      setLoading(false);
      return;
    }
    setLoading(true);
    load();
    if (!refresh) return;
    const t = setInterval(load, refresh);
    return () => clearInterval(t);
  }, [path, refresh, load]);
  return { data, error, loading, reload: load, setData };
}

// ── types ────────────────────────────────────────────────────────────────────
export type DiffLine = { t: "+" | "-" | " " | "@"; s: string };
export type Run = {
  id: number; status: "queued" | "running" | "done" | "failed"; stage: string; trigger: string;
  progress: { fetched?: number; found?: number; current?: string; applied?: number };
  stats: Record<string, number>; error: string | null; created_by: string; created_at: string; started_at: string | null; finished_at: string | null;
};
export type Category = { id: number; key: string; name: string; description: string; keywords: string[]; color: string; position: number; total: number; waiting: number; also: number };
export type PageRef = { id: number; url: string; title: string; status?: string };
export type EntryStatus = "new" | "changed" | "removal" | "approved" | "rejected" | "removed";
export type Entry = {
  id: number; status: EntryStatus; title: string; excerpt?: string; content?: string; category_id: number | null; secondary_ids: number[]; labels: string[];
  page: PageRef | null; has_approved: boolean; duplicate_of: number | null; manual_edit: boolean; edited: boolean; reviewer: string | null;
  reviewed_at: string | null; detected_at: string; updated_at: string; revision: number;
};
export type EntryDetail = Entry & {
  content: string; approved: { title: string; content: string; category_id: number | null; secondary_ids: number[]; labels: string[] } | null;
  diff?: DiffLine[]; added?: number; removed?: number;
  comments: { id: number; author: string; body: string; created_at: string }[];
  history: { id: number; action: string; actor: string; detail: Record<string, unknown>; created_at: string }[];
};
export type PageRow = {
  id: number; url: string; title: string; status: "active" | "removed" | "skipped" | "error" | "excluded"; reason: string | null; http_status: number | null; depth: number; found_via: "link" | "sitemap" | "manual"; verdict: "ok" | "fail" | null; kept_by_person: boolean;
  first_seen_at: string; last_crawled_at: string | null; last_changed_at: string | null; last_change_kind: string | null; change_count: number;
  changed_in_last_run: boolean; new_in_last_run: boolean; entries: number; waiting: number;
};
export type PageEvent = { id: number; kind: "new" | "changed" | "removed" | "restored"; added: number; removed: number; created_at: string; run_id: number; page: PageRef; diff?: DiffLine[] };
export type Change = { entry_id: number; change: "added" | "modified" | "removed"; title: string; category: string; source_url: string | null; diff: DiffLine[]; added: number; removed: number; meta: string[] };
export type Item = { entry_id: number; title: string; content: string; category_id: number | null; category: string; color: string; secondary: string[]; labels: string[]; source_url: string | null; source_title: string | null; manual_edit: boolean };
export type Version = { id: number; number: number; note: string; created_by: string; created_at: string; stats: { added?: number; modified?: number; removed?: number; total?: number }; items?: Item[]; changes?: Change[]; categories?: Category[] };
export type Overview = {
  chatbot: { key: string; name: string; description: string };
  pages: { active: number; removed: number; skipped: number; error: number };
  entries: Record<EntryStatus, number>; waiting: number; live: number; sources: number;
  active_run: Run | null; last_run: Run | null; runs: Run[]; published: Version | null;
  unpublished: { added: number; modified: number; removed: number }; unpublished_total: number;
  recent: PageEvent[];
  document: { gdoc_url: string | null; synced_version: number | null };
};
