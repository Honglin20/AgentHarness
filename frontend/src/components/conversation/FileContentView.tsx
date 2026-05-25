"use client";

import { useEffect, useRef } from "react";

const EXT_TO_LANG: Record<string, string> = {
  ts: "typescript", tsx: "typescript", js: "javascript", jsx: "javascript",
  py: "python", rb: "ruby", go: "go", rs: "rust", java: "java",
  json: "json", yaml: "yaml", yml: "yaml", toml: "toml",
  md: "markdown", html: "html", css: "css", scss: "scss",
  sh: "bash", bash: "bash", zsh: "bash",
  sql: "sql", xml: "xml", graphql: "graphql",
  c: "c", cpp: "cpp", h: "c", hpp: "cpp",
  swift: "swift", kt: "kotlin", scala: "scala",
  dockerfile: "docker", makefile: "makefile",
};

function guessLang(path: string | undefined): string {
  if (!path) return "plain";
  const base = path.split("/").pop() ?? path;
  const lower = base.toLowerCase();
  if (lower === "dockerfile") return "docker";
  if (lower === "makefile") return "makefile";
  const ext = lower.split(".").pop() ?? "";
  return EXT_TO_LANG[ext] ?? "plain";
}

interface FileContentViewProps {
  content: string;
  filePath?: string;
}

export function FileContentView({ content, filePath }: FileContentViewProps) {
  const codeRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!codeRef.current) return;
    // Lazy-load prismjs highlighting
    import("prismjs").then((Prism) => {
      const lang = guessLang(filePath);
      // Try to load the language grammar
      try {
        const langModule = `prismjs/components/prism-${lang}`;
        import(langModule).catch(() => {});
      } catch {}
      if (codeRef.current && Prism.languages[lang]) {
        codeRef.current.innerHTML = Prism.highlight(content, Prism.languages[lang], lang);
      }
    }).catch(() => {});
  }, [content, filePath]);

  const lines = content.split("\n");

  return (
    <div className="rounded-md border border-app-border overflow-hidden text-xs font-mono">
      {filePath && (
        <div className="bg-muted/50 px-2 py-1 text-xs font-medium text-muted-foreground border-b border-app-border truncate">
          {filePath}
        </div>
      )}
      <div className="max-h-64 overflow-y-auto">
        {lines.map((line, i) => (
          <div key={i} className="flex hover:bg-muted/30">
            <span className="shrink-0 w-8 text-right pr-2 text-muted-foreground/50 select-none border-r border-app-border leading-[18px]">
              {i + 1}
            </span>
            <code
              ref={i === 0 ? codeRef : undefined}
              className="pl-2 whitespace-pre text-xs leading-[18px] flex-1 min-w-0"
            >
              {line || " "}
            </code>
          </div>
        ))}
      </div>
    </div>
  );
}
