"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BookOpen, MessageSquare, Sparkles, Sun, Moon } from "lucide-react";
import { motion } from "framer-motion";
import { useNotebookStore } from "@/store/useNotebook";
import { cn } from "@/lib/cn";
import { Tooltip } from "@/components/ui/Tooltip";

const modes = [
  {
    href: "/read",
    label: "Read",
    description: "Browse the wiki",
    icon: BookOpen,
  },
  {
    href: "/ask",
    label: "Ask",
    description: "Query with citations",
    icon: MessageSquare,
  },
  {
    href: "/curate",
    label: "Curate",
    description: "Review and approve",
    icon: Sparkles,
  },
] as const;

export function ModeNav() {
  const pathname = usePathname() ?? "";
  const theme = useNotebookStore((s) => s.theme);
  const toggleTheme = useNotebookStore((s) => s.toggleTheme);

  return (
    <nav className="flex items-center gap-1 p-1 rounded-lg bg-subtle border border-border">
      {modes.map((m) => {
        const active = pathname.startsWith(m.href);
        const Icon = m.icon;
        return (
          <Link
            key={m.href}
            href={m.href as any}
            className={cn(
              "relative inline-flex items-center gap-2 px-3 h-8 rounded-md text-sm font-medium",
              "transition-colors duration-150",
              active
                ? "text-foreground"
                : "text-muted-foreground hover:text-foreground"
            )}
            aria-current={active ? "page" : undefined}
          >
            {active && (
              <motion.span
                layoutId="mode-pill"
                className="absolute inset-0 rounded-md bg-card border border-border shadow-sm"
                transition={{ type: "spring", stiffness: 400, damping: 35 }}
              />
            )}
            <Icon className="w-4 h-4 relative z-10" />
            <span className="relative z-10">{m.label}</span>
          </Link>
        );
      })}
      <span className="mx-1 h-5 w-px bg-border" />
      <Tooltip content={theme === "dark" ? "Light mode" : "Dark mode"} side="bottom">
        <button
          aria-label="Toggle theme"
          onClick={toggleTheme}
          className="inline-flex items-center justify-center w-8 h-8 rounded-md text-muted-foreground hover:text-foreground hover:bg-card transition-colors"
        >
          {theme === "dark" ? (
            <Sun className="w-4 h-4" />
          ) : (
            <Moon className="w-4 h-4" />
          )}
        </button>
      </Tooltip>
    </nav>
  );
}
