"use client";

interface DiffViewProps {
  oldText: string;
  newText: string;
  fileName?: string;
  mode: "create" | "edit";
}

function lineNum(n: number, w = 3): string {
  return String(n).padStart(w, " ");
}

export function DiffView({ oldText, newText, fileName, mode }: DiffViewProps) {
  if (mode === "create" || !oldText) {
    const lines = newText.split("\n");
    return (
      <div className="rounded-md border border-app-border overflow-hidden text-xs font-mono">
        {fileName && (
          <div className="bg-emerald-500/10 px-2 py-1 text-xs font-medium text-emerald-700 border-b border-app-border">
            + {fileName}
          </div>
        )}
        <div className="max-h-64 overflow-y-auto">
          {lines.map((line, i) => (
            <div key={i} className="flex hover:bg-emerald-500/5">
              <span className="shrink-0 w-8 text-right pr-2 text-muted-foreground/50 select-none border-r border-app-border">
                {lineNum(i + 1)}
              </span>
              <span className="pl-2 bg-emerald-500/10 text-emerald-800 whitespace-pre">{line || " "}</span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  const oldLines = oldText.split("\n");
  const newLines = newText.split("\n");
  const maxLen = Math.max(oldLines.length, newLines.length);

  return (
    <div className="rounded-md border border-app-border overflow-hidden text-xs font-mono">
      {fileName && (
        <div className="bg-blue-500/10 px-2 py-1 text-xs font-medium text-blue-700 border-b border-app-border">
          ~ {fileName}
        </div>
      )}
      <div className="max-h-64 overflow-y-auto">
        {Array.from({ length: maxLen }).map((_, i) => {
          const oldLine = i < oldLines.length ? oldLines[i] : undefined;
          const newLine = i < newLines.length ? newLines[i] : undefined;
          const isRemoved = oldLine !== undefined && (newLine === undefined || oldLine !== newLine);
          const isAdded = newLine !== undefined && (oldLine === undefined || oldLine !== newLine);

          if (isRemoved && isAdded) {
            return (
              <div key={i}>
                <div className="flex bg-red-500/10">
                  <span className="shrink-0 w-8 text-right pr-2 text-muted-foreground/50 select-none border-r border-app-border">
                    {lineNum(i + 1)}
                  </span>
                  <span className="pl-2 text-red-800 whitespace-pre">- {oldLine || " "}</span>
                </div>
                <div className="flex bg-emerald-500/10">
                  <span className="shrink-0 w-8 text-right pr-2 text-muted-foreground/50 select-none border-r border-app-border">
                    {lineNum(i + 1)}
                  </span>
                  <span className="pl-2 text-emerald-800 whitespace-pre">+ {newLine || " "}</span>
                </div>
              </div>
            );
          }
          if (isRemoved) {
            return (
              <div key={i} className="flex bg-red-500/10">
                <span className="shrink-0 w-8 text-right pr-2 text-muted-foreground/50 select-none border-r border-app-border">
                  {lineNum(i + 1)}
                </span>
                <span className="pl-2 text-red-800 whitespace-pre">- {oldLine || " "}</span>
              </div>
            );
          }
          if (isAdded) {
            return (
              <div key={i} className="flex bg-emerald-500/10">
                <span className="shrink-0 w-8 text-right pr-2 text-muted-foreground/50 select-none border-r border-app-border">
                  {lineNum(i + 1)}
                </span>
                <span className="pl-2 text-emerald-800 whitespace-pre">+ {newLine || " "}</span>
              </div>
            );
          }
          return (
            <div key={i} className="flex">
              <span className="shrink-0 w-8 text-right pr-2 text-muted-foreground/50 select-none border-r border-app-border">
                {lineNum(i + 1)}
              </span>
              <span className="pl-2 whitespace-pre text-muted-foreground">  {oldLine || " "}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
