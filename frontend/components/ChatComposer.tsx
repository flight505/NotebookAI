"use client";

import {
  KeyboardEvent,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { Send, Square } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/cn";

interface ChatComposerProps {
  onSubmit: (text: string) => void;
  onCancel?: () => void;
  isStreaming: boolean;
  disabled?: boolean;
  placeholder?: string;
  className?: string;
}

const MAX_ROWS = 8;
const LINE_HEIGHT_PX = 22;

export function ChatComposer({
  onSubmit,
  onCancel,
  isStreaming,
  disabled,
  placeholder = "Ask anything about this notebook…",
  className,
}: ChatComposerProps) {
  const [value, setValue] = useState("");
  const ref = useRef<HTMLTextAreaElement | null>(null);

  const autoGrow = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    const max = LINE_HEIGHT_PX * MAX_ROWS + 24; // padding allowance
    const target = Math.min(el.scrollHeight, max);
    el.style.height = `${target}px`;
  }, []);

  useLayoutEffect(autoGrow, [autoGrow, value]);

  // Refocus when an in-flight stream completes.
  useEffect(() => {
    if (!isStreaming && !disabled) {
      ref.current?.focus();
    }
  }, [isStreaming, disabled]);

  const submit = () => {
    const trimmed = value.trim();
    if (!trimmed || isStreaming || disabled) return;
    onSubmit(trimmed);
    setValue("");
  };

  const handleKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      submit();
      return;
    }
    if (e.key === "Tab" && !e.shiftKey) {
      e.preventDefault();
      const el = e.currentTarget;
      const start = el.selectionStart ?? 0;
      const end = el.selectionEnd ?? 0;
      const next = value.slice(0, start) + "\t" + value.slice(end);
      setValue(next);
      // Move caret past the inserted tab on the next tick.
      requestAnimationFrame(() => {
        if (ref.current) {
          ref.current.selectionStart = ref.current.selectionEnd = start + 1;
        }
      });
    }
    // Plain Enter inserts a newline (default).
  };

  return (
    <div
      className={cn(
        "rounded-xl border border-border bg-card shadow-sm",
        "focus-within:border-foreground/30 transition-colors",
        className,
      )}
    >
      <textarea
        ref={ref}
        value={value}
        disabled={disabled || isStreaming}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKey}
        placeholder={placeholder}
        rows={1}
        data-testid="chat-composer-textarea"
        className={cn(
          "w-full resize-none bg-transparent px-4 py-3",
          "text-sm leading-[22px] text-foreground placeholder:text-muted-foreground",
          "outline-none",
        )}
        aria-label="Ask the agent"
      />
      <div className="flex items-center justify-between px-3 pb-2">
        <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
          {value.length > 0 ? `${value.length} chars` : "⌘+Enter to send"}
        </span>
        {isStreaming ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={onCancel}
            aria-label="Stop streaming"
          >
            <Square className="w-3.5 h-3.5" />
            Stop
          </Button>
        ) : (
          <Button
            type="button"
            size="sm"
            onClick={submit}
            disabled={!value.trim() || disabled}
            aria-label="Send message"
            data-testid="chat-composer-send"
          >
            <Send className="w-3.5 h-3.5" />
            Send
          </Button>
        )}
      </div>
    </div>
  );
}
