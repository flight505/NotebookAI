"use client";

import { useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Loader2, Archive } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { CitationChip } from "@/components/CitationChip";
import { StreamingText } from "@/components/StreamingText";
import { cn } from "@/lib/cn";

export interface TranscriptCitation {
  article_path: string;
  quote?: string;
  score?: number | null;
}

export interface TranscriptMessage {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  citations?: TranscriptCitation[];
  created_at?: string;
  model?: string | null;
}

interface ChatTranscriptProps {
  messages: TranscriptMessage[];
  streaming?: {
    text: string;
    citations: TranscriptCitation[];
    isStreaming: boolean;
  };
  onArchive?: (message: TranscriptMessage) => void;
  className?: string;
}

export function ChatTranscript({
  messages,
  streaming,
  onArchive,
  className,
}: ChatTranscriptProps) {
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [
    messages.length,
    streaming?.text,
    streaming?.isStreaming,
    streaming?.citations.length,
  ]);

  return (
    <div className={cn("flex flex-col gap-4 px-4 py-6", className)}>
      <AnimatePresence initial={false}>
        {messages.map((m) => (
          <motion.div
            key={m.id}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.16 }}
            className={cn(
              "flex w-full",
              m.role === "user" ? "justify-end" : "justify-start",
            )}
          >
            <MessageBubble message={m} onArchive={onArchive} />
          </motion.div>
        ))}
      </AnimatePresence>

      {streaming?.isStreaming && (
        <motion.div
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex w-full justify-start"
        >
          <div className="max-w-[80ch] rounded-xl bg-card border border-border px-4 py-3 shadow-sm">
            {streaming.text ? (
              <StreamingText
                text={streaming.text}
                isStreaming={streaming.isStreaming}
                className="text-sm whitespace-pre-wrap leading-relaxed text-foreground"
              />
            ) : (
              <span className="inline-flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                Thinking…
              </span>
            )}
            {streaming.citations.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mt-3 pt-2 border-t border-border">
                {streaming.citations.map((c) => (
                  <CitationChip
                    key={c.article_path}
                    articlePath={c.article_path}
                    quote={c.quote}
                    score={c.score}
                  />
                ))}
              </div>
            )}
          </div>
        </motion.div>
      )}

      <div ref={endRef} />
    </div>
  );
}

function MessageBubble({
  message,
  onArchive,
}: {
  message: TranscriptMessage;
  onArchive?: (message: TranscriptMessage) => void;
}) {
  if (message.role === "user") {
    return (
      <div className="max-w-[70ch] rounded-xl bg-foreground text-background px-4 py-2.5 shadow-sm">
        <p className="text-sm whitespace-pre-wrap leading-relaxed">
          {message.text}
        </p>
      </div>
    );
  }

  return (
    <div className="max-w-[80ch] rounded-xl bg-card border border-border px-4 py-3 shadow-sm">
      <div className="prose prose-sm max-w-none dark:prose-invert text-sm leading-relaxed">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.text}</ReactMarkdown>
      </div>
      {message.citations && message.citations.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-3 pt-2 border-t border-border">
          {message.citations.map((c) => (
            <CitationChip
              key={c.article_path}
              articlePath={c.article_path}
              quote={c.quote}
              score={c.score}
            />
          ))}
        </div>
      )}
      {onArchive && message.role === "assistant" && (
        <div className="flex items-center justify-end gap-2 mt-2">
          <Button
            size="sm"
            variant="ghost"
            onClick={() => onArchive(message)}
            aria-label="Archive answer to wiki"
          >
            <Archive className="w-3.5 h-3.5" />
            Archive to wiki
          </Button>
        </div>
      )}
    </div>
  );
}
