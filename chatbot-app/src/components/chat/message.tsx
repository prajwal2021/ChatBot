"use client";

import { memo, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { AlertCircle, Check, Copy, RotateCcw, ThumbsDown, ThumbsUp } from "lucide-react";
import { cn } from "@/lib/utils";
import { Message } from "@/types/chat";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { BrandMark } from "@/components/chat/brand-mark";
import { API_URL } from "@/lib/api";

interface MessageBubbleProps {
  message: Message;
  isLast?: boolean;
  onRegenerate?: () => void;
  onFeedback?: (messageId: string, value: "up" | "down" | null) => void;
}

const markdownComponents: Components = {
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  ),
  table: ({ children }) => (
    <div className="table-wrap">
      <table>{children}</table>
    </div>
  ),
};

const Markdown = memo(function Markdown({ content }: { content: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
      {content}
    </ReactMarkdown>
  );
});

export function MessageBubble({ message, isLast, onRegenerate, onFeedback }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const [copied, setCopied] = useState(false);
  const liked = message.feedback ?? null;
  const canRate = Boolean(message.logId && onFeedback);
  const rate = (value: "up" | "down") => onFeedback?.(message.id, liked === value ? null : value);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      /* clipboard unavailable (e.g. insecure context) */
    }
  };

  const time = new Date(message.timestamp).toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  });

  if (isUser) {
    return (
      <div
        id={`msg-${message.id}`}
        data-user-message={message.id}
        className="group flex scroll-mt-6 flex-col items-end px-4 py-3 animate-in fade-in slide-in-from-bottom-1 duration-300 sm:px-6"
      >
        <div className="max-w-[85%] whitespace-pre-wrap break-words rounded-3xl bg-secondary px-4 py-2.5 text-[0.9375rem] leading-relaxed text-secondary-foreground sm:max-w-[75%]">
          {message.content}
        </div>
        <div className="mt-1 flex items-center gap-0.5 pr-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
          <span className="mr-1 text-[11px] text-muted-foreground">{time}</span>
          <ActionButton label={copied ? "Copied" : "Copy"} onClick={handleCopy}>
            {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
          </ActionButton>
        </div>
      </div>
    );
  }

  const thinking = message.isStreaming && !message.content;

  return (
    <div className="group flex gap-3 px-4 py-3 animate-in fade-in duration-300 sm:gap-4 sm:px-6">
      <BrandMark size="sm" className="mt-0.5" />

      <div className="min-w-0 flex-1 pt-0.5">
        {thinking ? (
          <div className="flex h-7 items-center gap-1.5 text-sm text-muted-foreground" aria-live="polite">
            <span>Thinking</span>
            <span className="flex gap-1">
              <span className="thinking-dot h-1 w-1 rounded-full bg-current" />
              <span className="thinking-dot h-1 w-1 rounded-full bg-current [animation-delay:150ms]" />
              <span className="thinking-dot h-1 w-1 rounded-full bg-current [animation-delay:300ms]" />
            </span>
          </div>
        ) : message.error ? (
          <div className="flex items-start gap-2.5 rounded-xl border border-destructive/25 bg-destructive/5 px-4 py-3 text-sm text-foreground">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
            <span>{message.content}</span>
          </div>
        ) : (
          <div className="chat-prose">
            <Markdown content={message.content} />
          </div>
        )}

        {/* Inline images (assistant only) */}
        {!message.isStreaming && message.imageIds && message.imageIds.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {message.imageIds.map((id) => (
              <img
                key={id}
                src={`${API_URL}/static/images/${id}`}
                alt="Knowledge base illustration"
                className="max-w-xs rounded-xl border border-border object-contain shadow-sm"
                onError={(e) => {
                  (e.target as HTMLImageElement).style.display = "none";
                }}
              />
            ))}
          </div>
        )}

        {!message.isStreaming && (
          <div
            className={cn(
              "-ml-1.5 mt-2 flex items-center gap-0.5 transition-opacity",
              isLast ? "opacity-100" : "opacity-0 group-hover:opacity-100 focus-within:opacity-100"
            )}
          >
            {!message.error && (
              <>
                <ActionButton label={copied ? "Copied" : "Copy"} onClick={handleCopy}>
                  {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                </ActionButton>
                {canRate && (
                  <>
                    <ActionButton label="Good response" onClick={() => rate("up")} active={liked === "up"}>
                      <ThumbsUp className={cn("h-3.5 w-3.5", liked === "up" && "fill-current")} />
                    </ActionButton>
                    <ActionButton label="Bad response" onClick={() => rate("down")} active={liked === "down"}>
                      <ThumbsDown className={cn("h-3.5 w-3.5", liked === "down" && "fill-current")} />
                    </ActionButton>
                  </>
                )}
              </>
            )}
            {onRegenerate && (
              <ActionButton label={message.error ? "Try again" : "Regenerate"} onClick={onRegenerate}>
                <RotateCcw className="h-3.5 w-3.5" />
              </ActionButton>
            )}
            <span className="ml-1.5 text-[11px] text-muted-foreground">{time}</span>
          </div>
        )}
      </div>
    </div>
  );
}

function ActionButton({
  label,
  onClick,
  active,
  children,
}: {
  label: string;
  onClick: () => void;
  active?: boolean;
  children: React.ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger
        onClick={onClick}
        aria-label={label}
        aria-pressed={active}
        className={cn(
          "inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground",
          active && "bg-accent text-foreground"
        )}
      >
        {children}
      </TooltipTrigger>
      <TooltipContent side="bottom" className="text-xs">
        {label}
      </TooltipContent>
    </Tooltip>
  );
}
