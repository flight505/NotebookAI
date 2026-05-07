"use client";

import {
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageSquarePlus, Trash2 } from "lucide-react";
import { motion } from "framer-motion";
import { AlertTriangle } from "lucide-react";
import { API_BASE_URL, ask, http } from "@/lib/api";
import { useNotebookStore } from "@/store/useNotebook";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { ChatComposer } from "@/components/ChatComposer";
import { ChatTranscript, type TranscriptMessage } from "@/components/ChatTranscript";
import { CitationChip } from "@/components/CitationChip";
import { useStreamingAsk } from "@/components/StreamingText";
import { cn } from "@/lib/cn";

export const dynamic = "force-dynamic";

interface ChatSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  path: string;
}

interface ChatFull {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  notebook_id: string;
  model: string | null;
  messages: TranscriptMessage[];
}

async function fetchChats(notebookId: string): Promise<ChatSummary[]> {
  const { data } = await http.get<ChatSummary[]>(
    `/notebooks/${notebookId}/chats`,
  );
  return data;
}

async function fetchChat(
  notebookId: string,
  chatId: string,
): Promise<ChatFull> {
  const { data } = await http.get<ChatFull>(
    `/notebooks/${notebookId}/chats/${chatId}`,
  );
  return data;
}

async function deleteChat(notebookId: string, chatId: string): Promise<void> {
  await http.delete(`/notebooks/${notebookId}/chats/${chatId}`);
}

export default function AskPage() {
  return (
    <Suspense fallback={<AskSkeleton />}>
      <AskShell />
    </Suspense>
  );
}

function AskShell() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const notebookId = useNotebookStore((s) => s.currentNotebookId);
  const chatParam = searchParams.get("chat");

  const chatsQuery = useQuery({
    queryKey: ["chats", notebookId],
    queryFn: () =>
      notebookId ? fetchChats(notebookId) : Promise.resolve([] as ChatSummary[]),
    enabled: !!notebookId,
  });

  const statusQuery = useQuery({
    queryKey: ["agent-status", notebookId],
    queryFn: async () => {
      if (!notebookId) return null;
      const { data } = await http.get<{
        agent_status?: { available: boolean; reason: string | null };
      }>(`/notebooks/${notebookId}`);
      return data.agent_status ?? null;
    },
    enabled: !!notebookId,
  });
  const isDegraded = statusQuery.data
    ? statusQuery.data.available === false
    : false;

  const chatQuery = useQuery({
    queryKey: ["chat", notebookId, chatParam],
    queryFn: () =>
      notebookId && chatParam
        ? fetchChat(notebookId, chatParam)
        : Promise.resolve(null as ChatFull | null),
    enabled: !!notebookId && !!chatParam,
  });

  const stream = useStreamingAsk(notebookId);

  // Mirror chat_id from the streaming hook into the URL once it becomes
  // known (first turn of a new chat).
  useEffect(() => {
    if (stream.chatId && stream.chatId !== chatParam) {
      const params = new URLSearchParams(searchParams.toString());
      params.set("chat", stream.chatId);
      router.replace(`/ask?${params.toString()}`);
      queryClient.invalidateQueries({ queryKey: ["chats", notebookId] });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stream.chatId]);

  // After streaming completes successfully, refresh both the chat list
  // and the active chat so persisted citations surface.
  useEffect(() => {
    if (!stream.isStreaming && stream.text && !stream.error) {
      queryClient.invalidateQueries({ queryKey: ["chats", notebookId] });
      if (stream.chatId) {
        queryClient.invalidateQueries({
          queryKey: ["chat", notebookId, stream.chatId],
        });
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stream.isStreaming]);

  const handleSend = useCallback(
    (prompt: string) => {
      stream.send(prompt, { chatId: chatParam ?? null });
    },
    [stream, chatParam],
  );

  const handleArchive = useCallback(
    async (message: TranscriptMessage) => {
      if (!notebookId) return;
      // Re-ask the original prompt with archive=true.
      const userMsg = chatQuery.data?.messages
        .filter((m) => m.role === "user")
        .pop();
      const prompt = userMsg?.text ?? message.text;
      try {
        await ask(notebookId, { query: prompt, chat_id: chatParam ?? undefined });
      } catch {
        /* surfaced via global error toast in api layer */
      }
    },
    [notebookId, chatQuery.data, chatParam],
  );

  const startNewChat = () => {
    stream.reset();
    router.push(`/ask`);
  };

  const handleDelete = async (chatId: string) => {
    if (!notebookId) return;
    await deleteChat(notebookId, chatId);
    queryClient.invalidateQueries({ queryKey: ["chats", notebookId] });
    if (chatId === chatParam) router.replace("/ask");
  };

  const messages = useMemo<TranscriptMessage[]>(() => {
    return chatQuery.data?.messages ?? [];
  }, [chatQuery.data]);

  // Right-rail sources: prefer the streaming citations while in flight,
  // otherwise the citations on the most recent assistant message.
  const sourceCitations = useMemo(() => {
    if (stream.isStreaming || stream.citations.length > 0) {
      return stream.citations;
    }
    const lastAssistant = [...messages]
      .reverse()
      .find((m) => m.role === "assistant");
    return lastAssistant?.citations ?? [];
  }, [stream.isStreaming, stream.citations, messages]);

  if (!notebookId) {
    return (
      <div className="flex items-center justify-center h-full p-10">
        <p className="text-sm text-muted-foreground">
          Pick a notebook from the switcher to start a chat.
        </p>
      </div>
    );
  }

  return (
    <div className="grid h-full grid-cols-[260px_1fr_280px]">
      {/* Left rail: chat list */}
      <aside className="border-r border-border bg-card/40 flex flex-col">
        <div className="flex items-center justify-between p-3 border-b border-border">
          <h2 className="text-sm font-semibold">Chats</h2>
          <Button size="sm" variant="ghost" onClick={startNewChat}>
            <MessageSquarePlus className="w-4 h-4" />
            New
          </Button>
        </div>
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {chatsQuery.isLoading && (
            <>
              <Skeleton className="h-9" />
              <Skeleton className="h-9" />
            </>
          )}
          {chatsQuery.data?.length === 0 && (
            <p className="text-xs text-muted-foreground p-2">No chats yet.</p>
          )}
          {chatsQuery.data?.map((c) => {
            const active = c.id === chatParam;
            return (
              <div
                key={c.id}
                className={cn(
                  "group flex items-start gap-2 px-2 py-1.5 rounded-md cursor-pointer",
                  active
                    ? "bg-card border border-border"
                    : "hover:bg-muted",
                )}
                onClick={() => router.push(`/ask?chat=${c.id}`)}
              >
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate">{c.title}</p>
                  <p className="text-[11px] text-muted-foreground">
                    {c.message_count} message
                    {c.message_count === 1 ? "" : "s"}
                  </p>
                </div>
                <button
                  className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-foreground"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleDelete(c.id);
                  }}
                  aria-label={`Delete ${c.title}`}
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            );
          })}
        </div>
      </aside>

      {/* Center: transcript + composer */}
      <main className="flex flex-col min-w-0">
        {isDegraded && (
          <div
            role="status"
            data-testid="degraded-banner"
            className="mx-4 mt-3 flex items-start gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-xs text-amber-800 dark:text-amber-200"
          >
            <AlertTriangle className="h-4 w-4 shrink-0 mt-[1px]" />
            <div>
              <p className="font-medium">Wiki-only mode</p>
              <p className="text-amber-800/80 dark:text-amber-200/80">
                Claude is unavailable. Answers below are retrieved wiki
                passages — no synthesis. Citations still work the same way.
              </p>
            </div>
          </div>
        )}
        <div className="flex-1 overflow-y-auto">
          {chatQuery.isLoading && chatParam ? (
            <div className="p-4 space-y-3">
              <Skeleton className="h-16" />
              <Skeleton className="h-24" />
            </div>
          ) : (
            <ChatTranscript
              messages={messages}
              streaming={stream}
              onArchive={handleArchive}
            />
          )}
          {stream.error && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="mx-4 my-2 p-3 rounded-md border border-red-500/30 bg-red-500/10 text-xs"
            >
              {stream.error}
            </motion.div>
          )}
        </div>
        <div className="p-3 border-t border-border bg-background sticky bottom-0">
          <ChatComposer
            onSubmit={handleSend}
            onCancel={stream.cancel}
            isStreaming={stream.isStreaming}
          />
        </div>
      </main>

      {/* Right rail: sources */}
      <aside className="border-l border-border bg-card/40 flex flex-col">
        <div className="p-3 border-b border-border">
          <h2 className="text-sm font-semibold">Sources</h2>
          <p className="text-[11px] text-muted-foreground mt-0.5">
            Articles cited in the latest answer.
          </p>
        </div>
        <div className="flex-1 overflow-y-auto p-3">
          {sourceCitations.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              Citations appear here as the agent reads the wiki.
            </p>
          ) : (
            <div className="flex flex-col gap-2">
              {sourceCitations.map((c) => (
                <CitationChip
                  key={c.article_path}
                  articlePath={c.article_path}
                  quote={c.quote}
                  score={c.score}
                  className="self-start"
                />
              ))}
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}

function AskSkeleton() {
  return (
    <div className="grid h-full grid-cols-[260px_1fr_280px]">
      <div className="border-r border-border p-3 space-y-2">
        <Skeleton className="h-8" />
        <Skeleton className="h-9" />
        <Skeleton className="h-9" />
      </div>
      <div className="p-4 space-y-3">
        <Skeleton className="h-16" />
        <Skeleton className="h-24" />
      </div>
      <div className="border-l border-border p-3">
        <Skeleton className="h-6" />
      </div>
    </div>
  );
}

// Allow API_BASE_URL/ask helper to be tree-shaken if unused.
void API_BASE_URL;
