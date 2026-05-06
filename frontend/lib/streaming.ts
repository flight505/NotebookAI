// Streaming helpers for the Ask mode SSE endpoint.

import { API_BASE_URL } from "@/lib/api";

export interface StreamCitation {
  article_path: string;
  quote: string;
  score?: number | null;
}

export interface StreamSseEvent {
  event: string;
  id?: string;
  data: Record<string, unknown>;
}

interface AskStreamPayload {
  prompt: string;
  archive?: boolean;
  chat_id?: string | null;
}

/**
 * Open a POST + SSE stream against /ask?stream=true. Yields parsed
 * `{event, id, data}` objects until the stream closes.
 */
export async function* postAskStream(
  notebookId: string,
  payload: AskStreamPayload,
  signal?: AbortSignal,
): AsyncIterableIterator<StreamSseEvent> {
  const res = await fetch(
    `${API_BASE_URL}/notebooks/${notebookId}/ask`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify({ ...payload, stream: true }),
      signal,
    },
  );
  if (!res.ok || !res.body) {
    throw new Error(`ask stream failed: ${res.status}`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let sep: number;
    while ((sep = buf.indexOf("\n\n")) !== -1) {
      const chunk = buf.slice(0, sep);
      buf = buf.slice(sep + 2);
      const ev = parseSseChunk(chunk);
      if (ev) yield ev;
    }
  }
}

function parseSseChunk(chunk: string): StreamSseEvent | null {
  const lines = chunk.split("\n");
  let event = "message";
  let id: string | undefined;
  const dataLines: string[] = [];
  for (const line of lines) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("id:")) id = line.slice(3).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (!dataLines.length) return null;
  try {
    return { event, id, data: JSON.parse(dataLines.join("\n")) };
  } catch {
    return { event, id, data: { raw: dataLines.join("\n") } };
  }
}

/**
 * Coalesce a Read tool-call into a citation entry.
 * The agent emits `agent.tool_call` with `tool: "Read"` and either
 * `input.path` or `input.file_path`. We strip everything before
 * `wiki/` so we get a stable wiki-relative path.
 */
export function citationFromToolCall(
  data: Record<string, unknown>,
): StreamCitation | null {
  const tool = (data["tool"] as string) || "";
  if (tool !== "Read") return null;
  const input = (data["input"] as Record<string, unknown> | undefined) ?? {};
  const raw = (input["path"] || input["file_path"]) as string | undefined;
  if (!raw) return null;
  const idx = raw.indexOf("wiki/");
  if (idx === -1) return null;
  return { article_path: raw.slice(idx), quote: "" };
}
