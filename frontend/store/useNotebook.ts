"use client";

import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";

export type Theme = "light" | "dark" | "system";

interface NotebookState {
  currentNotebookId: string | null;
  currentArticlePath: string | null;
  theme: Theme;
  showGraphView: boolean;
  setNotebook: (id: string | null) => void;
  setArticle: (path: string | null) => void;
  toggleTheme: () => void;
  setTheme: (theme: Theme) => void;
  toggleGraphView: () => void;
}

export const useNotebookStore = create<NotebookState>()(
  persist(
    (set) => ({
      currentNotebookId: null,
      currentArticlePath: null,
      theme: "system",
      showGraphView: false,
      setNotebook: (id) =>
        set({ currentNotebookId: id, currentArticlePath: null }),
      setArticle: (path) => set({ currentArticlePath: path }),
      setTheme: (theme) => set({ theme }),
      toggleTheme: () =>
        set((s) => ({
          theme: s.theme === "dark" ? "light" : "dark",
        })),
      toggleGraphView: () => set((s) => ({ showGraphView: !s.showGraphView })),
    }),
    {
      name: "notebookai-state",
      storage: createJSONStorage(() => localStorage),
      partialize: (s) => ({
        currentNotebookId: s.currentNotebookId,
        theme: s.theme,
        showGraphView: s.showGraphView,
      }),
    }
  )
);
