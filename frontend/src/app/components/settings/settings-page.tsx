"use client";

import { useState, useEffect } from "react";

/* ─── Settings Page ─── */
export function SettingsPage() {
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  // 获取当前配置
  useEffect(() => {
    fetch("http://127.0.0.1:8000/api/settings")
      .then((res) => res.json())
      .then((data) => {
        if (data.success) {
          setModel(data.data.compatible_model || "");
          setApiKey(data.data.compatible_api_key || "");
          setBaseUrl(data.data.compatible_base_url || "");
        }
      })
      .catch((err) => setError("获取配置失败：" + err.message))
      .finally(() => setLoading(false));
  }, []);

  // 保存配置
  const handleSave = async () => {
    setSaving(true);
    setError("");
    setMessage("");
    
    try {
      const res = await fetch("http://127.0.0.1:8000/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          compatible_model: model,
          compatible_api_key: apiKey,
          compatible_base_url: baseUrl,
        }),
      });
      
      const data = await res.json();
      
      if (data.success) {
        setMessage(data.message || "配置已保存");
      } else {
        setError(data.detail || "保存失败");
      }
    } catch (err) {
      setError("保存失败：");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center space-y-3">
          <div className="w-8 h-8 border-4 border-[var(--brand-accent)] border-t-transparent rounded-full animate-spin mx-auto" />
          <p className="text-sm text-[var(--text-secondary)]">加载中...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-[var(--text-primary)] font-['Roobert']">
          模型配置
        </h1>
        <p className="text-sm text-[var(--text-secondary)] font-['Plus_Jakarta_Sans'] mt-1">
          配置 OpenAI 兼容的模型服务（如 Claude、GPT 等）
        </p>
      </div>

      {/* 配置表单 */}
      <div className="space-y-4 bg-[var(--bg-surface)] rounded-xl border border-[var(--border-base)] p-6">
        <div>
          <label className="block text-sm font-medium text-[var(--text-primary)] mb-1.5">
            模型名称
            <span className="text-xs text-[var(--text-tertiary)] ml-2">
              (如：claude-sonnet-4-5, gpt-4, gpt-3.5-turbo)
            </span>
          </label>
          <input
            type="text"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            placeholder="输入模型名称"
            className="w-full px-3 py-2 text-sm border border-[var(--border-base)] rounded-lg outline-none focus:border-[var(--brand-accent)] focus:ring-1 focus:ring-[var(--brand-accent)]/50 transition-all font-['Plus_Jakarta_Sans'] bg-[var(--bg-surface)] text-[var(--text-primary)]"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-[var(--text-primary)] mb-1.5">
            API Key
            <span className="text-xs text-[var(--text-tertiary)] ml-2">
              (可选)
            </span>
          </label>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="输入 API Key"
            className="w-full px-3 py-2 text-sm border border-[var(--border-base)] rounded-lg outline-none focus:border-[var(--brand-accent)] focus:ring-1 focus:ring-[var(--brand-accent)]/50 transition-all font-['Plus_Jakarta_Sans'] bg-[var(--bg-surface)] text-[var(--text-primary)]"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-[var(--text-primary)] mb-1.5">
            Base URL
            <span className="text-xs text-[var(--text-tertiary)] ml-2">
              (如：https://model-garden.calix.local)
            </span>
          </label>
          <input
            type="url"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="输入 Base URL"
            className="w-full px-3 py-2 text-sm border border-[var(--border-base)] rounded-lg outline-none focus:border-[var(--brand-accent)] focus:ring-1 focus:ring-[var(--brand-accent)]/50 transition-all font-['Plus_Jakarta_Sans'] bg-[var(--bg-surface)] text-[var(--text-primary)]"
          />
        </div>
      </div>

      {/* 操作按钮 */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-4 py-2 bg-[var(--brand-primary)] text-white text-sm font-medium rounded-lg hover:brightness-110 transition-all disabled:opacity-50 disabled:cursor-not-allowed font-['Plus_Jakarta_Sans']"
        >
          {saving ? "保存中..." : "保存配置"}
        </button>
        <button
          onClick={() => window.location.reload()}
          className="px-4 py-2 bg-[var(--bg-subtle)] text-[var(--text-secondary)] text-sm font-medium rounded-lg hover:bg-[var(--border-light)] transition-colors font-['Plus_Jakarta_Sans']"
        >
          刷新
        </button>
      </div>

      {/* 消息提示 */}
      {message && (
        <div className="p-3 bg-[var(--brand-accent)]/10 border border-[var(--brand-accent)] rounded-lg">
          <p className="text-sm text-[var(--brand-primary)]">{message}</p>
        </div>
      )}

      {error && (
        <div className="p-3 bg-[#FF6B6B]/10 border border-[#FF6B6B] rounded-lg">
          <p className="text-sm text-[#FF6B6B]">{error}</p>
        </div>
      )}

      {/* 使用说明 */}
      <div className="p-4 bg-[var(--bg-muted)] rounded-lg border border-[var(--border-base)]">
        <h3 className="text-sm font-medium text-[var(--text-primary)] mb-2">
          💡 使用说明
        </h3>
        <ul className="text-xs text-[var(--text-secondary)] space-y-1 font-['Plus_Jakarta_Sans']">
          <li>• 填写模型名称、API Key 和 Base URL</li>
          <li>• 点击"保存配置"写入 .env 文件</li>
          <li className="text-[var(--brand-yellow)]">• 保存后需要<strong>重启后端服务</strong>才能生效</li>
          <li className="text-[var(--text-tertiary)]">原因：.env 配置仅在服务启动时加载，LLM 连接需重建</li>
        </ul>
      </div>
    </div>
  );
}

export default SettingsPage;
