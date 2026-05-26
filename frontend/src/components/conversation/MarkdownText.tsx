"use client";

import { memo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import rehypePrism from "rehype-prism-plus";

interface MarkdownTextProps {
  children: string;
  className?: string;
}

/**
 * Render an agent message body as Markdown with GFM tables, KaTeX math,
 * and Prism code highlighting. Memoized — re-rendering on every streaming
 * delta is expensive.
 */
function MarkdownTextImpl({ children, className }: MarkdownTextProps) {
  return (
    <div className={`markdown-body text-sm leading-relaxed ${className ?? ""}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex, [rehypePrism, { ignoreMissing: true }]]}
        components={{
          // Tighten default Tailwind reset overrides so paragraphs and lists
          // don't get crushed; tables get a basic border.
          p: ({ children }) => <p className="my-2 whitespace-pre-wrap">{children}</p>,
          ul: ({ children }) => <ul className="my-2 ml-5 list-disc">{children}</ul>,
          ol: ({ children }) => <ol className="my-2 ml-5 list-decimal">{children}</ol>,
          li: ({ children }) => <li className="my-0.5">{children}</li>,
          h1: ({ children }) => <h1 className="mt-3 mb-2 text-base font-semibold">{children}</h1>,
          h2: ({ children }) => <h2 className="mt-3 mb-2 text-sm font-semibold">{children}</h2>,
          h3: ({ children }) => <h3 className="mt-2 mb-1.5 text-sm font-semibold">{children}</h3>,
          code: ({ inline, className, children, ...props }: { inline?: boolean; className?: string; children?: React.ReactNode }) =>
            inline ? (
              <code className="rounded bg-muted px-1 py-0.5 font-mono text-[12px]" {...props}>
                {children}
              </code>
            ) : (
              <code className={`${className ?? ""} font-mono text-[12px]`} {...props}>
                {children}
              </code>
            ),
          pre: ({ children }) => (
            <pre className="my-2 overflow-x-auto rounded-md bg-muted p-2 text-[12px]">{children}</pre>
          ),
          table: ({ children }) => (
            <div className="my-2 overflow-x-auto">
              <table className="border-collapse text-xs">{children}</table>
            </div>
          ),
          th: ({ children }) => (
            <th className="border border-app-border bg-muted px-2 py-1 text-left font-medium">{children}</th>
          ),
          td: ({ children }) => <td className="border border-app-border px-2 py-1">{children}</td>,
          a: ({ children, href }) => (
            <a href={href} target="_blank" rel="noreferrer" className="text-blue-600 underline">
              {children}
            </a>
          ),
          blockquote: ({ children }) => (
            <blockquote className="my-2 border-l-2 border-app-border pl-3 text-muted-foreground">
              {children}
            </blockquote>
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}

export const MarkdownText = memo(MarkdownTextImpl);
