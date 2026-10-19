"use client";

import { useEffect, useRef, useState, KeyboardEvent } from "react";
import { ArrowUp, Square } from "lucide-react";
import { cn } from "@/lib/utils";

interface InputAreaProps {
  onSend: (message: string) => void;
  disabled?: boolean;
  isStreaming?: boolean;
  onStop?: () => void;
  kbLastUpdated?: string | null;
  placeholder?: string;
  /** Changes whenever the active conversation changes, to re-focus the box. */
  focusKey?: string;
}

const MAX_HEIGHT = 200;

export function InputArea({
  onSend,
  disabled,
  isStreaming,
  onStop,
  kbLastUpdated,
  placeholder = "Ask a question…",
  focusKey,
}: InputAreaProps) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    // Don't pop the on-screen keyboard open on touch devices.
    if (window.matchMedia("(pointer: fine)").matches) textareaRef.current?.focus();
  }, [focusKey]);

  const resize = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, MAX_HEIGHT) + "px";
  };

  const handleSend = () => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
    requestAnimationFrame(resize);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      handleSend();
    }
  };

  const canSend = value.trim().length > 0 && !disabled;

  return (
    <div className="px-3 pb-3 pt-2 sm:px-6 sm:pb-4">
      <div
        className={cn(
          "flex items-end gap-2 rounded-[1.6rem] border border-input bg-card py-2 pl-5 pr-2 shadow-sm transition-[box-shadow,border-color]",
          "focus-within:border-foreground/20 focus-within:shadow-md"
        )}
      >
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            resize();
          }}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          rows={1}
          aria-label="Message"
          className="thin-scroll max-h-[200px] min-h-[40px] flex-1 resize-none bg-transparent py-2 text-[0.9375rem] leading-relaxed text-foreground placeholder:text-muted-foreground focus:outline-none"
        />

        {isStreaming ? (
          <button
            type="button"
            onClick={onStop}
            aria-label="Stop generating"
            title="Stop generating"
            className="mb-0.5 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-foreground text-background transition-opacity hover:opacity-85"
          >
            <Square className="h-3 w-3 fill-current" />
          </button>
        ) : (
          <button
            type="button"
            onClick={handleSend}
            disabled={!canSend}
            aria-label="Send message"
            title="Send message"
            className={cn(
              "mb-0.5 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full transition-all",
              canSend
                ? "bg-primary text-primary-foreground shadow-sm hover:brightness-110"
                : "cursor-not-allowed bg-muted text-muted-foreground"
            )}
          >
            <ArrowUp className="h-[18px] w-[18px]" strokeWidth={2.25} />
          </button>
        )}
      </div>

      <p className="mt-2 px-2 text-center text-[11px] leading-snug text-muted-foreground">
        Answers come from official TTU information and can still contain mistakes. Please verify important details.
        {kbLastUpdated && <span className="whitespace-nowrap"> · Updated {kbLastUpdated}</span>}
      </p>
    </div>
  );
}
