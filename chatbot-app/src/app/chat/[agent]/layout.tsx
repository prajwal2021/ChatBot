import type { Metadata } from "next";

const AGENT_TITLES: Record<string, string> = {
  "ttu-online": "Online+ Chatbot",
  "k12": "K12 Chatbot",
};

export async function generateMetadata({
  params,
}: {
  params: Promise<{ agent: string }>;
}): Promise<Metadata> {
  const { agent } = await params;
  return {
    title: AGENT_TITLES[agent] ?? "ElevenLabs ChatBot",
  };
}

export default function AgentLayout({ children }: { children: React.ReactNode }) {
  return children;
}
