"use client";

import { useCallback, useRef, useState } from "react";
import {
  citationFromToolCall,
  postAskStream,
  type StreamCitation,
} from "@/lib/streaming";

export interface UseStreamingAskState {
  text: string;
  citations: StreamCitation[];
  isStreaming: boolean;
  error: string | null;
  chatId: string | null;
  send: (
    prompt: string,
    options?: { archive?: boolean; chatId?: string | null },
  ) => Promise<void>;
  cancel: () => void;
  reset: () => void;
}

/**
 * Hook that wraps `postAskStream` and exposes a friendly, render-loop-ready
 * state shape. Coalesces `agent.message` chunks into `text`, accumulates
 * `Read` tool calls as citations, and sets `isStreaming=false` on
 * `agent.done` / `agent.error`.
 */
export function useStreamingAsk(notebookId: string | null): UseStreamingAskState {
  const [text, setText] = useState("");
  const [citations, setCitations] = useState<StreamCitation[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [chatId, setChatId] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);

  const reset = useCallback(() => {
    setText("");
    setCitations([]);
    setError(null);
  }, []);

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setIsStreaming(false);
  }, []);

  const send = useCallback(
    async (
      prompt: string,
      options?: { archive?: boolean; chatId?: string | null },
    ) => {
      if (!notebookId) {
        setError("No notebook selected.");
        return;
      }
      setText("");
      setCitations([]);
      setError(null);
      setIsStreaming(true);

      const controller = new AbortController();
      abortRef.current = controller;

      const seenPaths = new Set<string>();
      const useChatId = options?.chatId ?? chatId ?? undefined;

      try {
        for await (const ev of postAskStream(
          notebookId,
          {
            prompt,
            archive: options?.archive,
            chat_id: useChatId,
          },
          controller.signal,
        )) {
          if (ev.event === "agent.tool_call") {
            const cite = citationFromToolCall(ev.data);
            if (cite && !seenPaths.has(cite.article_path)) {
              seenPaths.add(cite.article_path);
              setCitations((prev) => [...prev, cite]);
            }
          } else if (ev.event === "agent.message") {
            const chunk = (ev.data["text"] as string | undefined) ?? "";
            if (chunk) setText((prev) => prev + chunk);
          } else if (ev.event === "agent.done") {
            const summary = (ev.data["summary"] as string | undefined) ?? "";
            if (summary) setText(summary);
            const cid = ev.data["chat_id"] as string | undefined;
            if (cid) setChatId(cid);
            break;
          } else if (ev.event === "agent.error") {
            setError(
              (ev.data["message"] as string | undefined) ?? "Agent error",
            );
            break;
          }
        }
      } catch (err) {
        if ((err as Error).name !== "AbortError") {
          setError((err as Error).message);
        }
      } finally {
        setIsStreaming(false);
        abortRef.current = null;
      }
    },
    [notebookId, chatId],
  );

  return {
    text,
    citations,
    isStreaming,
    error,
    chatId,
    send,
    cancel,
    reset,
  };
}

/**
 * Display variant — renders streamed text with a blinking caret while
 * `isStreaming` is true. No props are required beyond the text itself,
 * keeping the dependency surface tiny.
 */
export function StreamingText({
  text,
  isStreaming,
  className,
}: {
  text: string;
  isStreaming: boolean;
  className?: string;
}) {
  return (
    <span className={className} data-testid="streaming-text">
      {text}
      {isStreaming && (
        <span
          className="inline-block w-[0.5ch] h-[1em] ml-[0.1ch] align-baseline animate-pulse bg-foreground/70"
          aria-hidden="true"
        />
      )}
    </span>
  );
}
