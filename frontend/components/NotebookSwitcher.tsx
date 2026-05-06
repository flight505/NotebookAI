"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import {
  ChevronDown,
  FolderOpen,
  Plus,
  BookMarked,
  Loader2,
} from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";
import toast from "react-hot-toast";
import { useNotebookStore } from "@/store/useNotebook";
import { listLibrary, createNotebook, type LibraryEntry } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { cn } from "@/lib/cn";

export function NotebookSwitcher() {
  const [open, setOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const currentId = useNotebookStore((s) => s.currentNotebookId);
  const setNotebook = useNotebookStore((s) => s.setNotebook);

  const { data: library, isLoading } = useQuery({
    queryKey: ["library"],
    queryFn: listLibrary,
    retry: 0,
  });

  const current = library?.find((n) => n.id === currentId);

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "inline-flex items-center gap-2 px-3 h-9 rounded-md text-sm font-medium",
          "border border-border bg-card hover:bg-muted transition-colors",
          "max-w-[260px] min-w-[180px]"
        )}
      >
        <BookMarked className="w-4 h-4 text-accent shrink-0" />
        <span className="truncate flex-1 text-left">
          {current?.name ?? (isLoading ? "Loading…" : "Select notebook")}
        </span>
        <ChevronDown
          className={cn(
            "w-4 h-4 text-muted-foreground transition-transform",
            open && "rotate-180"
          )}
        />
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.12 }}
            className={cn(
              "absolute left-0 top-full mt-2 z-40",
              "w-[320px] bg-card border border-border rounded-lg shadow-xl overflow-hidden"
            )}
          >
            <div className="max-h-80 overflow-y-auto">
              {isLoading ? (
                <div className="px-3 py-6 text-sm text-muted-foreground flex items-center gap-2 justify-center">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Loading library…
                </div>
              ) : !library || library.length === 0 ? (
                <div className="px-4 py-8 text-center">
                  <BookMarked className="w-6 h-6 mx-auto mb-2 text-muted-foreground" />
                  <p className="text-sm text-muted-foreground mb-3">
                    No notebooks yet
                  </p>
                  <p className="text-xs text-muted-foreground/70">
                    Create one to get started.
                  </p>
                </div>
              ) : (
                <ul className="py-1">
                  {library.map((nb) => (
                    <NotebookRow
                      key={nb.id}
                      notebook={nb}
                      active={nb.id === currentId}
                      onSelect={() => {
                        setNotebook(nb.id);
                        setOpen(false);
                      }}
                    />
                  ))}
                </ul>
              )}
            </div>
            <div className="border-t border-border p-2 flex items-center gap-1">
              <Button
                variant="ghost"
                size="sm"
                className="flex-1 justify-start"
                onClick={() => {
                  setOpen(false);
                  setCreateOpen(true);
                }}
              >
                <Plus className="w-4 h-4" />
                New notebook
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="flex-1 justify-start"
                onClick={() => {
                  toast(
                    "External folder registration available via /api/library/register"
                  );
                }}
              >
                <FolderOpen className="w-4 h-4" />
                Open folder
              </Button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <CreateNotebookModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
      />
    </div>
  );
}

function NotebookRow({
  notebook,
  active,
  onSelect,
}: {
  notebook: LibraryEntry;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <li>
      <button
        onClick={onSelect}
        className={cn(
          "w-full text-left px-3 py-2 flex items-center gap-3 transition-colors",
          active ? "bg-subtle" : "hover:bg-muted"
        )}
      >
        <span
          className={cn(
            "w-2 h-2 rounded-full",
            active ? "bg-accent" : "bg-muted-foreground/30"
          )}
        />
        <span className="flex-1 min-w-0">
          <span className="block text-sm font-medium truncate">
            {notebook.name}
          </span>
          <span className="block text-xs text-muted-foreground truncate">
            {notebook.article_count} articles · {notebook.chat_count} chats
            {notebook.is_external && " · external"}
          </span>
        </span>
      </button>
    </li>
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
  const [description, setDescription] = useState("");
  const queryClient = useQueryClient();
  const setNotebook = useNotebookStore((s) => s.setNotebook);

  const mutation = useMutation({
    mutationFn: () => createNotebook({ name, description: description || undefined }),
    onSuccess: (nb) => {
      toast.success(`Created “${nb.name}”`);
      queryClient.invalidateQueries({ queryKey: ["library"] });
      setNotebook(nb.id);
      setName("");
      setDescription("");
      onClose();
    },
    onError: (err: any) => {
      toast.error(`Could not create notebook: ${err?.message ?? "unknown"}`);
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
            Description (optional)
          </label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
            placeholder="Notes and synthesis on…"
            className="w-full px-3 py-2 rounded-md border border-border bg-background text-sm resize-none focus:outline-none focus:border-accent"
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
