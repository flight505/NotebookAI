import axios, { AxiosInstance } from "axios";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8765/api";

export const http: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30_000,
  headers: { "Content-Type": "application/json" },
});

// ─── Types matching CONTRACTS.md ──────────────────────────────────────────────

export interface NotebookAgentConfig {
  model: string;
  lint_model: string;
  lint_schedule: "hourly" | "daily" | "off";
  lint_budget_tokens_per_day: number;
}

export interface NotebookEmbeddingsConfig {
  model: string;
  dim: number;
}

export interface NotebookStats {
  raw_count: number;
  wiki_count: number;
  chat_count: number;
  last_op_at: string | null;
}

export interface Notebook {
  id: string;
  name: string;
  path: string;
  created_at: string;
  schema_version: number;
  git_enabled: boolean;
  agent: NotebookAgentConfig;
  embeddings: NotebookEmbeddingsConfig;
  description?: string;
  stats: NotebookStats;
}

export type NotebookMutable = Pick<Notebook, "name" | "description" | "agent">;

/**
 * A library listing entry — matches backend ``NotebookEntry`` from
 * ``backend/notebookai/library/scanner.py``. This is intentionally a
 * lighter shape than ``Notebook`` (no ``agent``/``embeddings``) so that
 * scanning many notebooks stays cheap.
 */
export interface LibraryEntry {
  id: string;
  name: string;
  path: string;
  created_at: string | null;
  last_op_at: string | null;
  article_count: number;
  chat_count: number;
  is_external: boolean;
  git_enabled: boolean;
}

export interface RegisterExternalRequest {
  path: string;
}

export interface IngestJob {
  id: string;
  notebook_id: string;
  kind: "url" | "file" | "youtube";
  source: string;
  topic: string;
  raw_path: string;
  status: "queued" | "fetching" | "compiling" | "done" | "error";
  error?: string;
  started_at: string;
  finished_at?: string;
}

export interface Citation {
  wiki_path: string;
  anchor?: string;
  raw_refs: { raw_path: string; offset_start: number; offset_end: number }[];
}

export interface LintFinding {
  id: string;
  notebook_id: string;
  kind: "contradiction" | "orphan" | "missing_xref" | "thin_coverage" | "stale_link";
  severity: "info" | "warn" | "error";
  wiki_paths: string[];
  message: string;
  suggested_fix?: string;
  status: "open" | "accepted" | "rejected" | "deferred";
  created_at: string;
}

export interface Article {
  path: string;
  title: string;
  content: string;
  frontmatter: Record<string, unknown>;
  backlinks: string[];
  outlinks: string[];
  raw_refs: string[];
  updated_at: string;
}

export interface OpLogEntry {
  id: string;
  op: "ingest" | "compile" | "cascade" | "archive" | "lint-fix" | "human-edit";
  summary: string;
  files_changed: string[];
  author: "agent" | "human";
  created_at: string;
}

export interface Commit {
  sha: string;
  author: string;
  subject: string;
  body: string;
  created_at: string;
  files_changed: string[];
}

export interface CommitDetail extends Commit {
  diff: string;
}

export interface BacklinkEntry {
  source_path: string;
  source_title: string;
  context_snippet: string;
}

// ─── Endpoints ────────────────────────────────────────────────────────────────

export async function listNotebooks(): Promise<Notebook[]> {
  const { data } = await http.get<Notebook[]>("/notebooks");
  return data;
}

export async function createNotebook(input: {
  name: string;
  id?: string;
  description?: string;
}): Promise<Notebook> {
  const { data } = await http.post<Notebook>("/notebooks", input);
  return data;
}

export async function getNotebook(id: string): Promise<Notebook> {
  const { data } = await http.get<Notebook>(`/notebooks/${id}`);
  return data;
}

export async function deleteNotebook(id: string): Promise<{ deleted: true }> {
  const { data } = await http.delete<{ deleted: true }>(`/notebooks/${id}`);
  return data;
}

export async function listLibrary(): Promise<LibraryEntry[]> {
  const { data } = await http.get<LibraryEntry[]>("/library");
  return data;
}

export async function registerExternalNotebook(
  path: string
): Promise<LibraryEntry> {
  const { data } = await http.post<LibraryEntry>("/library/register", { path });
  return data;
}

export async function deregisterExternalNotebook(path: string): Promise<void> {
  // Use base64url encoding to avoid path-traversal in the URL segment.
  const encoded = btoa(unescape(encodeURIComponent(path)))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
  await http.delete(`/library/external/${encoded}`);
}

export async function ingest(
  notebookId: string,
  kind: "url" | "youtube",
  payload: { url: string; topic?: string }
): Promise<IngestJob> {
  const { data } = await http.post<IngestJob>(
    `/notebooks/${notebookId}/ingest/${kind}`,
    payload
  );
  return data;
}

export async function ask(
  notebookId: string,
  payload: { query: string; chat_id?: string }
): Promise<{ answer: string; citations: Citation[] }> {
  // Non-streaming variant: collect SSE chunks server-side or use a simple POST.
  // The contract defines streaming; for non-stream callers the SSE deltas are
  // joined client-side. Most callers should use askStream.
  const { data } = await http.post(`/notebooks/${notebookId}/ask`, {
    ...payload,
    stream: false,
  });
  return data;
}

export interface AskStreamEvent {
  event: string;
  data: Record<string, unknown>;
  id?: string;
}

export async function* askStream(
  notebookId: string,
  payload: { query: string; chat_id?: string },
  signal?: AbortSignal
): AsyncIterableIterator<AskStreamEvent> {
  const res = await fetch(`${API_BASE_URL}/notebooks/${notebookId}/ask`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(payload),
    signal,
  });
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
    let sep;
    while ((sep = buf.indexOf("\n\n")) !== -1) {
      const chunk = buf.slice(0, sep);
      buf = buf.slice(sep + 2);
      const ev = parseSseChunk(chunk);
      if (ev) yield ev;
    }
  }
}

function parseSseChunk(chunk: string): AskStreamEvent | null {
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

export async function lint(
  notebookId: string,
  scope: "all" | "recent" = "recent"
): Promise<{ job_id: string }> {
  const { data } = await http.post(`/notebooks/${notebookId}/lint`, { scope });
  return data;
}

export async function listLintFindings(
  notebookId: string,
  status?: "open" | "resolved"
): Promise<LintFinding[]> {
  const { data } = await http.get<LintFinding[]>(
    `/notebooks/${notebookId}/lint/findings`,
    { params: status ? { status } : undefined }
  );
  return data;
}

export async function listArticles(
  notebookId: string,
  params?: { topic?: string; q?: string }
): Promise<Article[]> {
  const { data } = await http.get<Article[]>(
    `/notebooks/${notebookId}/articles`,
    { params }
  );
  return data;
}

export async function getArticle(
  notebookId: string,
  path: string
): Promise<Article> {
  const { data } = await http.get<Article>(
    `/notebooks/${notebookId}/articles/${encodeURI(path)}`
  );
  return data;
}

export async function putArticle(
  notebookId: string,
  path: string,
  content: string
): Promise<Article> {
  const { data } = await http.put<Article>(
    `/notebooks/${notebookId}/articles/${encodeURI(path)}`,
    { content }
  );
  return data;
}

export async function getBacklinks(
  notebookId: string,
  path: string
): Promise<BacklinkEntry[]> {
  const { data } = await http.get<BacklinkEntry[]>(
    `/notebooks/${notebookId}/articles/${encodeURI(path)}/backlinks`
  );
  return data;
}

export async function getLog(
  notebookId: string,
  params?: { limit?: number; since?: string }
): Promise<OpLogEntry[]> {
  const { data } = await http.get<OpLogEntry[]>(
    `/notebooks/${notebookId}/log`,
    { params }
  );
  return data;
}

export async function getHistory(
  notebookId: string,
  params?: { path?: string; limit?: number }
): Promise<Commit[]> {
  const { data } = await http.get<Commit[]>(
    `/notebooks/${notebookId}/history`,
    { params }
  );
  return data;
}

// ─── SSE subscription ────────────────────────────────────────────────────────

export interface EventSubscription {
  close: () => void;
}

export function subscribeEvents(
  notebookId: string,
  onEvent: (event: string, data: any) => void,
  options?: { since?: string; onError?: (err: unknown) => void }
): EventSubscription {
  let closed = false;
  let es: EventSource | null = null;
  let retryDelay = 1000;
  const maxDelay = 30_000;

  const connect = () => {
    if (closed) return;
    const url = new URL(`${API_BASE_URL}/notebooks/${notebookId}/events`);
    if (options?.since) url.searchParams.set("since", options.since);

    try {
      es = new EventSource(url.toString());
    } catch (err) {
      options?.onError?.(err);
      return;
    }

    const knownEvents = [
      "agent.tool_call",
      "agent.tool_result",
      "agent.message",
      "agent.done",
      "agent.error",
      "ingest.started",
      "ingest.complete",
      "lint.finding",
      "file.changed",
    ];

    knownEvents.forEach((evName) => {
      es!.addEventListener(evName, (ev) => {
        try {
          const data = JSON.parse((ev as MessageEvent).data);
          onEvent(evName, data);
        } catch {
          /* swallow */
        }
        retryDelay = 1000;
      });
    });

    es.onerror = () => {
      if (closed) return;
      es?.close();
      es = null;
      setTimeout(connect, retryDelay);
      retryDelay = Math.min(retryDelay * 2, maxDelay);
    };
  };

  connect();

  return {
    close() {
      closed = true;
      es?.close();
    },
  };
}
