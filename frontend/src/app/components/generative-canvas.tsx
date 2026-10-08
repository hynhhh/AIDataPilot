"use client";

import { useState } from "react";
import { ChevronDown, FileText } from "lucide-react";
import { LineChartComponent } from "./chart-components/line-chart";
import { BarChartComponent } from "./chart-components/bar-chart";
import { PieChartComponent } from "./chart-components/pie-chart";
import { DataTableComponent } from "./chart-components/data-table";
import { InsightCardComponent } from "./chart-components/insight-card";
import { SectionTitle } from "./chart-components/section-title";
import type { CanvasState } from "../page";

interface GenerativeCanvasProps {
  canvasState: CanvasState;
}

export function GenerativeCanvas({ canvasState }: GenerativeCanvasProps) {
  const { chart, analysis, insights, table, sql } = canvasState;
  const [showSql, setShowSql] = useState(false);

  return (
    <div className="h-full overflow-auto">
      <div className="p-4 space-y-4 max-w-none">
        {/* Empty State */}
        {!chart && !analysis && !insights?.length && !table && (
          <div className="flex flex-col items-center justify-center h-[60vh] text-center space-y-4">
            <div className="w-16 h-16 rounded-full bg-[var(--brand-accent)]/20 flex items-center justify-center">
              <span className="text-3xl">{'🪁'}</span>
            </div>
            <div>
              <p className="text-lg font-semibold text-[var(--text-primary)] font-['Roobert']">Ask Data</p>
              <p className="text-sm text-[var(--text-secondary)] font-['Plus_Jakarta_Sans'] mt-1">
                Ask a question to get charts, tables, and insights
              </p>
            </div>
          </div>
        )}

        {/* Analysis Text */}
        {analysis && (
          <div className="rounded-xl border border-[var(--border-base)] bg-[var(--bg-surface)] p-4">
            <p className="text-sm text-[var(--text-primary)] font-['Plus_Jakarta_Sans'] leading-relaxed whitespace-pre-wrap">
              {analysis}
            </p>
          </div>
        )}

        {/* Chart Area */}
        {chart && (
          <div className="rounded-xl border border-[var(--border-base)] bg-[var(--bg-surface)] p-4">
            {chart.type === "table" ? (
              <div>
                <SectionTitle title="Data Table" />
                <div className="mt-3">
                  {chart.data && chart.data.length > 0 ? (
                    <DataTableComponent
                      columns={Object.keys(chart.data[0])}
                      rows={chart.data}
                    />
                  ) : (
                    <div className="text-center text-sm text-gray-400 py-6">No data</div>
                  )}
                </div>
              </div>
            ) : chart.type === "metric" ? (
              <div>
                <SectionTitle title={chart.label || "Metric"} />
                <div className="mt-3 flex items-center gap-4">
                  <div className="flex-1 bg-gradient-to-br from-[#1B606F] to-[#0d4a5a] rounded-xl p-6 text-center">
                    <p className="text-xs text-white/70 font-['Plus_Jakarta_Sans'] uppercase tracking-wide">
                      {chart.label || "Result"}
                    </p>
                    <p className="text-4xl font-bold text-white font-['Roobert'] mt-2">
                      {(() => {
                        const numValue = typeof chart.value === "number"
                          ? chart.value
                          : Number(chart.value);
                        return isNaN(numValue) ? "—" : numValue.toLocaleString();
                      })()}
                    </p>
                  </div>
                </div>
              </div>
            ) : chart.type === "pie" ? (
              <div>
                <SectionTitle title="Distribution" />
                <div className="mt-3">
                  <PieChartComponent data={chart.series?.[0]?.data || []} />
                </div>
              </div>
            ) : chart.type === "bar" ? (
              <div>
                <SectionTitle title="Data" />
                <div className="mt-3">
                  <BarChartComponent
                    data={chart.series?.[0]?.data?.map((v: number, i: number) => ({
                      ticker: String(chart.xAxis?.data?.[i] || `Item ${i + 1}`),
                      return: v,
                    })) || []}
                  />
                </div>
              </div>
            ) : chart.type === "line" ? (
              <div>
                <SectionTitle title="Trend" />
                <div className="mt-3">
                  <LineChartComponent
                    data={(chart.xAxis?.data || []).map((x: string, i: number) => ({
                      date: x,
                      portfolio: chart.series?.[0]?.data?.[i] ?? 0,
                      spy: 0,
                    }))}
                  />
                </div>
              </div>
            ) : (
              <div>
                <SectionTitle title="Chart" />
                <div className="mt-3">
                  <div className="text-center text-sm text-gray-400 py-6">
                    Unsupported chart type: {chart.type}
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Data Table */}
        {table && table.rows.length > 0 && chart?.type !== "table" && (
          <div className="rounded-xl border border-[var(--border-base)] bg-[var(--bg-surface)] p-4">
            <SectionTitle title="Results" />
            <div className="mt-3">
              <DataTableComponent columns={table.columns} rows={table.rows} />
            </div>
          </div>
        )}

        {/* Insights */}
        {insights && insights.length > 0 && (
          <div className="rounded-xl border border-[var(--border-base)] bg-[var(--bg-surface)] p-4">
            <SectionTitle title="Insights" />
            <div className="mt-3 grid grid-cols-2 gap-4">
              {insights.map((insight, index) => (
                <InsightCardComponent
                  key={`insight-${index}`}
                  insight={{
                    title: insight.title,
                    description: insight.description,
                    emoji: insight.emoji,
                  }}
                  type="info"
                />
              ))}
            </div>
          </div>
        )}

        {/* SQL Code (collapsible, bottom) */}
        {sql && (
          <div className="rounded-xl border border-[var(--border-base)] bg-[var(--bg-surface)]">
            <button
              onClick={() => setShowSql(!showSql)}
              className="flex items-center gap-1.5 w-full px-4 py-3 text-xs font-medium text-[var(--brand-primary)] hover:text-[var(--text-primary)] transition-colors"
            >
              <FileText size={12} />
              {showSql ? "Hide SQL" : "Show SQL"}
              <ChevronDown
                className={`ml-auto transition-transform ${showSql ? "rotate-180" : ""}`}
                size={12}
              />
            </button>
            {showSql && (
              <div className="px-4 pb-3">
                <pre className="text-xs text-[var(--brand-primary)] bg-[var(--bg-muted)] rounded p-3 overflow-x-auto">
                  {sql}
                </pre>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}