"use client";

import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import { listLibrary, type LibraryEntry } from "@/lib/api";

export type Theme = "light" | "dark" | "system";

interface NotebookState {
  currentNotebookId: string | null;
  currentArticlePath: string | null;
  theme: Theme;
  showGraphView: boolean;

  // Library-backed catalog of notebooks. Persisted shallowly; the canonical
  // source of truth is the backend, refreshed via ``refreshLibrary()``.
  library: LibraryEntry[];
  libraryLoading: boolean;
  libraryError: string | null;

  setNotebook: (id: string | null) => void;
  setArticle: (path: string | null) => void;
  toggleTheme: () => void;
  setTheme: (theme: Theme) => void;
  toggleGraphView: () => void;
  setLibrary: (library: LibraryEntry[]) => void;
  refreshLibrary: () => Promise<void>;
}

export const useNotebookStore = create<NotebookState>()(
  persist(
    (set, get) => ({
      currentNotebookId: null,
      currentArticlePath: null,
      theme: "system",
      showGraphView: false,
      library: [],
      libraryLoading: false,
      libraryError: null,

      setNotebook: (id) =>
        set({ currentNotebookId: id, currentArticlePath: null }),
      setArticle: (path) => set({ currentArticlePath: path }),
      setTheme: (theme) => set({ theme }),
      toggleTheme: () =>
        set((s) => ({
          theme: s.theme === "dark" ? "light" : "dark",
        })),
      toggleGraphView: () => set((s) => ({ showGraphView: !s.showGraphView })),
      setLibrary: (library) => {
        const current = get().currentNotebookId;
        const stillThere =
          current === null || library.some((nb) => nb.id === current);
        set({
          library,
          libraryError: null,
          currentNotebookId: stillThere ? current : null,
        });
      },
      refreshLibrary: async () => {
        set({ libraryLoading: true, libraryError: null });
        try {
          const library = await listLibrary();
          get().setLibrary(library);
        } catch (err) {
          set({
            libraryError: err instanceof Error ? err.message : String(err),
          });
        } finally {
          set({ libraryLoading: false });
        }
      },
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
