"use client";

/**
 * LibraryPanel — top-left notebook library browser.
 *
 * Lists all notebooks discovered by the backend scanner (canonical
 * ``library_root`` + externally registered roots), with controls to:
 *   - search / filter by name
 *   - create a new notebook (via the existing /api/notebooks endpoint)
 *   - register an external folder (absolute path, validated server-side)
 *   - open a notebook's path in Finder/Explorer (web: copy to clipboard;
 *     Tauri: shell.open via the Tauri shell plugin)
 *   - drop a folder onto the panel to register it (browser File System
 *     Access API best-effort; full path is only available in Tauri)
 *
 * Drag-and-drop tradeoff: web browsers expose only the dropped file/folder
 * NAME via the standard DataTransfer API — not its absolute path — for
 * privacy reasons. We therefore prompt the user to confirm/paste the
 * absolute path on web. In a Tauri build, ``__TAURI__`` is present and we
 * read the dropped path directly from the Tauri-supplied event.
 */

import {
  ChangeEvent,
  DragEvent,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  BookMarked,
  Clock,
  ExternalLink,
  FolderInput,
  FolderOpen,
  Loader2,
  Plus,
  Search,
} from "lucide-react";
import toast from "react-hot-toast";
import {
  createNotebook,
  listLibrary,
  registerExternalNotebook,
  type LibraryEntry,
} from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { useNotebookStore } from "@/store/useNotebook";
import { cn } from "@/lib/cn";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function relativeTime(iso: string | null): string {
  if (!iso) return "—";
  const ts = Date.parse(iso);
  if (Number.isNaN(ts)) return "—";
  const diffMs = Date.now() - ts;
  const sec = Math.round(diffMs / 1000);
  if (sec < 60) return "just now";
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.round(hr / 24);
  if (day < 30) return `${day}d ago`;
  const mo = Math.round(day / 30);
  if (mo < 12) return `${mo}mo ago`;
  return new Date(ts).toLocaleDateString();
}

interface TauriShell {
  open: (path: string) => Promise<void>;
}

interface TauriGlobal {
  shell?: TauriShell;
}

declare global {
  interface Window {
    __TAURI__?: TauriGlobal;
  }
}

async function openInFileManager(path: string): Promise<void> {
  if (typeof window === "undefined") return;
  const tauri = window.__TAURI__;
  if (tauri?.shell?.open) {
    try {
      await tauri.shell.open(path);
      return;
    } catch (err) {
      toast.error(
        `Could not open: ${err instanceof Error ? err.message : String(err)}`
      );
      return;
    }
  }
  // Web fallback: copy the path to clipboard.
  try {
    await navigator.clipboard.writeText(path);
    toast.success("Path copied to clipboard");
  } catch {
    toast(path, { icon: "📋" });
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function LibraryPanel() {
  const queryClient = useQueryClient();
  const setLibrary = useNotebookStore((s) => s.setLibrary);
  const setNotebook = useNotebookStore((s) => s.setNotebook);
  const currentId = useNotebookStore((s) => s.currentNotebookId);

  const [search, setSearch] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [registerOpen, setRegisterOpen] = useState(false);
  const [dragOver, setDragOver] = useState(false);

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["library"],
    queryFn: listLibrary,
    retry: 0,
  });

  // Mirror the React Query result into the Zustand store so the rest of the
  // app can rely on a single source of truth.
  useEffect(() => {
    if (data) setLibrary(data);
  }, [data, setLibrary]);

  const filtered = useMemo(() => {
    const list = data ?? [];
    const q = search.trim().toLowerCase();
    if (!q) return list;
    return list.filter(
      (nb) =>
        nb.name.toLowerCase().includes(q) ||
        nb.id.toLowerCase().includes(q) ||
        nb.path.toLowerCase().includes(q)
    );
  }, [data, search]);

  // ---- drag & drop register -------------------------------------------------

  const registerMutation = useMutation({
    mutationFn: (path: string) => registerExternalNotebook(path),
    onSuccess: (entry) => {
      toast.success(`Registered "${entry.name}"`);
      queryClient.invalidateQueries({ queryKey: ["library"] });
    },
    onError: (err: unknown) => {
      const msg =
        err && typeof err === "object" && "message" in err
          ? String((err as { message: unknown }).message)
          : String(err);
      toast.error(`Could not register: ${msg}`);
    },
  });

  const handleDrop = async (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);

    // Tauri exposes a custom event with the dropped paths; in the browser
    // we only get File entries with no absolute path. Prefer Tauri.
    interface MaybeTauriDataTransfer extends DataTransfer {
      paths?: string[];
    }
    const dt = e.dataTransfer as MaybeTauriDataTransfer;
    if (dt?.paths && dt.paths.length > 0) {
      registerMutation.mutate(dt.paths[0]);
      return;
    }

    if (e.dataTransfer.items && e.dataTransfer.items.length > 0) {
      const item = e.dataTransfer.items[0];
      const file = item.getAsFile();
      if (file) {
        // In the browser we can't get the absolute path. Pre-fill the
        // register-external modal with the folder name to give the user a
        // hint on what to paste.
        setRegisterOpen(true);
        toast(
          "Browsers can't read absolute paths. Paste the full path to register.",
          { icon: "ℹ️" }
        );
      }
    }
  };

  return (
    <div
      className={cn(
        "flex flex-col w-full h-full bg-card border border-border rounded-lg overflow-hidden",
        dragOver && "ring-2 ring-accent ring-offset-2 ring-offset-background"
      )}
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
    >
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border">
        <BookMarked className="w-4 h-4 text-accent" />
        <span className="text-sm font-semibold tracking-tight flex-1">
          Library
        </span>
        <Button
          variant="ghost"
          size="sm"
          aria-label="Register external folder"
          onClick={() => setRegisterOpen(true)}
        >
          <FolderInput className="w-4 h-4" />
        </Button>
        <Button
          variant="accent"
          size="sm"
          aria-label="New notebook"
          onClick={() => setCreateOpen(true)}
        >
          <Plus className="w-4 h-4" />
          New
        </Button>
      </div>

      {/* Search */}
      <div className="px-3 py-2 border-b border-border">
        <div className="relative">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
          <input
            value={search}
            onChange={(e: ChangeEvent<HTMLInputElement>) =>
              setSearch(e.target.value)
            }
            placeholder="Search notebooks…"
            className="w-full h-8 pl-7 pr-2 rounded-md border border-border bg-background text-sm focus:outline-none focus:border-accent"
          />
        </div>
      </div>

      {/* List */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        {isLoading ? (
          <div className="flex items-center justify-center gap-2 py-8 text-sm text-muted-foreground">
            <Loader2 className="w-4 h-4 animate-spin" /> Loading library…
          </div>
        ) : isError ? (
          <div className="px-3 py-6 text-sm text-red-500">
            Couldn’t load library: {String(error)}
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState
            search={search}
            onCreate={() => setCreateOpen(true)}
            onRegister={() => setRegisterOpen(true)}
          />
        ) : (
          <ul className="py-1">
            {filtered.map((nb) => (
              <LibraryRow
                key={`${nb.id}-${nb.path}`}
                notebook={nb}
                active={nb.id === currentId}
                onSelect={() => setNotebook(nb.id)}
                onOpen={() => openInFileManager(nb.path)}
              />
            ))}
          </ul>
        )}
      </div>

      <CreateNotebookModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
      />
      <RegisterExternalModal
        open={registerOpen}
        onClose={() => setRegisterOpen(false)}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Subcomponents
// ---------------------------------------------------------------------------

function LibraryRow({
  notebook,
  active,
  onSelect,
  onOpen,
}: {
  notebook: LibraryEntry;
  active: boolean;
  onSelect: () => void;
  onOpen: () => void;
}) {
  return (
    <li>
      <div
        className={cn(
          "group flex items-center gap-2 px-3 py-2 transition-colors",
          active ? "bg-subtle" : "hover:bg-muted"
        )}
      >
        <button
          onClick={onSelect}
          className="flex-1 min-w-0 flex items-center gap-2 text-left"
        >
          <span
            className={cn(
              "w-2 h-2 rounded-full shrink-0",
              active ? "bg-accent" : "bg-muted-foreground/30"
            )}
          />
          <span className="flex-1 min-w-0">
            <span className="block text-sm font-medium truncate">
              {notebook.name}
              {notebook.is_external && (
                <span
                  className="ml-1.5 text-[10px] px-1 py-0.5 rounded bg-muted text-muted-foreground align-middle"
                  title="Registered from outside the library_root"
                >
                  ext
                </span>
              )}
            </span>
            <span className="flex items-center gap-2 text-xs text-muted-foreground truncate">
              <Clock className="w-3 h-3 shrink-0" />
              {relativeTime(notebook.last_op_at)}
              <span
                className="px-1.5 py-0.5 rounded bg-subtle text-foreground/80"
                title={`${notebook.article_count} article(s)`}
              >
                {notebook.article_count}
              </span>
            </span>
          </span>
        </button>
        <button
          onClick={onOpen}
          aria-label="Open in file manager"
          title="Open folder"
          className="opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded-md hover:bg-card"
        >
          <FolderOpen className="w-3.5 h-3.5" />
        </button>
      </div>
    </li>
  );
}

function EmptyState({
  search,
  onCreate,
  onRegister,
}: {
  search: string;
  onCreate: () => void;
  onRegister: () => void;
}) {
  if (search) {
    return (
      <div className="px-4 py-8 text-center text-sm text-muted-foreground">
        No notebooks match “{search}”.
      </div>
    );
  }
  return (
    <div className="px-4 py-10 text-center">
      <BookMarked className="w-6 h-6 mx-auto mb-2 text-muted-foreground" />
      <p className="text-sm text-muted-foreground mb-4">No notebooks yet</p>
      <div className="flex flex-col gap-2 items-center">
        <Button variant="accent" size="sm" onClick={onCreate}>
          <Plus className="w-3.5 h-3.5" /> Create notebook
        </Button>
        <Button variant="ghost" size="sm" onClick={onRegister}>
          <FolderInput className="w-3.5 h-3.5" /> Register external folder
        </Button>
      </div>
    </div>
  );
}

function CreateNotebookModal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [name, setName] = useState("");
  const [topic, setTopic] = useState("");
  const queryClient = useQueryClient();
  const setNotebook = useNotebookStore((s) => s.setNotebook);

  const mutation = useMutation({
    mutationFn: () =>
      createNotebook({ name, description: topic.trim() || undefined }),
    onSuccess: (nb) => {
      toast.success(`Created “${nb.name}”`);
      queryClient.invalidateQueries({ queryKey: ["library"] });
      setNotebook(nb.id);
      setName("");
      setTopic("");
      onClose();
    },
    onError: (err: unknown) => {
      const msg =
        err && typeof err === "object" && "message" in err
          ? String((err as { message: unknown }).message)
          : String(err);
      toast.error(`Could not create notebook: ${msg}`);
    },
  });

  return (
    <Modal open={open} onClose={onClose} title="Create notebook">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim()) mutation.mutate();
        }}
        className="space-y-4"
      >
        <div>
          <label className="block text-xs font-medium text-muted-foreground mb-1.5">
            Name
          </label>
          <input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="ML Research"
            className="w-full h-9 px-3 rounded-md border border-border bg-background text-sm focus:outline-none focus:border-accent"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-muted-foreground mb-1.5">
            Initial topic (optional)
          </label>
          <input
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="e.g. Reinforcement learning fundamentals"
            className="w-full h-9 px-3 rounded-md border border-border bg-background text-sm focus:outline-none focus:border-accent"
          />
        </div>
        <div className="flex items-center justify-end gap-2 pt-1">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="submit"
            variant="accent"
            disabled={!name.trim() || mutation.isPending}
          >
            {mutation.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
            Create
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function RegisterExternalModal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [path, setPath] = useState("");
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: () => registerExternalNotebook(path),
    onSuccess: (entry) => {
      toast.success(`Registered “${entry.name}”`);
      queryClient.invalidateQueries({ queryKey: ["library"] });
      setPath("");
      onClose();
    },
    onError: (err: unknown) => {
      const msg =
        err && typeof err === "object" && "message" in err
          ? String((err as { message: unknown }).message)
          : String(err);
      toast.error(`Could not register: ${msg}`);
    },
  });

  return (
    <Modal open={open} onClose={onClose} title="Register external notebook">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (path.trim()) mutation.mutate();
        }}
        className="space-y-4"
      >
        <div className="text-xs text-muted-foreground">
          Paste the absolute path to a folder containing
          <code className="mx-1 px-1 py-0.5 rounded bg-muted">
            .notebookai/notebook.json
          </code>
          .
        </div>
        <div>
          <label className="block text-xs font-medium text-muted-foreground mb-1.5">
            Absolute path
          </label>
          <input
            autoFocus
            value={path}
            onChange={(e) => setPath(e.target.value)}
            placeholder="/Users/you/elsewhere/my-notebook"
            className="w-full h-9 px-3 rounded-md border border-border bg-background text-sm font-mono focus:outline-none focus:border-accent"
          />
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <ExternalLink className="w-3 h-3" />
          Tip: in the desktop (Tauri) build, you can drop a folder onto the
          panel to auto-fill this.
        </div>
        <div className="flex items-center justify-end gap-2 pt-1">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="submit"
            variant="accent"
            disabled={!path.trim() || mutation.isPending}
          >
            {mutation.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
            Register
          </Button>
        </div>
      </form>
    </Modal>
  );
}

export default LibraryPanel;
