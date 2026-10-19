export interface AgentMeta {
  /** Short brand label, e.g. "TTU Online". */
  label: string;
  /** Name shown as the assistant's identity. */
  assistantName: string;
  /** One-line description under the welcome heading. */
  tagline: string;
  /** Starter questions shown on an empty conversation. */
  suggestions: { title: string; prompt: string }[];
}

const AGENT_META: Record<string, AgentMeta> = {
  "ttu-online": {
    label: "TTU Online",
    assistantName: "TTU Online Assistant",
    tagline:
      "Ask about online programs, admissions, tuition, transfer credits, and student support at Texas Tech.",
    suggestions: [
      { title: "Browse programs", prompt: "List all online bachelor's degree programs" },
      { title: "Apply", prompt: "How do I apply to TTU Online?" },
      { title: "Tuition & aid", prompt: "How much does tuition cost and what financial aid is available?" },
      { title: "Transfer credits", prompt: "How do transfer credits work?" },
    ],
  },
  k12: {
    label: "TTU K-12",
    assistantName: "TTU K-12 Assistant",
    tagline:
      "Ask about enrollment, courses, Credit by Exam, grades, transcripts, and support at Texas Tech K-12.",
    suggestions: [
      { title: "Programs", prompt: "What is the difference between the tuition-free and tuition-paid programs?" },
      { title: "Credit by Exam", prompt: "How does Credit by Exam work?" },
      { title: "Grade appeals", prompt: "How do I appeal a final grade?" },
      { title: "Grade reports", prompt: "How do I view and print my student's grade report?" },
    ],
  },
};

export function getAgentMeta(agentId: string, displayName?: string): AgentMeta {
  const known = AGENT_META[agentId];
  if (known) return known;
  const label = displayName || agentId;
  return {
    label,
    assistantName: `${label} Assistant`,
    tagline: "Ask a question and I'll answer from the official knowledge base.",
    suggestions: [],
  };
}
