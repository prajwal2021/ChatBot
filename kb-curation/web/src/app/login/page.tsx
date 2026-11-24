"use client";
import { AlertCircle, ArrowRight, BookOpenCheck, Eye, EyeOff, GitCompareArrows, Link2, ShieldCheck } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent, type KeyboardEvent } from "react";
import { API } from "@/lib/api";
import { Button, inputCls, Label } from "@/components/ui";
import { cn } from "@/lib/utils";

const POINTS = [
  { icon: Link2, title: "Watched at the source", text: "Each ServiceNow category is linked to the TTU pages its articles come from." },
  { icon: GitCompareArrows, title: "Changes proposed for you", text: "When a page changes, the AI drafts the exact edits for the affected articles." },
  { icon: ShieldCheck, title: "Nothing goes live unreviewed", text: "A reviewer approves every change before it reaches the chatbot." },
];

export default function LoginPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [caps, setCaps] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // already signed in (e.g. the login page was bookmarked): go straight in
  useEffect(() => {
    fetch(`${API}/api/me`, { credentials: "include", cache: "no-store" })
      .then((r) => { if (r.ok) router.replace("/"); })
      .catch(() => {});
  }, [router]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      // called directly (not through api()) so a wrong password shows here instead of reloading the page
      const r = await fetch(`${API}/api/login`, {
        method: "POST", credentials: "include", cache: "no-store",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: name.trim(), password }),
      });
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        throw new Error(r.status === 401 ? "That name and password don't match. Check both and try again." : j.detail || `Sign-in failed (${r.status})`);
      }
      router.replace("/");
    } catch (e) {
      const m = (e as Error).message;
      setErr(m === "Failed to fetch" ? "Can't reach the KB Curation server. Check that you are on the TTU network or VPN." : m);
      setBusy(false);
    }
  };
  const capsCheck = (e: KeyboardEvent<HTMLInputElement>) => setCaps(e.getModifierState?.("CapsLock") ?? false);

  return (
    <div className="flex min-h-full flex-col bg-white lg:flex-row">
      <aside className="relative flex flex-col justify-between overflow-hidden bg-ink px-8 py-10 text-white lg:w-[46%] lg:px-14 lg:py-14">
        <div aria-hidden className="pointer-events-none absolute -right-32 -top-32 size-[420px] rounded-full bg-white/[0.04]" />
        <div aria-hidden className="pointer-events-none absolute -bottom-40 -left-24 size-[360px] rounded-full bg-white/[0.03]" />
        <div className="relative flex items-center gap-2.5">
          <div className="flex size-9 items-center justify-center rounded-xl bg-white text-ink"><BookOpenCheck className="size-5" /></div>
          <span className="text-lg font-semibold tracking-tight">KB Curation</span>
        </div>
        <div className="relative my-10 max-w-md lg:my-0">
          <h1 className="text-[28px] font-semibold leading-tight tracking-tight lg:text-[34px]">Keep the chatbot&apos;s knowledge accurate and up to date.</h1>
          <p className="mt-3 text-[15px] text-white/60">For the TTU Online and TTU K-12 chatbots.</p>
          <ul className="mt-8 hidden space-y-5 sm:block">
            {POINTS.map((p) => (
              <li key={p.title} className="flex gap-3.5">
                <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-white/10"><p.icon className="size-4" /></span>
                <span>
                  <span className="block text-[14px] font-medium">{p.title}</span>
                  <span className="block text-[13px] leading-relaxed text-white/55">{p.text}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
        <p className="relative hidden text-xs text-white/40 lg:block">Texas Tech University · Internal tool for authorized reviewers</p>
      </aside>

      <main className="flex flex-1 items-center justify-center px-6 py-12 lg:px-16">
        <div className="w-full max-w-[380px]">
          <h2 className="text-[22px] font-semibold tracking-tight">Sign in</h2>
          <p className="mt-1 text-sm text-muted">Use the name and password your administrator set up for you.</p>

          <form onSubmit={submit} className="mt-7 space-y-4" noValidate>
            <div>
              <Label>Name</Label>
              <input id="name" autoFocus autoComplete="username" placeholder="e.g. Prajwal" className={cn(inputCls, "h-10")}
                value={name} onChange={(e) => { setName(e.target.value); setErr(null); }} />
            </div>
            <div>
              <Label>Password</Label>
              <div className="relative">
                <input id="password" type={show ? "text" : "password"} autoComplete="current-password" className={cn(inputCls, "h-10 pr-10")}
                  value={password} onChange={(e) => { setPassword(e.target.value); setErr(null); }} onKeyUp={capsCheck} onKeyDown={capsCheck} />
                <button type="button" onClick={() => setShow((v) => !v)} aria-label={show ? "Hide password" : "Show password"}
                  className="absolute inset-y-0 right-0 flex w-10 items-center justify-center text-neutral-400 hover:text-ink">
                  {show ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                </button>
              </div>
              {caps && <p className="mt-1.5 text-xs text-amber-700">Caps Lock is on.</p>}
            </div>

            {err && (
              <div role="alert" className="flex gap-2 rounded-xl border border-red-200 bg-red-50 px-3 py-2.5 text-[13px] text-red-700">
                <AlertCircle className="mt-0.5 size-4 shrink-0" /><span>{err}</span>
              </div>
            )}

            <Button type="submit" variant="primary" busy={busy} disabled={!name.trim() || !password} className="h-10 w-full">
              Sign in {!busy && <ArrowRight className="size-4" />}
            </Button>
          </form>

          <p className="mt-6 border-t border-line pt-4 text-xs leading-relaxed text-muted">
            No account, or forgot your password? Ask your KB Curation administrator. They can create an account or reset a password for you.
          </p>
        </div>
      </main>
    </div>
  );
}
