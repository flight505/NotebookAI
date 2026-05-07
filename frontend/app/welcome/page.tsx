"use client";

/**
 * /welcome — first-run onboarding flow.
 *
 * Three steps:
 *   1. Product pitch + hero icon.
 *   2. Choose a starting setup (create empty / try demo / register).
 *   3. Verify Claude availability, then dismiss the flow.
 *
 * Gates: this page is a no-op for users who already have notebooks OR
 * who've previously dismissed the flow. Both checks redirect to /read
 * silently — we don't want to trap returning users.
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { listLibrary } from "@/lib/api";
import { useNotebookStore } from "@/store/useNotebook";
import { WelcomeStep1 } from "@/components/WelcomeStep1";
import { WelcomeStep2 } from "@/components/WelcomeStep2";
import { WelcomeStep3 } from "@/components/WelcomeStep3";
import { cn } from "@/lib/cn";

export const dynamic = "force-dynamic";

const DISMISS_KEY = "notebookai.welcome.dismissed";

export default function WelcomePage() {
  const router = useRouter();
  const setNotebook = useNotebookStore((s) => s.setNotebook);
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [createdNotebookId, setCreatedNotebookId] = useState<string | null>(null);
  const [readyToRender, setReadyToRender] = useState(false);

  // Library check + localStorage gate. Run once on mount; if the user
  // already has notebooks AND hasn't asked for the flow, redirect away
  // immediately so we don't flash the welcome screen.
  const libraryQuery = useQuery({
    queryKey: ["library"],
    queryFn: listLibrary,
    retry: 0,
  });

  useEffect(() => {
    if (libraryQuery.isLoading) return;
    const dismissed =
      typeof window !== "undefined" &&
      window.localStorage.getItem(DISMISS_KEY) === "true";
    const hasNotebooks = (libraryQuery.data ?? []).length > 0;
    // Either gate skips the welcome flow:
    //  - the user already dismissed it once, or
    //  - the user already has notebooks (don't trap returning users).
    if (dismissed || hasNotebooks) {
      router.replace("/read");
      return;
    }
    setReadyToRender(true);
  }, [libraryQuery.data, libraryQuery.isLoading, router]);

  const handleSelected = (notebookId: string) => {
    setCreatedNotebookId(notebookId);
    setNotebook(notebookId);
    setStep(3);
  };

  const handleFinish = () => {
    try {
      window.localStorage.setItem(DISMISS_KEY, "true");
    } catch {
      /* ignore quota errors */
    }
    if (createdNotebookId) {
      router.push(`/read?notebook=${encodeURIComponent(createdNotebookId)}`);
    } else {
      router.push("/read");
    }
  };

  if (!readyToRender) {
    return (
      <div
        className="flex-1 flex items-center justify-center"
        data-testid="welcome-loading"
      />
    );
  }

  return (
    <div
      className="flex-1 flex items-center justify-center py-12"
      data-testid="welcome-shell"
    >
      <div className="w-full max-w-3xl flex flex-col items-center">
        <StepIndicator step={step} />
        <div className="mt-10 w-full flex justify-center">
          <AnimatePresence mode="wait">
            {step === 1 && (
              <motion.div
                key="step-1"
                initial={false}
                className="w-full flex justify-center"
              >
                <WelcomeStep1 onNext={() => setStep(2)} />
              </motion.div>
            )}
            {step === 2 && (
              <motion.div
                key="step-2"
                initial={false}
                className="w-full flex justify-center"
              >
                <WelcomeStep2 onNext={handleSelected} />
              </motion.div>
            )}
            {step === 3 && createdNotebookId && (
              <motion.div
                key="step-3"
                initial={false}
                className="w-full flex justify-center"
              >
                <WelcomeStep3
                  notebookId={createdNotebookId}
                  onFinish={handleFinish}
                />
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}

function StepIndicator({ step }: { step: 1 | 2 | 3 }) {
  const steps: { n: 1 | 2 | 3; label: string }[] = [
    { n: 1, label: "Welcome" },
    { n: 2, label: "Set up" },
    { n: 3, label: "Verify" },
  ];
  return (
    <ol
      className="flex items-center gap-3 text-xs text-muted-foreground"
      data-testid="welcome-step-indicator"
      aria-label="Onboarding progress"
    >
      {steps.map((s, idx) => (
        <li key={s.n} className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <span
              className={cn(
                "w-6 h-6 rounded-full border flex items-center justify-center text-[11px] font-semibold tabular-nums",
                s.n === step
                  ? "border-accent bg-accent text-accent-foreground"
                  : s.n < step
                    ? "border-accent/50 bg-accent/10 text-accent"
                    : "border-border text-muted-foreground"
              )}
              data-testid={`welcome-step-marker-${s.n}`}
              data-active={s.n === step}
            >
              {s.n}
            </span>
            <span
              className={cn(
                "font-medium",
                s.n === step ? "text-foreground" : ""
              )}
            >
              {s.label}
            </span>
          </div>
          {idx < steps.length - 1 && (
            <span
              className={cn(
                "w-8 h-px",
                s.n < step ? "bg-accent/50" : "bg-border"
              )}
            />
          )}
        </li>
      ))}
    </ol>
  );
}
