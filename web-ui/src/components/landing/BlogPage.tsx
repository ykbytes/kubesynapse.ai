import { useState, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import {
  ArrowLeft, Calendar, Clock, Tag, User, ChevronRight, Search, BookOpen,
} from "lucide-react";

// ─── Types ───

interface BlogFrontmatter {
  title: string;
  date: string;
  author: string;
  tags: string[];
  summary: string;
  slug: string;
  published: boolean;
}

interface BlogPost {
  frontmatter: BlogFrontmatter;
  content: string;
}

// ─── Parse frontmatter from markdown ───

function parseFrontmatter(raw: string): { frontmatter: Record<string, unknown>; content: string } {
  const normalized = raw.replace(/\r\n/g, "\n");
  const match = normalized.match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/);
  if (!match) return { frontmatter: {}, content: normalized };

  const yamlBlock = match[1];
  const content = match[2].trim();
  const frontmatter: Record<string, unknown> = {};

  for (const line of yamlBlock.split("\n")) {
    const colonIdx = line.indexOf(":");
    if (colonIdx === -1) continue;
    const key = line.slice(0, colonIdx).trim();
    let value: unknown = line.slice(colonIdx + 1).trim();

    if (typeof value === "string" && value.startsWith('"') && value.endsWith('"')) {
      value = (value as string).slice(1, -1);
    }
    if (typeof value === "string" && (value as string).startsWith("[")) {
      try { value = JSON.parse((value as string).replace(/'/g, '"')); } catch { /* keep string */ }
    }
    if (value === "true") value = true;
    if (value === "false") value = false;

    frontmatter[key] = value;
  }

  return { frontmatter, content };
}

// ─── Import all markdown files at build time ───

const postModules = import.meta.glob("../content/blog/*.md", { eager: true, query: "?raw", import: "default" }) as Record<string, string>;

function loadPosts(): BlogPost[] {
  const posts: BlogPost[] = [];
  for (const [, raw] of Object.entries(postModules)) {
    const { frontmatter, content } = parseFrontmatter(raw);
    const fm = frontmatter as unknown as BlogFrontmatter;
    if (!fm.title || !fm.slug || !Array.isArray(fm.tags)) continue;
    if (fm.published !== false) {
      posts.push({ frontmatter: fm, content });
    }
  }
  posts.sort((a, b) => b.frontmatter.date.localeCompare(a.frontmatter.date));
  return posts;
}

function readingTime(content: string): number {
  return Math.max(1, Math.round(content.split(/\s+/).length / 220));
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr + "T00:00:00");
  return d.toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric" });
}

// ─── Markdown components ───
// Inline styles guarantee rendering regardless of Tailwind JIT compilation.

const blogMarkdownComponents = {
  h1: ({ children }: { children?: React.ReactNode }) => (
    <h1 style={{ color: "#fff" }} className="mt-10 mb-5 text-3xl font-bold leading-tight">{children}</h1>
  ),
  h2: ({ children }: { children?: React.ReactNode }) => (
    <h2 style={{ color: "#f0f0f0" }} className="mt-9 mb-4 text-2xl font-bold leading-snug">{children}</h2>
  ),
  h3: ({ children }: { children?: React.ReactNode }) => (
    <h3 style={{ color: "#e8e8e8" }} className="mt-7 mb-3 text-xl font-semibold">{children}</h3>
  ),
  p: ({ children }: { children?: React.ReactNode }) => (
    <p style={{ color: "#c8ccd0" }} className="mb-5 text-[15.5px] leading-[1.85]">{children}</p>
  ),
  ul: ({ children }: { children?: React.ReactNode }) => (
    <ul style={{ color: "#c8ccd0" }} className="mb-5 ml-6 list-disc space-y-2 text-[15.5px]">{children}</ul>
  ),
  ol: ({ children }: { children?: React.ReactNode }) => (
    <ol style={{ color: "#c8ccd0" }} className="mb-5 ml-6 list-decimal space-y-2 text-[15.5px]">{children}</ol>
  ),
  li: ({ children }: { children?: React.ReactNode }) => (
    <li style={{ color: "#c8ccd0" }} className="leading-[1.8] pl-1">{children}</li>
  ),
  strong: ({ children }: { children?: React.ReactNode }) => (
    <strong style={{ color: "#ffffff" }} className="font-semibold">{children}</strong>
  ),
  em: ({ children }: { children?: React.ReactNode }) => (
    <em style={{ color: "#b8bcc0" }} className="italic">{children}</em>
  ),
  a: ({ href, children }: { href?: string; children?: React.ReactNode }) => (
    <a
      href={href}
      style={{ color: "#5eead4" }}
      className="underline underline-offset-3 decoration-teal-400/40 transition-colors hover:text-teal-300"
      target="_blank"
      rel="noopener noreferrer"
    >
      {children}
    </a>
  ),
  blockquote: ({ children }: { children?: React.ReactNode }) => (
    <blockquote
      style={{ borderLeftColor: "#5eead4", background: "rgba(30,35,50,0.6)", color: "#c8ccd0" }}
      className="my-5 border-l-[3px] rounded-r-lg px-5 py-4"
    >
      {children}
    </blockquote>
  ),
  pre: ({ children }: { children?: React.ReactNode }) => (
    <pre
      style={{ background: "#0d1117", borderColor: "#2a2f3a" }}
      className="my-5 overflow-x-auto rounded-xl border p-5 text-sm"
    >
      {children}
    </pre>
  ),
  code: ({ className, children }: { className?: string; children?: React.ReactNode }) => {
    if (className) {
      return <code className={`${className} text-sm`}>{children}</code>;
    }
    return (
      <code
        style={{ background: "#1e2433", color: "#5eead4" }}
        className="rounded-md px-1.5 py-0.5 text-[13.5px] font-medium"
      >
        {children}
      </code>
    );
  },
  hr: () => (
    <hr style={{ borderColor: "#2a2f3a" }} className="my-10" />
  ),
};

// ─── Blog List View ───

function BlogList({
  posts,
  onSelect,
  onBack,
}: {
  posts: BlogPost[];
  onSelect: (post: BlogPost) => void;
  onBack: () => void;
}) {
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedTag, setSelectedTag] = useState<string | null>(null);

  const allTags = useMemo(() => {
    const tags = new Set<string>();
    posts.forEach((p) => p.frontmatter.tags.forEach((t) => tags.add(t)));
    return Array.from(tags).sort();
  }, [posts]);

  const filtered = useMemo(() => {
    return posts.filter((p) => {
      const matchesSearch =
        !searchQuery ||
        p.frontmatter.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
        p.frontmatter.summary.toLowerCase().includes(searchQuery.toLowerCase());
      const matchesTag = !selectedTag || p.frontmatter.tags.includes(selectedTag);
      return matchesSearch && matchesTag;
    });
  }, [posts, searchQuery, selectedTag]);

  return (
    <div className="mx-auto max-w-4xl px-6 py-10">
      {/* Back link */}
      <button
        onClick={onBack}
        className="mb-8 flex items-center gap-2 text-sm font-medium transition-colors"
        style={{ color: "#9ca3af" }}
        onMouseEnter={(e) => (e.currentTarget.style.color = "#5eead4")}
        onMouseLeave={(e) => (e.currentTarget.style.color = "#9ca3af")}
      >
        <ArrowLeft className="h-4 w-4" />
        Back to Home
      </button>

      {/* Page header */}
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="mb-10"
      >
        <div className="flex items-center gap-3 mb-2">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl" style={{ background: "rgba(94,234,212,0.12)" }}>
            <BookOpen className="h-5 w-5" style={{ color: "#5eead4" }} />
          </div>
          <h1 style={{ color: "#ffffff" }} className="text-4xl font-extrabold tracking-tight">
            Blog
          </h1>
        </div>
        <p style={{ color: "#9ca3af" }} className="mt-2 text-base leading-relaxed">
          Engineering journal — feature deep-dives, architecture decisions, and roadmap.
        </p>
      </motion.div>

      {/* Search + tag bar */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, delay: 0.1 }}
        className="mb-8 space-y-4"
      >
        <div className="relative">
          <Search className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2" style={{ color: "#6b7280" }} />
          <input
            type="text"
            placeholder="Search posts..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full rounded-xl py-3 pl-11 pr-4 text-sm outline-none transition-all"
            style={{
              background: "#1a1f2e",
              border: "1px solid #2a3040",
              color: "#e5e7eb",
            }}
            onFocus={(e) => (e.currentTarget.style.borderColor = "#5eead4")}
            onBlur={(e) => (e.currentTarget.style.borderColor = "#2a3040")}
          />
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => setSelectedTag(null)}
            className="rounded-full px-3.5 py-1.5 text-xs font-semibold transition-all"
            style={
              !selectedTag
                ? { background: "rgba(94,234,212,0.15)", color: "#5eead4", boxShadow: "inset 0 0 0 1px rgba(94,234,212,0.3)" }
                : { background: "#1a1f2e", color: "#9ca3af" }
            }
          >
            All
          </button>
          {allTags.map((tag) => (
            <button
              key={tag}
              onClick={() => setSelectedTag(selectedTag === tag ? null : tag)}
              className="rounded-full px-3.5 py-1.5 text-xs font-semibold transition-all"
              style={
                selectedTag === tag
                  ? { background: "rgba(94,234,212,0.15)", color: "#5eead4", boxShadow: "inset 0 0 0 1px rgba(94,234,212,0.3)" }
                  : { background: "#1a1f2e", color: "#9ca3af" }
              }
            >
              {tag}
            </button>
          ))}
        </div>
      </motion.div>

      {/* Featured post (first card, bigger) */}
      {filtered.length > 0 && (
        <motion.article
          key={filtered[0].frontmatter.slug + "-hero"}
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.15 }}
          onClick={() => onSelect(filtered[0])}
          className="group mb-6 cursor-pointer rounded-2xl p-7 transition-all hover:-translate-y-0.5"
          style={{
            background: "linear-gradient(135deg, #1a1f2e 0%, #141825 100%)",
            border: "1px solid #2a3040",
          }}
          onMouseEnter={(e) => (e.currentTarget.style.borderColor = "rgba(94,234,212,0.35)")}
          onMouseLeave={(e) => (e.currentTarget.style.borderColor = "#2a3040")}
        >
          <div className="mb-3 flex items-center gap-2">
            <span className="rounded-md px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider" style={{ background: "rgba(94,234,212,0.12)", color: "#5eead4" }}>
              Latest
            </span>
            {filtered[0].frontmatter.tags.map((tag) => (
              <span
                key={tag}
                className="rounded-full px-2.5 py-0.5 text-[11px] font-medium"
                style={{ background: "#1e2433", color: "#9ca3af" }}
              >
                {tag}
              </span>
            ))}
          </div>

          <h2 className="text-2xl font-bold transition-colors sm:text-3xl" style={{ color: "#f9fafb" }}>
            <span className="group-hover:underline group-hover:decoration-teal-400/40 group-hover:underline-offset-4">
              {filtered[0].frontmatter.title}
            </span>
          </h2>

          <p className="mt-3 text-[15px] leading-relaxed" style={{ color: "#b0b8c4" }}>
            {filtered[0].frontmatter.summary}
          </p>

          <div className="mt-5 flex items-center gap-5 text-xs" style={{ color: "#6b7280" }}>
            <span className="flex items-center gap-1.5">
              <Calendar className="h-3.5 w-3.5" />
              {formatDate(filtered[0].frontmatter.date)}
            </span>
            <span className="flex items-center gap-1.5">
              <User className="h-3.5 w-3.5" />
              {filtered[0].frontmatter.author}
            </span>
            <span className="flex items-center gap-1.5">
              <Clock className="h-3.5 w-3.5" />
              {readingTime(filtered[0].content)} min read
            </span>
            <span className="ml-auto flex items-center gap-1 text-xs font-medium transition-colors" style={{ color: "#5eead4" }}>
              Read more <ChevronRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-1" />
            </span>
          </div>
        </motion.article>
      )}

      {/* Remaining post cards */}
      <div className="space-y-4">
        {filtered.slice(1).map((post, i) => (
          <motion.article
            key={post.frontmatter.slug}
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35, delay: 0.2 + i * 0.05 }}
            onClick={() => onSelect(post)}
            className="group flex cursor-pointer items-start gap-5 rounded-xl p-5 transition-all hover:-translate-y-0.5"
            style={{
              background: "#141825",
              border: "1px solid #222738",
            }}
            onMouseEnter={(e) => (e.currentTarget.style.borderColor = "rgba(94,234,212,0.25)")}
            onMouseLeave={(e) => (e.currentTarget.style.borderColor = "#222738")}
          >
            {/* Left: content */}
            <div className="flex-1 min-w-0">
              <div className="mb-2 flex flex-wrap gap-1.5">
                {post.frontmatter.tags.map((tag) => (
                  <span
                    key={tag}
                    className="rounded-full px-2 py-0.5 text-[10px] font-medium"
                    style={{ background: "#1e2433", color: "#8b95a5" }}
                  >
                    {tag}
                  </span>
                ))}
              </div>
              <h3 className="text-lg font-bold transition-colors" style={{ color: "#e5e7eb" }}>
                <span className="group-hover:underline group-hover:decoration-teal-400/40 group-hover:underline-offset-3">
                  {post.frontmatter.title}
                </span>
              </h3>
              <p className="mt-1.5 text-sm leading-relaxed line-clamp-2" style={{ color: "#8b95a5" }}>
                {post.frontmatter.summary}
              </p>
              <div className="mt-3 flex items-center gap-4 text-[11px]" style={{ color: "#6b7280" }}>
                <span className="flex items-center gap-1">
                  <Calendar className="h-3 w-3" />
                  {formatDate(post.frontmatter.date)}
                </span>
                <span className="flex items-center gap-1">
                  <Clock className="h-3 w-3" />
                  {readingTime(post.content)} min
                </span>
              </div>
            </div>

            {/* Right: arrow */}
            <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg transition-all" style={{ background: "#1e2433" }}>
              <ChevronRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" style={{ color: "#5eead4" }} />
            </div>
          </motion.article>
        ))}
      </div>

      {filtered.length === 0 && (
        <div className="py-20 text-center text-sm" style={{ color: "#6b7280" }}>
          No posts found matching your search.
        </div>
      )}
    </div>
  );
}

// ─── Blog Post View ───

function BlogPostView({
  post,
  onBack,
}: {
  post: BlogPost;
  onBack: () => void;
}) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.4 }}
      className="mx-auto max-w-3xl px-6 py-10"
    >
      {/* Back button */}
      <button
        onClick={onBack}
        className="mb-8 flex items-center gap-2 text-sm font-medium transition-colors"
        style={{ color: "#9ca3af" }}
        onMouseEnter={(e) => (e.currentTarget.style.color = "#5eead4")}
        onMouseLeave={(e) => (e.currentTarget.style.color = "#9ca3af")}
      >
        <ArrowLeft className="h-4 w-4" />
        Back to all posts
      </button>

      {/* Header */}
      <header className="mb-10">
        <div className="mb-4 flex flex-wrap gap-2">
          {post.frontmatter.tags.map((tag) => (
            <span
              key={tag}
              className="inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium"
              style={{ background: "rgba(94,234,212,0.1)", color: "#5eead4" }}
            >
              <Tag className="h-3 w-3" />
              {tag}
            </span>
          ))}
        </div>

        <h1 style={{ color: "#ffffff" }} className="text-3xl font-extrabold tracking-tight sm:text-4xl md:text-5xl leading-tight">
          {post.frontmatter.title}
        </h1>

        <div className="mt-5 flex flex-wrap items-center gap-5 text-sm" style={{ color: "#8b95a5" }}>
          <span className="flex items-center gap-1.5">
            <User className="h-4 w-4" />
            {post.frontmatter.author}
          </span>
          <span className="flex items-center gap-1.5">
            <Calendar className="h-4 w-4" />
            {formatDate(post.frontmatter.date)}
          </span>
          <span className="flex items-center gap-1.5">
            <Clock className="h-4 w-4" />
            {readingTime(post.content)} min read
          </span>
        </div>

        <hr style={{ borderColor: "#2a3040" }} className="mt-8" />
      </header>

      {/* Content */}
      <article>
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          rehypePlugins={[rehypeHighlight]}
          components={blogMarkdownComponents as never}
        >
          {post.content}
        </ReactMarkdown>
      </article>

      {/* Footer */}
      <footer className="mt-16 pt-8" style={{ borderTop: "1px solid #2a3040" }}>
        <button
          onClick={onBack}
          className="flex items-center gap-2 text-sm font-medium transition-colors"
          style={{ color: "#9ca3af" }}
          onMouseEnter={(e) => (e.currentTarget.style.color = "#5eead4")}
          onMouseLeave={(e) => (e.currentTarget.style.color = "#9ca3af")}
        >
          <ArrowLeft className="h-4 w-4" />
          Back to all posts
        </button>
      </footer>
    </motion.div>
  );
}

// ─── Main BlogPage ───

export function BlogPage({ onBack }: { onBack: () => void }) {
  const posts = useMemo(() => loadPosts(), []);
  const [selectedPost, setSelectedPost] = useState<BlogPost | null>(null);

  return (
    <div className="h-full overflow-y-auto">
      <AnimatePresence mode="wait">
        {selectedPost ? (
          <BlogPostView
            key="post"
            post={selectedPost}
            onBack={() => setSelectedPost(null)}
          />
        ) : (
          <BlogList
            key="list"
            posts={posts}
            onSelect={setSelectedPost}
            onBack={onBack}
          />
        )}
      </AnimatePresence>
    </div>
  );
}

export default BlogPage;
