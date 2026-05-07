"use client";

import Image from "next/image";
import { motion } from "framer-motion";
import { Button } from "@/components/ui/Button";

interface Props {
  onNext: () => void;
}

/**
 * Step 1 — product pitch + hero icon. Pure presentation.
 */
export function WelcomeStep1({ onNext }: Props) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.2 }}
      className="flex flex-col items-center text-center px-6"
      data-testid="welcome-step-1"
    >
      <div className="w-24 h-24 mb-6 rounded-2xl overflow-hidden border border-border shadow-sm bg-card">
        <Image
          src="/icon.png"
          alt="NotebookAI"
          width={96}
          height={96}
          priority
        />
      </div>
      <h1 className="text-2xl font-semibold tracking-tight mb-3">
        Welcome to NotebookAI
      </h1>
      <p className="max-w-md text-sm text-muted-foreground leading-relaxed mb-8">
        NotebookAI is a local-first knowledge workspace. Drop in PDFs,
        URLs, and YouTube transcripts; the agent compiles them into a
        cross-linked wiki you can read, ask questions of, and curate. All
        notebooks live as plain markdown on your machine — no cloud, no
        lock-in.
      </p>
      <Button variant="accent" onClick={onNext} data-testid="welcome-step-1-next">
        Get started
      </Button>
    </motion.div>
  );
}
