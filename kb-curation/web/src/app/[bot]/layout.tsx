"use client";
import { Shell } from "@/components/shell";
import { ToastProvider } from "@/components/ui";

export default function BotLayout({ children }: { children: React.ReactNode }) {
  return (
    <ToastProvider>
      <Shell>{children}</Shell>
    </ToastProvider>
  );
}
