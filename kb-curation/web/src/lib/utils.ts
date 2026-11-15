import { clsx, type ClassValue } from "clsx";

export const cn = (...a: ClassValue[]) => clsx(a);

export function ago(iso?: string | null): string {
  if (!iso) return "never";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 0) return inTime(-s);
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} hr ago`;
  if (s < 86400 * 14) return `${Math.round(s / 86400)} d ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function inTime(s: number): string {
  if (s < 3600) return `in ${Math.max(1, Math.round(s / 60))} min`;
  if (s < 86400) return `in ${Math.round(s / 3600)} hr`;
  return `in ${Math.round(s / 86400)} d`;
}

export const dateTime = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" }) : "—";

export const shortDate = (iso: string) => new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });

export function duration(a?: string | null, b?: string | null): string {
  if (!a || !b) return "—";
  const s = Math.max(0, Math.round((new Date(b).getTime() - new Date(a).getTime()) / 1000));
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
}

export const shortUrl = (u: string) => u.replace(/^https?:\/\/(www\.)?/, "");
export const pathOf = (u: string) => { try { return new URL(u).pathname; } catch { return u; } };
export const plural = (n: number, w: string, p?: string) => `${n.toLocaleString()} ${n === 1 ? w : p ?? w + "s"}`;

/** Tailwind classes per category colour (kept literal so Tailwind sees them). */
export const DOT: Record<string, string> = {
  blue: "bg-blue-500", emerald: "bg-emerald-500", amber: "bg-amber-500", violet: "bg-violet-500", rose: "bg-rose-500", cyan: "bg-cyan-500",
  orange: "bg-orange-500", teal: "bg-teal-500", indigo: "bg-indigo-500", pink: "bg-pink-500", lime: "bg-lime-500", slate: "bg-slate-400",
};
