"use client";

import { useParams, useRouter } from "next/navigation";
import { useRef, useState, useCallback, useEffect, useMemo } from "react";
import { ArrowDown } from "lucide-react";
import { Sidebar } from "@/components/chat/sidebar";
import { ChatHeader } from "@/components/chat/header";
import { MessageBubble } from "@/components/chat/message";
import { InputArea } from "@/components/chat/input-area";
import { EmptyState } from "@/components/chat/empty-state";
import { ChatNavigator } from "@/components/chat/chat-navigator";
import { Conversation, Message } from "@/types/chat";
import { API_URL } from "@/lib/api";
import { getAgentMeta } from "@/lib/agents";

// ── Storage (per agent) ────────────────────────────────────────────────────────

const ONE_WEEK_MS = 7 * 24 * 60 * 60 * 1000;

function generateId() {
  return Math.random().toString(36).slice(2, 11);
}

const NEW_CHAT_TITLE = "New chat";
// Default title used by the previous UI; chats saved with it should still be
// auto-titled from their first question.
const LEGACY_NEW_CHAT_TITLE = "New conversation";
const SIDEBAR_KEY = "ttu_chat_sidebar_collapsed";

function freshConversation(): Conversation {
  return {
    id: generateId(),
    title: NEW_CHAT_TITLE,
    lastMessage: "",
    updatedAt: new Date(),
    messages: [],
  };
}

function storageKey(agentId: string) {
  return `ttu_chat_${agentId}`;
}

function loadFromStorage(agentId: string): { conversations: Conversation[]; activeId: string } | null {
  try {
    const raw = localStorage.getItem(storageKey(agentId));
    if (!raw) return null;
    const { conversations, activeId, savedAt } = JSON.parse(raw);
    if (Date.now() - savedAt > ONE_WEEK_MS) {
      localStorage.removeItem(storageKey(agentId));
      return null;
    }
    return {
      conversations: conversations.map((c: Conversation) => ({
        ...c,
        updatedAt: new Date(c.updatedAt),
        messages: c.messages.map((m: Message) => ({
          ...m,
          timestamp: new Date(m.timestamp),
          isStreaming: false,
        })),
      })),
      activeId,
    };
  } catch {
    return null;
  }
}

function saveToStorage(agentId: string, conversations: Conversation[], activeId: string) {
  try {
    localStorage.setItem(
      storageKey(agentId),
      JSON.stringify({ conversations, activeId, savedAt: Date.now() })
    );
  } catch { /* full or disabled */ }
}

// ── Page ───────────────────────────────────────────────────────────────────────

export default function AgentChatPage() {
  const params = useParams();
  const router = useRouter();
  const agentId = params.agent as string;

  const [displayName, setDisplayName] = useState(agentId);
  const [kbLastUpdated, setKbLastUpdated] = useState<string | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState("");
  const [hydrated, setHydrated] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try {
      return typeof window !== "undefined" && localStorage.getItem(SIDEBAR_KEY) === "1";
    } catch {
      return false;
    }
  });
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [showScrollDown, setShowScrollDown] = useState(false);
  const [activeQuestionId, setActiveQuestionId] = useState<string | null>(null);
  const streamingRef = useRef(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const nearBottomRef = useRef(true);

  const meta = getAgentMeta(agentId, displayName);

  const toggleSidebar = useCallback(() => {
    setSidebarCollapsed((v) => {
      try { localStorage.setItem(SIDEBAR_KEY, v ? "0" : "1"); } catch { /* ignore */ }
      return !v;
    });
  }, []);

  // Fetch agent display name + validate agent exists
  useEffect(() => {
    fetch(`${API_URL}/agents`)
      .then((r) => r.json())
      .then((agents: { id: string; display_name: string; kb_last_updated?: string | null }[]) => {
        const found = agents.find((a) => a.id === agentId);
        if (!found) {
          router.replace("/");
          return;
        }
        setDisplayName(found.display_name);
        if (found.kb_last_updated) {
          setKbLastUpdated(
            new Intl.DateTimeFormat(undefined, {
              dateStyle: "medium",
              timeStyle: "short",
            }).format(new Date(found.kb_last_updated))
          );
        }
      })
      .catch(() => { /* use agentId as fallback */ });
  }, [agentId, router]);

  // Hydrate from localStorage
  useEffect(() => {
    const saved = loadFromStorage(agentId);
    if (saved && saved.conversations.length > 0) {
      setConversations(saved.conversations);
      setActiveId(saved.activeId);
    } else {
      const conv = freshConversation();
      setConversations([conv]);
      setActiveId(conv.id);
    }
    setHydrated(true);
  }, [agentId]);

  // Persist on change
  useEffect(() => {
    if (hydrated && conversations.length > 0) {
      saveToStorage(agentId, conversations, activeId);
    }
  }, [agentId, conversations, activeId, hydrated]);

  const activeConversation = conversations.find((c) => c.id === activeId);
  const messages = useMemo(() => activeConversation?.messages ?? [], [activeConversation]);
  const lastMessage = messages[messages.length - 1];

  const questions = useMemo(
    () =>
      messages
        .filter((m) => m.role === "user")
        .map((m) => ({ id: m.id, label: m.content.length > 140 ? m.content.slice(0, 140) + "…" : m.content })),
    [messages]
  );

  // ── Scrolling ─────────────────────────────────────────────────────────────
  const updateScrollState = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    nearBottomRef.current = distance < 120;
    setShowScrollDown(distance > 240);

    // The current question is the last one whose top has scrolled past the
    // upper third of the viewport.
    const top = el.getBoundingClientRect().top;
    let current: string | null = null;
    el.querySelectorAll<HTMLElement>("[data-user-message]").forEach((node) => {
      if (node.getBoundingClientRect().top - top <= el.clientHeight * 0.35) {
        current = node.dataset.userMessage ?? null;
      }
    });
    setActiveQuestionId(current ?? questions[0]?.id ?? null);
  }, [questions]);

  const scrollToBottom = useCallback((behavior: ScrollBehavior = "smooth") => {
    const el = scrollRef.current;
    if (!el) return;
    nearBottomRef.current = true;
    el.scrollTo({ top: el.scrollHeight, behavior });
  }, []);

  // Jump to the latest message when switching conversations.
  useEffect(() => {
    requestAnimationFrame(() => {
      scrollToBottom("auto");
      updateScrollState();
    });
  }, [activeId, hydrated]); // eslint-disable-line react-hooks/exhaustive-deps

  // Follow the answer while it streams, unless the reader has scrolled up.
  useEffect(() => {
    if (nearBottomRef.current) scrollToBottom("auto");
    updateScrollState();
  }, [messages.length, lastMessage?.content]); // eslint-disable-line react-hooks/exhaustive-deps

  const jumpToQuestion = useCallback((id: string) => {
    const node = scrollRef.current?.querySelector(`#msg-${CSS.escape(id)}`);
    node?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  const handleSend = useCallback(
    async (text: string) => {
      if (isStreaming) return;

      const userMsg: Message = {
        id: generateId(),
        role: "user",
        content: text,
        timestamp: new Date(),
      };
      const assistantMsgId = generateId();
      const assistantMsg: Message = {
        id: assistantMsgId,
        role: "assistant",
        content: "",
        timestamp: new Date(),
        isStreaming: true,
      };
      const currentId = activeId;

      setConversations((prev) =>
        prev.map((c) =>
          c.id === currentId
            ? {
                ...c,
                messages: [...c.messages, userMsg, assistantMsg],
                lastMessage: text,
                updatedAt: new Date(),
                title:
                  c.messages.filter((m) => m.role === "user").length === 0 &&
                  (c.title === NEW_CHAT_TITLE || c.title === LEGACY_NEW_CHAT_TITLE)
                    ? text.slice(0, 48) + (text.length > 48 ? "…" : "")
                    : c.title,
              }
            : c
        )
      );

      setIsStreaming(true);
      streamingRef.current = true; //preventing me to send another msg while waiting for response
      nearBottomRef.current = true;

      try {
        // Build the full history from the conversation before adding the current message.
        const historyMessages = (activeConversation?.messages ?? [])
          .filter((m) => m.content.trim() && !m.isStreaming)
          .map((m) => ({ role: m.role as "user" | "assistant", content: m.content }));

        const res = await fetch(`${API_URL}/chat/${agentId}`, { //api call hit with msg and history
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            message: text,
            session_id: currentId,
            history: historyMessages,
          }),
        });

        if (!res.ok || !res.body) throw new Error("API error");
        const logId = res.headers.get("X-Log-Id") ?? undefined;
        const logDate = res.headers.get("X-Log-Date") ?? undefined;

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let accumulated = "";
        const IMAGES_MARKER = "\n__IMAGES__:";

        while (streamingRef.current) {
          const { done, value } = await reader.read();
          if (done) break;
          accumulated += decoder.decode(value, { stream: true });

          // Hide the images marker from the displayed text while streaming
          const displayText = accumulated.includes(IMAGES_MARKER)
            ? accumulated.split(IMAGES_MARKER)[0].trim()
            : accumulated;

          setConversations((prev) =>
            prev.map((c) =>
              c.id === currentId
                ? {
                    ...c,
                    messages: c.messages.map((m) =>
                      m.id === assistantMsgId
                        ? { ...m, content: displayText, isStreaming: true }
                        : m
                    ),
                  }
                : c
            )
          );
        }

        // Parse final accumulated text for images marker
        let finalContent = accumulated;
        let imageIds: string[] = [];
        if (accumulated.includes(IMAGES_MARKER)) {
          const [textPart, imgPart] = accumulated.split(IMAGES_MARKER);
          finalContent = textPart.trim();
          imageIds = imgPart.trim().split(",").filter(Boolean);
        }

        setConversations((prev) =>
          prev.map((c) =>
            c.id === currentId
              ? {
                  ...c,
                  messages: c.messages.map((m) =>
                    m.id === assistantMsgId
                      ? { ...m, content: finalContent, imageIds, isStreaming: false, logId, logDate }
                      : m
                  ),
                }
              : c
          )
        );
      } catch {
        setConversations((prev) =>
          prev.map((c) =>
            c.id === currentId
              ? {
                  ...c,
                  messages: c.messages.map((m) =>
                    m.id === assistantMsgId
                      ? {
                          ...m,
                          content: "Couldn't reach the assistant. Check your connection and try again.",
                          error: true,
                          isStreaming: false,
                        }
                      : m
                  ),
                }
              : c
          )
        );
      } finally {
        setIsStreaming(false);
        streamingRef.current = false;
      }
    },
    [agentId, activeId, activeConversation, isStreaming]
  );

  const handleStop = useCallback(() => {
    streamingRef.current = false;
    setIsStreaming(false);
    setConversations((prev) =>
      prev.map((c) =>
        c.id === activeId
          ? {
              ...c,
              messages: c.messages.map((m) =>
                m.isStreaming
                  ? { ...m, isStreaming: false, content: m.content || "_Response stopped._" }
                  : m
              ),
            }
          : c
      )
    );
  }, [activeId]);

  const handleNew = useCallback(() => {
    setMobileSidebarOpen(false);
    // Reuse the current chat if nothing has been asked in it yet.
    if (activeConversation && activeConversation.messages.length === 0) return;
    const conv = freshConversation();
    setConversations((prev) => [conv, ...prev]);
    setActiveId(conv.id);
  }, [activeConversation]);

  const handleSelect = useCallback((id: string) => {
    setActiveId(id);
    setMobileSidebarOpen(false);
  }, []);

  const handleDelete = useCallback(
    (id: string) => {
      setConversations((prev) => {
        const next = prev.filter((c) => c.id !== id);
        if (activeId === id) {
          const fallback = next.find((c) => c.messages.length > 0) ?? next[0];
          if (fallback) {
            setActiveId(fallback.id);
          } else {
            const conv = freshConversation();
            setActiveId(conv.id);
            return [conv];
          }
        }
        return next;
      });
    },
    [activeId]
  );

  const updateConversation = useCallback((id: string, patch: (c: Conversation) => Partial<Conversation>) => {
    setConversations((prev) => prev.map((c) => (c.id === id ? { ...c, ...patch(c) } : c)));
  }, []);

  const handleTogglePin = useCallback(
    (id: string) => updateConversation(id, (c) => ({ pinned: !c.pinned })),
    [updateConversation]
  );
  const handleToggleFavorite = useCallback(
    (id: string) => updateConversation(id, (c) => ({ favorite: !c.favorite })),
    [updateConversation]
  );
  const handleRename = useCallback(
    (id: string, title: string) => updateConversation(id, () => ({ title })),
    [updateConversation]
  );

  const handleFeedback = useCallback(
    (messageId: string, value: "up" | "down" | null) => {
      const target = activeConversation?.messages.find((m) => m.id === messageId);
      if (!target?.logId || !target.logDate) return;
      const convId = activeId;
      setConversations((prev) =>
        prev.map((c) =>
          c.id === convId
            ? {
                ...c,
                messages: c.messages.map((m) =>
                  m.id === messageId ? { ...m, feedback: value ?? undefined } : m
                ),
              }
            : c
        )
      );
      const body = JSON.stringify({
        log_id: target.logId,
        log_date: target.logDate,
        feedback_type: value === "up" ? "thumbs_up" : value === "down" ? "thumbs_down" : "cleared",
      });
      const send = () =>
        fetch(`${API_URL}/feedback`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body,
        });
      // The answer's log record is written as the stream finishes, so a very
      // quick click can arrive first (404) — retry once shortly after.
      send()
        .then((r) => (r.status === 404 ? new Promise((ok) => setTimeout(ok, 1500)).then(send) : r))
        .catch(() => { /* feedback is best-effort */ });
    },
    [activeConversation, activeId]
  );

  const handleRegenerate = useCallback(() => {
    if (isStreaming || !activeConversation) return;
    const messages = activeConversation.messages;
    const lastAssistant = messages[messages.length - 1];
    if (lastAssistant?.role !== "assistant") return;
    const lastUser = [...messages].reverse().find((m) => m.role === "user");
    if (!lastUser) return;
    setConversations((prev) =>
      prev.map((c) =>
        c.id === activeId
          ? { ...c, messages: c.messages.filter((m) => m.id !== lastAssistant.id) }
          : c
      )
    );
    setTimeout(() => handleSend(lastUser.content), 50);
  }, [activeId, activeConversation, isStreaming, handleSend]);

  if (!hydrated) return null;

  const isEmpty = messages.length === 0;

  return (
    <div className="flex h-dvh overflow-hidden bg-background">
      <Sidebar
        conversations={conversations}
        activeId={activeId}
        agentLabel={meta.label}
        onSelect={handleSelect}
        onNew={handleNew}
        onDelete={handleDelete}
        onTogglePin={handleTogglePin}
        onToggleFavorite={handleToggleFavorite}
        onRename={handleRename}
        collapsed={sidebarCollapsed}
        onToggle={toggleSidebar}
        mobileOpen={mobileSidebarOpen}
        onMobileClose={() => setMobileSidebarOpen(false)}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        <ChatHeader
          assistantName={meta.assistantName}
          conversationTitle={activeConversation?.title ?? NEW_CHAT_TITLE}
          onOpenSidebar={() => setMobileSidebarOpen(true)}
          onNewChat={handleNew}
        />

        <div className="relative min-h-0 flex-1">
          <div ref={scrollRef} onScroll={updateScrollState} className="thin-scroll h-full overflow-y-auto">
            {isEmpty ? (
              <EmptyState meta={meta} onSuggestion={handleSend} />
            ) : (
              <div className="mx-auto max-w-3xl py-6">
                {messages.map((msg, i) => {
                  const isLast = i === messages.length - 1;
                  return (
                    <MessageBubble
                      key={msg.id}
                      message={msg}
                      isLast={isLast && msg.role === "assistant"}
                      onRegenerate={
                        isLast && msg.role === "assistant" && !msg.isStreaming ? handleRegenerate : undefined
                      }
                      onFeedback={handleFeedback}
                    />
                  );
                })}
              </div>
            )}
          </div>

          <ChatNavigator items={questions} activeId={activeQuestionId} onJump={jumpToQuestion} />

          {showScrollDown && (
            <button
              type="button"
              onClick={() => scrollToBottom()}
              aria-label="Scroll to latest message"
              className="absolute bottom-3 left-1/2 inline-flex h-9 w-9 -translate-x-1/2 items-center justify-center rounded-full border border-border bg-background text-foreground shadow-md transition hover:bg-accent animate-in fade-in zoom-in-95"
            >
              <ArrowDown className="h-4 w-4" />
            </button>
          )}
        </div>

        <div className="mx-auto w-full max-w-3xl">
          <InputArea
            onSend={handleSend}
            disabled={isStreaming}
            isStreaming={isStreaming}
            onStop={handleStop}
            kbLastUpdated={kbLastUpdated}
            placeholder={`Message ${meta.assistantName}`}
            focusKey={activeId}
          />
        </div>
      </main>
    </div>
  );
}
