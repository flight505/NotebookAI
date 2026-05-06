"use client";

import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import type { Article } from "@/lib/api";

interface GraphViewProps {
  articles: Article[];
  currentPath: string | null;
  onNavigate: (path: string) => void;
}

interface Node {
  id: string;
  title: string;
  x: number;
  y: number;
  degree: number;
}
interface Edge {
  source: string;
  target: string;
}

function buildGraph(articles: Article[]): { nodes: Node[]; edges: Edge[] } {
  const byPath = new Map<string, Article>();
  for (const a of articles) byPath.set(a.path, a);
  const byBase = new Map<string, Article>();
  for (const a of articles) {
    const base = a.path.split("/").pop()?.replace(/\.md$/, "");
    if (base) byBase.set(base.toLowerCase(), a);
  }

  const edgeSet = new Set<string>();
  const edges: Edge[] = [];
  const degree = new Map<string, number>();

  for (const a of articles) {
    for (const out of a.outlinks ?? []) {
      const target =
        byPath.get(out) ||
        byPath.get(out + ".md") ||
        byBase.get(out.toLowerCase());
      if (!target || target.path === a.path) continue;
      const key = `${a.path}→${target.path}`;
      if (edgeSet.has(key)) continue;
      edgeSet.add(key);
      edges.push({ source: a.path, target: target.path });
      degree.set(a.path, (degree.get(a.path) ?? 0) + 1);
      degree.set(target.path, (degree.get(target.path) ?? 0) + 1);
    }
  }

  const nodes: Node[] = articles.map((a) => ({
    id: a.path,
    title: a.title || a.path.replace(/\.md$/, ""),
    x: 0,
    y: 0,
    degree: degree.get(a.path) ?? 0,
  }));

  return { nodes, edges };
}

/**
 * Deterministic, dependency-free force-directed layout.
 * Few iterations + tiny graphs = good enough; runs once per articles change.
 */
function layout(
  nodes: Node[],
  edges: Edge[],
  width: number,
  height: number
): Node[] {
  if (nodes.length === 0) return nodes;
  // Seeded pseudo-random so it's deterministic per article set.
  let seed = 1;
  const rand = () => {
    seed = (seed * 9301 + 49297) % 233280;
    return seed / 233280;
  };

  const positioned = nodes.map((n) => ({
    ...n,
    x: rand() * width,
    y: rand() * height,
    vx: 0,
    vy: 0,
  }));

  const idx = new Map<string, number>();
  positioned.forEach((n, i) => idx.set(n.id, i));

  const iterations = Math.min(140, 40 + nodes.length * 3);
  const idealLen = Math.max(80, Math.min(180, 600 / Math.sqrt(nodes.length)));
  const repulsion = idealLen * idealLen * 0.7;
  const center = { x: width / 2, y: height / 2 };

  for (let iter = 0; iter < iterations; iter++) {
    const cooling = 1 - iter / iterations;
    // Repulsive forces.
    for (let i = 0; i < positioned.length; i++) {
      for (let j = i + 1; j < positioned.length; j++) {
        const a = positioned[i];
        const b = positioned[j];
        let dx = a.x - b.x;
        let dy = a.y - b.y;
        let d2 = dx * dx + dy * dy;
        if (d2 < 0.01) {
          dx = rand() - 0.5;
          dy = rand() - 0.5;
          d2 = 1;
        }
        const force = repulsion / d2;
        const d = Math.sqrt(d2);
        const fx = (dx / d) * force;
        const fy = (dy / d) * force;
        a.vx += fx;
        a.vy += fy;
        b.vx -= fx;
        b.vy -= fy;
      }
    }
    // Spring forces.
    for (const e of edges) {
      const a = positioned[idx.get(e.source)!];
      const b = positioned[idx.get(e.target)!];
      if (!a || !b) continue;
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const d = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const force = (d - idealLen) * 0.08;
      const fx = (dx / d) * force;
      const fy = (dy / d) * force;
      a.vx += fx;
      a.vy += fy;
      b.vx -= fx;
      b.vy -= fy;
    }
    // Gravity toward center.
    for (const n of positioned) {
      n.vx += (center.x - n.x) * 0.01;
      n.vy += (center.y - n.y) * 0.01;
    }
    // Apply with cooling.
    const damp = 0.85;
    for (const n of positioned) {
      n.vx *= damp;
      n.vy *= damp;
      n.x += n.vx * cooling;
      n.y += n.vy * cooling;
      n.x = Math.max(20, Math.min(width - 20, n.x));
      n.y = Math.max(20, Math.min(height - 20, n.y));
    }
  }

  return positioned;
}

export function GraphView({
  articles,
  currentPath,
  onNavigate,
}: GraphViewProps) {
  const W = 320;
  const H = 320;
  const [hovered, setHovered] = useState<string | null>(null);

  const { nodes, edges } = useMemo(() => {
    const { nodes: rawNodes, edges } = buildGraph(articles);
    const positioned = layout(rawNodes, edges, W, H);
    return { nodes: positioned, edges };
  }, [articles]);

  if (articles.length === 0) {
    return (
      <div className="p-6 text-center text-xs text-muted-foreground">
        Graph appears once you have articles with wikilinks.
      </div>
    );
  }

  const nodeById = new Map(nodes.map((n) => [n.id, n]));
  const focused = hovered ?? currentPath;
  const neighborSet = new Set<string>();
  if (focused) {
    neighborSet.add(focused);
    for (const e of edges) {
      if (e.source === focused) neighborSet.add(e.target);
      if (e.target === focused) neighborSet.add(e.source);
    }
  }

  return (
    <div className="px-2 py-2">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full h-auto rounded-md border border-border bg-subtle/30"
        role="img"
        aria-label="Article graph"
      >
        {edges.map((e, i) => {
          const a = nodeById.get(e.source);
          const b = nodeById.get(e.target);
          if (!a || !b) return null;
          const dim =
            focused !== null &&
            !(neighborSet.has(e.source) && neighborSet.has(e.target));
          return (
            <line
              key={i}
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
              stroke="var(--border)"
              strokeWidth={dim ? 0.6 : 1}
              opacity={dim ? 0.3 : 0.7}
            />
          );
        })}
        {nodes.map((n) => {
          const isCurrent = n.id === currentPath;
          const dim = focused !== null && !neighborSet.has(n.id);
          const r = Math.max(3, Math.min(7, 3 + n.degree * 0.7));
          return (
            <g
              key={n.id}
              transform={`translate(${n.x}, ${n.y})`}
              onMouseEnter={() => setHovered(n.id)}
              onMouseLeave={() => setHovered(null)}
              onClick={() => onNavigate(n.id)}
              style={{ cursor: "pointer" }}
              opacity={dim ? 0.25 : 1}
            >
              <motion.circle
                r={r}
                fill={isCurrent ? "var(--accent)" : "var(--card)"}
                stroke={isCurrent ? "var(--accent)" : "var(--muted-foreground)"}
                strokeWidth={isCurrent ? 2 : 1}
                whileHover={{ scale: 1.3 }}
                transition={{ duration: 0.15 }}
              />
              {(hovered === n.id || isCurrent) && (
                <text
                  x={r + 4}
                  y={3}
                  fontSize="9"
                  fill="var(--foreground)"
                  className="pointer-events-none select-none"
                  style={{ fontFamily: "var(--font-sans)" }}
                >
                  {truncate(n.title, 20)}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <div className="mt-2 px-1 flex items-center justify-between text-[10px] text-muted-foreground">
        <span>{nodes.length} nodes</span>
        <span>{edges.length} links</span>
      </div>
    </div>
  );
}

function truncate(s: string, n: number) {
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}
