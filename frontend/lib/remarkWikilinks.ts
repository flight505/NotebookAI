import { visit } from "unist-util-visit";
import type { Root, Text, PhrasingContent } from "mdast";

export interface WikilinkResolver {
  (target: string): { path: string; exists: boolean; backlinkCount?: number };
}

const WIKILINK_RE = /\[\[([^\]\n]+?)\]\]/g;

/**
 * Remark plugin that converts `[[name]]` and `[[ml/transformers]]` patterns
 * inside text nodes into mdast `link` nodes with custom data so the React
 * renderer can highlight existing-vs-missing targets and show backlink badges.
 */
export function remarkWikilinks(resolver: WikilinkResolver) {
  return function plugin() {
    return function transform(tree: Root) {
      visit(tree, "text", (node: Text, index, parent) => {
        if (!parent || typeof index !== "number") return;
        if (!node.value.includes("[[")) return;

        const out: PhrasingContent[] = [];
        let last = 0;
        let m: RegExpExecArray | null;
        WIKILINK_RE.lastIndex = 0;
        while ((m = WIKILINK_RE.exec(node.value)) !== null) {
          if (m.index > last) {
            out.push({
              type: "text",
              value: node.value.slice(last, m.index),
            } as Text);
          }
          const inner = m[1].trim();
          const [target, alias] = inner.split("|").map((s) => s.trim());
          const resolved = resolver(target);
          const display = alias ?? target;
          out.push({
            type: "link",
            url: resolved.exists
              ? `/read?article=${encodeURIComponent(resolved.path)}`
              : `#wikilink-missing-${encodeURIComponent(target)}`,
            title: resolved.exists
              ? `→ ${resolved.path}`
              : `Missing: ${target}`,
            children: [{ type: "text", value: display } as Text],
            data: {
              hProperties: {
                className: resolved.exists
                  ? "wikilink wikilink-exists"
                  : "wikilink wikilink-missing",
                "data-wikilink-target": resolved.path,
                "data-wikilink-exists": String(resolved.exists),
                "data-backlink-count": String(resolved.backlinkCount ?? 0),
              },
            },
          });
          last = m.index + m[0].length;
        }
        if (last < node.value.length) {
          out.push({ type: "text", value: node.value.slice(last) } as Text);
        }
        if (out.length > 0) {
          (parent.children as PhrasingContent[]).splice(index, 1, ...out);
          return index + out.length;
        }
      });
    };
  };
}

export function slugify(text: string): string {
  return text
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9\s-]/g, "")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-");
}
