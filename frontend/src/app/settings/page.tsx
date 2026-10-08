"use client";

import { SettingsPage } from "@/app/components/settings/settings-page";

export default function Settings() {
  return (
    <div className="h-screen bg-[var(--bg-base)] flex overflow-hidden">
      <div className="w-85 border-r border-[var(--border-base)] bg-[var(--bg-surface)] flex-shrink-0 flex flex-col">
        <div className="p-4 border-b border-[var(--border-base)] bg-[var(--bg-base)]">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xl">⚙️</span>
            <div>
              <h1 className="text-lg font-semibold text-[var(--text-primary)] font-['Roobert']">
                设置
              </h1>
              <p className="text-xs text-[var(--text-secondary)]">模型配置</p>
            </div>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto p-4">
          <SettingsPage />
        </div>
      </div>
    </div>
  );
}
