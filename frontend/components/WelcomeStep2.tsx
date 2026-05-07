"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FolderInput, Loader2, Plus, Sparkles } from "lucide-react";
import toast from "react-hot-toast";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { Card, CardBody } from "@/components/ui/Card";
import { library } from "@/lib/api";

interface Props {
  onNext: (notebookId: string) => void;
}

/**
 * Step 2 — choose a starting setup. The three buttons map to:
 *
 *   1. Create empty notebook  → POST /api/notebooks  (default name)
 *   2. Try the demo notebook  → POST /api/library/demo  (idempotent)
 *   3. Connect to existing folder → POST /api/library/register
 */
export function WelcomeStep2({ onNext }: Props) {
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [registerOpen, setRegisterOpen] = useState(false);

  const demoMutation = useMutation({
    mutationFn: () => library.createDemoNotebook(),
    onSuccess: (entry) => {
      queryClient.invalidateQueries({ queryKey: ["library"] });
      toast.success(`Demo notebook ready: ${entry.name}`);
      onNext(entry.id);
    },
    onError: (err: unknown) => {
      const msg =
        err && typeof err === "object" && "message" in err
          ? String((err as { message: unknown }).message)
          : String(err);
      toast.error(`Could not create demo notebook: ${msg}`);
    },
  });

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.2 }}
      className="px-6 w-full max-w-2xl"
      data-testid="welcome-step-2"
    >
      <div className="text-center mb-8">
        <h2 className="text-xl font-semibold tracking-tight mb-2">
          Choose a starting setup
        </h2>
        <p className="text-sm text-muted-foreground">
          You can always add more notebooks later from the Library panel.
        </p>
      </div>

      <div className="grid gap-3">
        <ChoiceCard
          icon={<Plus className="w-5 h-5" />}
          title="Create empty notebook"
          description="A fresh, blank knowledge base named “My Knowledge Base”. Add sources from Curate mode."
          onClick={() => setCreateOpen(true)}
          testId="welcome-create-empty"
        />
        <ChoiceCard
          icon={<Sparkles className="w-5 h-5" />}
          title="Try the demo notebook"
          description="A small seeded notebook with three wiki articles and one chat — explore the UI in seconds."
          onClick={() => demoMutation.mutate()}
          loading={demoMutation.isPending}
          testId="welcome-create-demo"
        />
        <ChoiceCard
          icon={<FolderInput className="w-5 h-5" />}
          title="Connect to existing folder"
          description="Register an external folder that already contains a NotebookAI notebook on disk."
          onClick={() => setRegisterOpen(true)}
          testId="welcome-register-external"
        />
      </div>

      <CreateNotebookModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={(id) => {
          setCreateOpen(false);
          onNext(id);
        }}
      />
      <RegisterExternalModal
        open={registerOpen}
        onClose={() => setRegisterOpen(false)}
        onRegistered={(id) => {
          setRegisterOpen(false);
          onNext(id);
        }}
      />
    </motion.div>
  );
}

// ---------------------------------------------------------------------------
// Subcomponents
// ---------------------------------------------------------------------------

function ChoiceCard({
  icon,
  title,
  description,
  onClick,
  loading,
  testId,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  onClick: () => void;
  loading?: boolean;
  testId: string;
}) {
  return (
    <Card className="cursor-pointer hover:border-accent transition-colors">
      <CardBody>
        <button
          onClick={onClick}
          disabled={loading}
          data-testid={testId}
          className="flex items-start gap-3 text-left w-full disabled:opacity-60"
        >
          <span className="shrink-0 w-9 h-9 rounded-md bg-subtle flex items-center justify-center text-accent">
            {loading ? <Loader2 className="w-5 h-5 animate-spin" /> : icon}
          </span>
          <span className="flex-1 min-w-0">
            <span className="block text-sm font-semibold mb-1">{title}</span>
            <span className="block text-xs text-muted-foreground leading-relaxed">
              {description}
            </span>
          </span>
        </button>
      </CardBody>
    </Card>
  );
}

function CreateNotebookModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (id: string) => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("My Knowledge Base");

  const mutation = useMutation({
    mutationFn: () => library.createNotebook({ name }),
    onSuccess: (nb) => {
      queryClient.invalidateQueries({ queryKey: ["library"] });
      toast.success(`Created “${nb.name}”`);
      onCreated(nb.id);
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
    <Modal open={open} onClose={onClose} title="Create empty notebook">
      <form
        data-testid="welcome-create-empty-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim()) mutation.mutate();
        }}
        className="space-y-4"
      >
        <div>
          <label className="block text-xs font-medium text-muted-foreground mb-1.5">
            Notebook name
          </label>
          <input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            data-testid="welcome-create-empty-name"
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
            data-testid="welcome-create-empty-submit"
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
  onRegistered,
}: {
  open: boolean;
  onClose: () => void;
  onRegistered: (id: string) => void;
}) {
  const queryClient = useQueryClient();
  const [path, setPath] = useState("");

  const mutation = useMutation({
    mutationFn: () => library.registerExternal(path),
    onSuccess: (entry) => {
      queryClient.invalidateQueries({ queryKey: ["library"] });
      toast.success(`Registered “${entry.name}”`);
      onRegistered(entry.id);
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
    <Modal open={open} onClose={onClose} title="Connect to existing folder">
      <form
        data-testid="welcome-register-external-form"
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
            data-testid="welcome-register-external-path"
            className="w-full h-9 px-3 rounded-md border border-border bg-background text-sm font-mono focus:outline-none focus:border-accent"
          />
        </div>
        <div className="flex items-center justify-end gap-2 pt-1">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="submit"
            variant="accent"
            disabled={!path.trim() || mutation.isPending}
            data-testid="welcome-register-external-submit"
          >
            {mutation.isPending && <Loader2 className="w-4 h-4 animate-spin" />}
            Register
          </Button>
        </div>
      </form>
    </Modal>
  );
}
