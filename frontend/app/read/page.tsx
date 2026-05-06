"use client";

import { Suspense, useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Network, BookOpen, Search } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { listArticles, getArticle, type Article } from "@/lib/api";
import { useNotebookStore } from "@/store/useNotebook";
import { ArticleTree } from "@/components/ArticleTree";
import { ArticleReader } from "@/components/ArticleReader";
import { Backlinks } from "@/components/Backlinks";
import { GraphView } from "@/components/GraphView";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/cn";

export const dynamic = "force-dynamic";

export default function ReadPage() {
  return (
    <Suspense fallback={<ReadSkeleton />}>
      <ReadShell />
    </Suspense>
  );
}

function ReadShell() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const articleParam = searchParams.get("article");

  const notebookId = useNotebookStore((s) => s.currentNotebookId);
  const setArticle = useNotebookStore((s) => s.setArticle);
  const showGraphView = useNotebookStore((s) => s.showGraphView);
  const toggleGraphView = useNotebookStore((s) => s.toggleGraphView);

  const articlesQuery = useQuery({
    queryKey: ["articles", notebookId],
    queryFn: () => (notebookId ? listArticles(notebookId) : Promise.resolve([])),
    enabled: !!notebookId,
    retry: 0,
  });

  const articles = articlesQuery.data ?? [];

  const articleQuery = useQuery({
    queryKey: ["article", notebookId, articleParam],
    queryFn: () =>
      notebookId && articleParam
        ? getArticle(notebookId, articleParam)
        : Promise.resolve(null as Article | null),
    enabled: !!notebookId && !!articleParam,
    retry: 0,
  });

  const navigate = (path: string) => {
    setArticle(path);
    const params = new URLSearchParams(searchParams.toString());
    params.set("article", path);
    router.push(`/read?${params.toString()}`);
  };

  useEffect(() => {
    if (articleParam) setArticle(articleParam);
  }, [articleParam, setArticle]);

  const errorMessage = useMemo(() => {
    const err = articlesQuery.error;
    if (!err) return null;
    return (err as any)?.message ?? "Backend unreachable";
  }, [articlesQuery.error]);

  if (!notebookId) {
    return <NoNotebookEmptyState />;
  }

  return (
    <div className="read-grid">
      {/* Left rail: article tree */}
      <aside className="border-r border-border bg-card/40 overflow-y-auto">
        <div className="px-3 py-2.5 border-b border-border flex items-center justify-between sticky top-0 bg-card/90 backdrop-blur z-10">
          <span className="text-xs font-semibold tracking-wider uppercase text-muted-foreground">
            Articles
          </span>
          <span className="text-[10px] tabular-nums text-muted-foreground">
            {articles.length}
          </span>
        </div>
        {errorMessage ? (
          <div className="p-4 text-xs text-muted-foreground leading-relaxed">
            <p className="mb-2 font-medium text-foreground">Backend offline</p>
            <p>
              Start the FastAPI backend on{" "}
              <code className="font-mono text-[11px] px-1 py-0.5 rounded bg-muted">
                127.0.0.1:8765
              </code>{" "}
              to load articles.
            </p>
          </div>
        ) : (
          <ArticleTree
            articles={articles}
            selectedPath={articleParam}
            onSelect={navigate}
            loading={articlesQuery.isLoading}
          />
        )}
      </aside>

      {/* Center: article reader */}
      <section className="overflow-hidden bg-background relative">
        <AnimatePresence mode="wait">
          <ArticleReader
            key={articleParam ?? "empty"}
            article={articleQuery.data ?? null}
            articles={articles}
            loading={articleQuery.isLoading}
            error={
              articleQuery.error
                ? ((articleQuery.error as any)?.message ?? "Load failed")
                : null
            }
            onNavigate={navigate}
          />
        </AnimatePresence>
      </section>

      {/* Right rail: backlinks + graph */}
      <aside className="border-l border-border bg-card/40 overflow-y-auto">
        <div className="px-3 py-2.5 border-b border-border flex items-center justify-between sticky top-0 bg-card/90 backdrop-blur z-10">
          <span className="text-xs font-semibold tracking-wider uppercase text-muted-foreground">
            {showGraphView ? "Graph" : "Backlinks"}
          </span>
          <Button
            variant="ghost"
            size="sm"
            onClick={toggleGraphView}
            className="h-6 px-2 text-xs"
            aria-pressed={showGraphView}
          >
            <Network
              className={cn(
                "w-3.5 h-3.5",
                showGraphView ? "text-accent" : "text-muted-foreground"
              )}
            />
            {showGraphView ? "Backlinks" : "Graph"}
          </Button>
        </div>
        {showGraphView ? (
          <GraphView
            articles={articles}
            currentPath={articleParam}
            onNavigate={navigate}
          />
        ) : (
          <Backlinks
            current={articleQuery.data ?? null}
            articles={articles}
            onNavigate={navigate}
          />
        )}
      </aside>
    </div>
  );
}

function ReadSkeleton() {
  return (
    <div className="read-grid">
      <div className="border-r border-border bg-card/40" />
      <div />
      <div className="border-l border-border bg-card/40" />
    </div>
  );
}

function NoNotebookEmptyState() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      className="flex-1 flex items-center justify-center px-6"
    >
      <div className="max-w-md text-center">
        <div className="w-14 h-14 rounded-2xl bg-subtle border border-border mx-auto mb-5 flex items-center justify-center">
          <BookOpen className="w-6 h-6 text-accent" />
        </div>
        <h1 className="text-xl font-semibold tracking-tight mb-2">
          Select a notebook
        </h1>
        <p className="text-sm text-muted-foreground leading-relaxed mb-6">
          NotebookAI organizes your reading into notebooks. Pick one from the
          switcher above, or create your first to start ingesting sources.
        </p>
        <div className="text-xs text-muted-foreground inline-flex items-center gap-2">
          <Search className="w-3.5 h-3.5" />
          Library lives in <code className="font-mono">~/NotebookAI/notebooks/</code>
        </div>
      </div>
    </motion.div>
  );
}
