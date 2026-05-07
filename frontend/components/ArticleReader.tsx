"use client";

import { useMemo } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import {
  oneDark,
  oneLight,
} from "react-syntax-highlighter/dist/esm/styles/prism";
import { Link as LinkIcon, AlertCircle } from "lucide-react";
import { motion } from "framer-motion";
import type { Article } from "@/lib/api";
import { remarkWikilinks, slugify } from "@/lib/remarkWikilinks";
import { useNotebookStore } from "@/store/useNotebook";
import { Skeleton } from "@/components/ui/Skeleton";
import { cn } from "@/lib/cn";

interface ArticleReaderProps {
  article: Article | null;
  articles: Article[];
  loading?: boolean;
  error?: string | null;
  onNavigate: (path: string) => void;
}

export function ArticleReader({
  article,
  articles,
  loading,
  error,
  onNavigate,
}: ArticleReaderProps) {
  const theme = useNotebookStore((s) => s.theme);
  const isDark =
    theme === "dark" ||
    (theme === "system" &&
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-color-scheme: dark)").matches);

  const resolver = useMemo(() => {
    const byBasename = new Map<string, Article>();
    const byPath = new Map<string, Article>();
    const backlinkCounts = new Map<string, number>();
    for (const a of articles) {
      byPath.set(a.path, a);
      const base = a.path.split("/").pop()?.replace(/\.md$/, "");
      if (base) byBasename.set(base.toLowerCase(), a);
      backlinkCounts.set(a.path, a.backlinks?.length ?? 0);
    }
    return (target: string) => {
      const norm = target.replace(/\.md$/, "").toLowerCase();
      const direct =
        byPath.get(target) ||
        byPath.get(target + ".md") ||
        byPath.get(target.toLowerCase()) ||
        byPath.get(target.toLowerCase() + ".md");
      if (direct) {
        return {
          path: direct.path,
          exists: true,
          backlinkCount: backlinkCounts.get(direct.path) ?? 0,
        };
      }
      const byBase = byBasename.get(norm.split("/").pop() ?? norm);
      if (byBase) {
        return {
          path: byBase.path,
          exists: true,
          backlinkCount: backlinkCounts.get(byBase.path) ?? 0,
        };
      }
      return { path: target, exists: false, backlinkCount: 0 };
    };
  }, [articles]);

  if (loading) {
    return (
      <div className="p-10 max-w-prose mx-auto space-y-4">
        <Skeleton className="h-9 w-2/3" />
        <Skeleton className="h-4 w-1/3" />
        <div className="space-y-2 pt-6">
          {[...Array(8)].map((_, i) => (
            <Skeleton
              key={i}
              className="h-4"
              style={{ width: `${70 + ((i * 7) % 30)}%` }}
            />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-10 flex flex-col items-center justify-center text-center">
        <AlertCircle className="w-8 h-8 text-muted-foreground mb-3" />
        <p className="text-sm font-medium mb-1">Could not load article</p>
        <p className="text-xs text-muted-foreground max-w-xs">{error}</p>
      </div>
    );
  }

  if (!article) {
    return (
      <div className="p-10 flex flex-col items-center justify-center h-full text-center">
        <div className="w-12 h-12 rounded-full bg-subtle flex items-center justify-center mb-4">
          <LinkIcon className="w-5 h-5 text-muted-foreground" />
        </div>
        <p className="text-sm font-medium text-foreground mb-1.5">
          Select an article
        </p>
        <p className="text-xs text-muted-foreground max-w-sm leading-relaxed">
          Pick an article from the tree on the left, or follow a wikilink from
          another article.
        </p>
      </div>
    );
  }

  const components: Components = {
    h1: ({ children, ...props }) => {
      const text = String(children);
      const id = slugify(text);
      return (
        <h1 id={id} {...props}>
          {children}
          <a
            href={`#${id}`}
            aria-label={`Link to ${text}`}
            className="anchor-link"
          >
            <LinkIcon className="w-3.5 h-3.5" />
          </a>
        </h1>
      );
    },
    h2: ({ children, ...props }) => {
      const text = String(children);
      const id = slugify(text);
      return (
        <h2 id={id} {...props}>
          {children}
          <a
            href={`#${id}`}
            aria-label={`Link to ${text}`}
            className="anchor-link"
          >
            <LinkIcon className="w-3.5 h-3.5" />
          </a>
        </h2>
      );
    },
    h3: ({ children, ...props }) => {
      const text = String(children);
      const id = slugify(text);
      return (
        <h3 id={id} {...props}>
          {children}
          <a
            href={`#${id}`}
            aria-label={`Link to ${text}`}
            className="anchor-link"
          >
            <LinkIcon className="w-3 h-3" />
          </a>
        </h3>
      );
    },
    a: ({ href, title, children, className, ...props }) => {
      const isWikilink =
        typeof className === "string" && className.includes("wikilink");
      const exists =
        isWikilink && (props as any)["data-wikilink-exists"] === "true";
      const target = (props as any)["data-wikilink-target"] as
        | string
        | undefined;
      const backlinkCount = parseInt(
        ((props as any)["data-backlink-count"] as string) ?? "0",
        10
      );

      if (isWikilink) {
        return (
          <a
            href={href}
            title={title}
            className={cn(
              "wikilink",
              exists
                ? "text-accent hover:underline"
                : "text-muted-foreground/80 italic underline decoration-dotted decoration-muted-foreground/50"
            )}
            onClick={(e) => {
              if (!exists) return;
              e.preventDefault();
              if (target) onNavigate(target);
            }}
          >
            {children}
            {exists && backlinkCount > 0 && (
              <span
                className="ml-1 inline-flex items-center justify-center min-w-[1.1rem] h-[1.1rem] px-1 rounded-full bg-accent/15 text-accent text-[10px] font-medium leading-none align-baseline"
                aria-label={`${backlinkCount} backlinks`}
              >
                {backlinkCount}
              </span>
            )}
          </a>
        );
      }

      const isExternal =
        href?.startsWith("http://") || href?.startsWith("https://");
      return (
        <a
          href={href}
          title={title}
          target={isExternal ? "_blank" : undefined}
          rel={isExternal ? "noreferrer noopener" : undefined}
        >
          {children}
        </a>
      );
    },
    code: ({ inline, className, children, ...props }: any) => {
      const match = /language-(\w+)/.exec(className || "");
      if (inline || !match) {
        return (
          <code className={className} {...props}>
            {children}
          </code>
        );
      }
      return (
        <SyntaxHighlighter
          PreTag="div"
          language={match[1]}
          style={(isDark ? oneDark : oneLight) as any}
          customStyle={{
            margin: "1.25em 0",
            borderRadius: "8px",
            border: "1px solid var(--border)",
            background: "var(--card)",
            fontSize: "0.875rem",
          }}
        >
          {String(children).replace(/\n$/, "")}
        </SyntaxHighlighter>
      );
    },
  };

  return (
    <motion.article
      key={article.path}
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.18, ease: "easeOut" }}
      className="px-10 py-10 overflow-y-auto h-full"
      data-testid="article-reader"
      data-article-path={article.path}
    >
      <div className="max-w-prose mx-auto">
        <FrontmatterCard article={article} />
        <h1 className="text-3xl font-semibold tracking-tight mb-1 text-foreground font-sans" data-testid="article-title">
          {article.title || article.path.replace(/\.md$/, "")}
        </h1>
        <p className="text-xs text-muted-foreground mb-8 font-mono">
          {article.path}
          {article.updated_at && (
            <>
              <span className="mx-2">·</span>
              updated {new Date(article.updated_at).toLocaleDateString()}
            </>
          )}
        </p>
        <div className="prose-article" data-testid="article-body">
          <ReactMarkdown
            remarkPlugins={[remarkGfm, remarkWikilinks(resolver)]}
            components={components}
          >
            {article.content}
          </ReactMarkdown>
        </div>
      </div>
    </motion.article>
  );
}

function FrontmatterCard({ article }: { article: Article }) {
  const fm = article.frontmatter ?? {};
  const entries = Object.entries(fm).filter(
    ([k]) => !["title", "id"].includes(k)
  );
  if (entries.length === 0) return null;
  return (
    <div className="mb-6 rounded-lg border border-border bg-subtle/50 px-4 py-3">
      <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-xs">
        {entries.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-muted-foreground font-mono uppercase tracking-wide text-[10px]">
              {k}
            </dt>
            <dd className="text-foreground/90 truncate">
              {typeof v === "string" ? v : JSON.stringify(v)}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
