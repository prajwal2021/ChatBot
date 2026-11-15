import { Fragment, type ReactNode } from "react";
import { cn } from "@/lib/utils";

type Block = { type: "p" | "bullet" | "step"; text: string; indent: number } | { type: "table"; rows: string[][] };

function blocks(content: string): Block[] {
  const out: Block[] = [];
  const lines = content.split("\n");
  for (let i = 0; i < lines.length; ) {
    if (lines[i].includes(" | ")) {
      const rows: string[][] = [];
      while (i < lines.length && lines[i].includes(" | ")) rows.push(lines[i++].split(" | ").map((c) => c.trim()));
      if (rows.length > 1 && new Set(rows.map((r) => r.length)).size === 1) out.push({ type: "table", rows });
      else rows.forEach((r) => out.push({ type: "p", text: r.join(" | "), indent: 0 }));
      continue;
    }
    const ln = lines[i++];
    const indent = Math.floor((ln.length - ln.trimStart().length) / 2);
    const s = ln.trim();
    if (!s) continue;
    if (s.startsWith("- ")) out.push({ type: "bullet", text: s.slice(2), indent });
    else if (/^\d+\. /.test(s)) out.push({ type: "step", text: s, indent });
    else out.push({ type: "p", text: s, indent: 0 });
  }
  return out;
}

function inline(text: string): ReactNode {
  const parts: ReactNode[] = [];
  const rx = /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g;
  let pos = 0, m: RegExpExecArray | null;
  while ((m = rx.exec(text))) {
    if (m.index > pos) parts.push(text.slice(pos, m.index));
    parts.push(<a key={m.index} href={m[2]} target="_blank" rel="noreferrer" className="text-blue-700 underline decoration-blue-200 underline-offset-2 hover:decoration-blue-600">{m[1]}</a>);
    pos = m.index + m[0].length;
  }
  if (pos < text.length) parts.push(text.slice(pos));
  return parts.map((p, i) => <Fragment key={i}>{p}</Fragment>);
}

/** Renders entry content (sentences, bullets, steps, tables, links) the way it will read in the document. */
export function Rich({ content, className }: { content: string; className?: string }) {
  return (
    <div className={cn("space-y-2 text-[14px] leading-relaxed text-neutral-800", className)}>
      {blocks(content).map((b, i) => {
        if (b.type === "table")
          return (
            <div key={i} className="overflow-x-auto rounded-lg border border-line">
              <table className="w-full text-left text-[13px]">
                <tbody>
                  {b.rows.map((r, ri) => (
                    <tr key={ri} className={cn("border-b border-line last:border-0", ri === 0 && "bg-subtle font-medium")}>
                      {r.map((c, ci) => <td key={ci} className="px-3 py-1.5 align-top">{inline(c)}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        if (b.type === "bullet")
          return (
            <div key={i} className="flex gap-2" style={{ paddingLeft: 4 + b.indent * 18 }}>
              <span className="mt-[9px] size-1 shrink-0 rounded-full bg-neutral-400" />
              <span>{inline(b.text)}</span>
            </div>
          );
        if (b.type === "step") {
          const [, n, rest] = b.text.match(/^(\d+)\. (.*)$/) ?? [];
          return (
            <div key={i} className="flex gap-2" style={{ paddingLeft: b.indent * 18 }}>
              <span className="w-5 shrink-0 text-right font-medium tabular-nums text-neutral-500">{n}.</span>
              <span>{inline(rest ?? b.text)}</span>
            </div>
          );
        }
        return <p key={i}>{inline(b.text)}</p>;
      })}
    </div>
  );
}
