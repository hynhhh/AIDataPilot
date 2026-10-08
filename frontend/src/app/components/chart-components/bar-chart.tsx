"use client"

import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts"

interface BarChartData {
  ticker: string
  return: number
}

interface BarChartComponentProps {
  data: BarChartData[]
  size?: "normal" | "small"
  onClick?: (data: string) => void
}

export function BarChartComponent({ data, size = "normal", onClick }: BarChartComponentProps) {
  const height = size === "small" ? 80 : 160 // h-20 or h-40
  const padding = size === "small" ? "p-2" : "p-4"
  const fontSize = size === "small" ? 8 : 10
  const tooltipFontSize = size === "small" ? "9px" : "11px"
  return (
    <div className={`bg-[var(--bg-surface)] border border-[var(--border-base)] rounded-xl ${padding}`}>
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border-light)" />
            <XAxis dataKey="ticker" stroke="var(--text-secondary)" fontSize={fontSize} fontFamily="Plus Jakarta Sans" />
            <YAxis
              stroke="var(--text-secondary)"
              fontSize={fontSize}
              fontFamily="Plus Jakarta Sans"
              tickFormatter={(value) => `${value}%`}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "var(--bg-surface)",
                border: "1px solid var(--border-base)",
                borderRadius: "8px",
                fontSize: tooltipFontSize,
                fontFamily: "Plus Jakarta Sans",
              }}
              formatter={(value) => [`${Number(value).toFixed(1)}%`, "Return"]}
            />
            <Bar onClick={(data, index) => {
              if (size === "normal") {
                // @ts-ignore
                console.log(data.payload, "clicked")
                // @ts-ignore
                onClick?.(data.payload.ticker as string)
              }
            }} dataKey="return" fill="var(--brand-accent)" radius={[2, 2, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
