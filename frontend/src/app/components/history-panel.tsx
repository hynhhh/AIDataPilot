"use client";

import { useEffect, useState, useCallback } from "react";
import { Trash2, Loader2, MessageCircle, Clock } from "lucide-react";
import {
  fetchAllConversations,
  deleteHistory,
  loadConversation,
} from "@/utils/api-client";
import type { ChatMessage } from "@/utils/api-client";
import type { ConversationOverview } from "@/utils/api-client";

interface HistoryPanelProps {
  onSelectConversation: (messages: ChatMessage[], threadId: string) => void;
  onNewChat: () => void;
}

function formatRelativeTime(timestamp: string): string {
  try {
    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return "刚刚";
    if (diffMins < 60) return `${diffMins}分钟前`;
    if (diffHours < 24) return `${diffHours}小时前`;
    if (diffDays < 7) return `${diffDays}天前`;
    return date.toLocaleDateString("zh-CN", {
      month: "short",
      day: "numeric",
    });
  } catch {
    return "";
  }
}

export function HistoryPanel({
  onSelectConversation,
  onNewChat,
}: HistoryPanelProps) {
  const [conversations, setConversations] = useState<ConversationOverview[]>([]);
  const [loading, setLoading] = useState(true);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const fetchConversations = useCallback(async () => {
    try {
      const data = await fetchAllConversations();
      setConversations(data);
    } catch {
      // Silently handle — empty state will show
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchConversations();
  }, [fetchConversations]);

  const handleSelect = async (threadId: string) => {
    try {
      const messages = await loadConversation(threadId);
      onSelectConversation(messages, threadId);
    } catch (err) {
      console.error("Failed to load conversation:", err);
    }
  };

  const handleDelete = async (e: React.MouseEvent, threadId: string) => {
    e.stopPropagation();
    setDeletingId(threadId);
    try {
      await deleteHistory(threadId);
      setConversations((prev) => prev.filter((c) => c.thread_id !== threadId));
    } catch (err) {
      console.error("Failed to delete conversation:", err);
    } finally {
      setDeletingId(null);
    }
  };

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 size={20} className="animate-spin text-[var(--text-secondary)]" />
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-[#D8D8E5]">
        <h2 className="text-sm font-semibold text-[var(--text-primary)] font-['Roobert']">
          History Records
        </h2>
        <button
          onClick={onNewChat}
          className="px-2.5 py-1 text-xs font-medium text-[var(--brand-primary)] bg-[var(--brand-accent)]/10 rounded-lg hover:bg-[var(--brand-accent)]/25 transition-colors"
        >
          + Add New Chat
        </button>
      </div>

      {/* Conversation List */}
      <div className="flex-1 overflow-y-auto">
        {conversations.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center space-y-3 px-4">
            <div className="w-12 h-12 rounded-full bg-[var(--brand-accent)]/20 flex items-center justify-center">
              <MessageCircle size={20} className="text-[var(--brand-primary)]" />
            </div>
            <p className="text-sm text-[var(--text-secondary)] font-['Plus_Jakarta_Sans']">
              暂无对话历史
            </p>
            <p className="text-xs text-[var(--text-tertiary)] font-['Plus_Jakarta_Sans']">
              发送一条消息开始分析数据
            </p>
          </div>
        ) : (
          <div className="py-2">
            {conversations.map((conv, index) => (
              <div
                key={conv.thread_id}
                onClick={() => handleSelect(conv.thread_id)}
                className="group px-4 py-3 hover:bg-[var(--bg-subtle)] cursor-pointer transition-colors border-b border-[var(--border-base)]/50 last:border-b-0"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-[var(--text-primary)] font-['Plus_Jakarta_Sans'] truncate">
                      {conv.question}
                    </p>
                    <div className="flex items-center gap-2 mt-1">
                      <Clock size={10} className="text-[var(--text-tertiary)]" />
                      <span className="text-xs text-[var(--text-tertiary)] font-['Plus_Jakarta_Sans']">
                        {formatRelativeTime(conv.timestamp)}
                      </span>
                      <span className="text-xs text-[var(--text-tertiary)] font-['Plus_Jakarta_Sans']">
                        · {conv.messageCount} 条消息
                      </span>
                    </div>
                  </div>
                  <button
                    onClick={(e) => handleDelete(e, conv.thread_id)}
                    disabled={deletingId === conv.thread_id}
                    className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-[var(--bg-subtle)] transition-all disabled:opacity-50"
                    title="删除"
                  >
                    {deletingId === conv.thread_id ? (
                      <Loader2 size={14} className="animate-spin text-[var(--text-tertiary)]" />
                    ) : (
                      <Trash2 size={14} className="text-[var(--text-tertiary)]" />
                    )}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default HistoryPanel;
