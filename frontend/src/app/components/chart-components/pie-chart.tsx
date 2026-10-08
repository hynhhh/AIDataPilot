"use client";

import type { ComponentProps, ReactNode } from "react";
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, Legend } from "recharts";

const COLORS = [
  "#1B606F", "#86ECE4", "#BEC9FF", "#F5A623",
  "#E86D6D", "#9B59B6", "#27AE60", "#3498DB",
];

export function PieChartComponent({ data }: { data: { name: string; value: number }[] }) {
  if (!data || data.length === 0) {
    return <div className="text-center text-sm text-gray-400 py-8">No data</div>;
  }

  const total = data.reduce((sum, item) => sum + item.value, 0);

  return (
    <div className="flex items-center gap-6">
      <div className="w-[200px] h-[200px]">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={data}
              dataKey="value"
              nameKey="name"
              cx="50%"
              cy="50%"
              outerRadius={70}
              innerRadius={35}
              paddingAngle={2}
              label={({ name, percent }) => `${name} ${(percent ??0* 100).toFixed(0)}%`}
            >
              {data.map((_entry, index) => (
                <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
              ))}
            </Pie>
            <Tooltip
              formatter={(value: any) =>
                new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(value)
              }
            />
            <Legend
              layout="vertical"
              align="right"
              verticalAlign="middle"
              formatter={(value: string, entry: any) => (
                <span className="text-xs text-[var(--text-secondary)]">{value}</span>
              )}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>
      <div className="flex-1 space-y-2">
        {data.map((item, index) => (
          <div key={index} className="flex items-center justify-between text-sm">
            <div className="flex items-center gap-2">
              <div
                className="w-3 h-3 rounded-full"
                style={{ backgroundColor: COLORS[index % COLORS.length] }}
              />
              <span className="text-[var(--text-primary)] font-['Plus_Jakarta_Sans']">{item.name}</span>
            </div>
            <span className="text-[var(--text-secondary)] font-['Plus_Jakarta_Sans']">
              {new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(item.value)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default PieChartComponent;
