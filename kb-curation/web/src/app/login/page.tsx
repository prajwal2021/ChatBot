"use client";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import { Button, Card, inputCls, Label } from "@/components/ui";

export default function LoginPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await api("/api/login", { body: { name, password } });
      router.replace("/");
    } catch (e) {
      setErr((e as Error).message === "Failed to fetch" ? "Cannot reach the KB Curation server." : (e as Error).message);
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-sm px-4 pt-32">
      <h1 className="mb-1 text-lg font-semibold">KB Curation</h1>
      <p className="mb-5 text-sm text-muted">Sign in to review and publish.</p>
      <Card className="p-5">
        <form onSubmit={submit}>
          <Label>Name</Label>
          <input autoFocus autoComplete="username" className={inputCls} value={name} onChange={(e) => setName(e.target.value)} />
          <div className="h-3" />
          <Label>Password</Label>
          <input type="password" autoComplete="current-password" className={inputCls} value={password} onChange={(e) => setPassword(e.target.value)} />
          {err && <p className="mt-3 text-sm text-red-600">{err}</p>}
          <Button type="submit" variant="primary" busy={busy} disabled={!name.trim() || !password} className="mt-4 w-full">Sign in</Button>
        </form>
      </Card>
    </div>
  );
}
