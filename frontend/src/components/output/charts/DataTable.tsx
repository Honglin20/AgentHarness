"use client";

import React, { useState, useMemo } from "react";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";

interface DataTableProps {
  columns: string[];
  rows: Record<string, unknown>[];
}

export default function DataTable({ columns, rows }: DataTableProps) {
  const [sortCol, setSortCol] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  const sortedRows = useMemo(() => {
    if (!sortCol) return rows;
    return [...rows].sort((a, b) => {
      const va = a[sortCol];
      const vb = b[sortCol];
      const na = Number(va);
      const nb = Number(vb);
      // Try numeric comparison
      if (!isNaN(na) && !isNaN(nb)) {
        return sortDir === "asc" ? na - nb : nb - na;
      }
      // Fall back to string comparison
      const sa = String(va ?? "");
      const sb = String(vb ?? "");
      return sortDir === "asc" ? sa.localeCompare(sb) : sb.localeCompare(sa);
    });
  }, [rows, sortCol, sortDir]);

  function handleSort(col: string) {
    if (sortCol === col) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortCol(col);
      setSortDir("asc");
    }
  }

  return (
    <Table className="text-xs">
      <TableHeader>
        <TableRow>
          {columns.map((col) => (
            <TableHead
              key={col}
              className="cursor-pointer select-none px-2 py-1 text-xs hover:bg-muted"
              onClick={() => handleSort(col)}
            >
              {col}
              {sortCol === col && (
                <span className="ml-1">{sortDir === "asc" ? "↑" : "↓"}</span>
              )}
            </TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {sortedRows.map((row, i) => (
          <TableRow key={i}>
            {columns.map((col) => (
              <TableCell key={col} className="px-2 py-1 text-xs">
                {String(row[col] ?? "")}
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
