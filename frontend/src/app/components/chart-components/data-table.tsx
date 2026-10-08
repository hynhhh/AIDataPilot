"use client";

import { useState } from "react";
import { ChevronUp, ChevronDown } from "lucide-react";

interface DataTableProps {
  columns: string[];
  rows: Record<string, any>[];
}

export function DataTableComponent({ columns, rows }: DataTableProps) {
  const [sortCol, setSortCol] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  if (!rows || rows.length === 0) {
    return <div className="text-center text-sm text-gray-400 py-8">No data</div>;
  }

  const sortedRows = sortCol
    ? [...rows].sort((a, b) => {
        const aVal = a[sortCol];
        const bVal = b[sortCol];
        const cmp =
          typeof aVal === "number" && typeof bVal === "number"
            ? aVal - bVal
            : String(aVal ?? "").localeCompare(String(bVal ?? ""));
        return sortDir === "asc" ? cmp : -cmp;
      })
    : rows;

  const handleSort = (col: string) => {
    if (sortCol === col) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortCol(col);
      setSortDir("asc");
    }
  };

  return (
    <div className="overflow-x-auto rounded-lg border border-[var(--border-base)]">
      <table className="w-full text-xs font-['Plus_Jakarta_Sans']">
        <thead className="bg-[var(--bg-muted)]">
          <tr>
            {columns.map((col) => (
              <th
                key={col}
                onClick={() => handleSort(col)}
                className={`text-left px-3 py-2 font-semibold text-[var(--text-primary)] border-b border-[var(--border-base)] cursor-pointer hover:bg-[var(--bg-subtle)] transition-colors
                  ${sortCol === col ? "bg-[var(--brand-accent)]/10" : ""}`}
              >
                <div className="flex items-center gap-1">
                  {col}
                  {sortCol === col && (
                    sortDir === "asc" ? <ChevronUp size={12} /> : <ChevronDown size={12} />
                  )}
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sortedRows.map((row, i) => (
            <tr key={i} className={i % 2 === 0 ? "bg-[var(--bg-surface)]" : "bg-[var(--bg-muted)]"}>
              {columns.map((col) => (
                <td key={col} className="px-3 py-2 text-[var(--text-secondary)] border-b border-[var(--border-base)]/50">
                  {row[col] !== null && row[col] !== undefined ? String(row[col]) : "—"}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default DataTableComponent;
