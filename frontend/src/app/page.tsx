"use client";

import { useState, useCallback } from "react";
import { ChatPanel } from "./components/chat-panel";
import { HistoryPanel } from "./components/history-panel";
import { Send, Settings, MessageCircle, ListTodo, Sun, Moon } from "lucide-react";
import Link from "next/link";
import { GenerativeCanvas } from "./components/generative-canvas";
import { streamChat, type ChatMessage } from "@/utils/api-client";
import { useTheme } from "@/hooks/use-theme";

export interface ChartData {
  type: string;
  xAxis?: any;
  series?: any[];
  value?: number | string;
  label?: string;
  data:any;
}

export interface InsightData {
  title: string;
  description: string;
  emoji: string;
}

export interface TableData {
  columns: string[];
  rows: Record<string, any>[];
}

export interface CanvasState {
  chart: ChartData | null;
  analysis: string;
  insights: InsightData[];
  table: TableData | null;
  suggestions: string[];
  recommendations: string[];
  sql: string;
}
function mapToCanvasState(agentResponse: any): Partial<CanvasState> {
  const state: Partial<CanvasState> = {};

  if (agentResponse?.chart) {
    state.chart = {
      type: agentResponse.chart.type,
      xAxis: agentResponse.chart.xAxis,
      series: agentResponse.chart.series,
      data: agentResponse.chart.data,
      value: agentResponse.chart.value,
      label: agentResponse.chart.label,
    };
  }

  state.analysis = agentResponse?.answer || agentResponse?.analysis || "";

  if (agentResponse?.insights) {
    state.insights = Array.isArray(agentResponse.insights)
      ? agentResponse.insights.map((insight: any) => ({
          title: insight.title || "",
          description: insight.description || "",
          emoji: insight.emoji || "💡",
        }))
      : [];
  }

  if (agentResponse?.table) {
    const tableData = typeof agentResponse.table === "string"
      ? JSON.parse(agentResponse.table)
      : agentResponse.table;

    if (Array.isArray(tableData) && tableData.length > 0) {
      state.table = {
        columns: Object.keys(tableData[0]),
        rows: tableData,
      };
    }
  }

  if (agentResponse?.suggestions) {
    state.suggestions = Array.isArray(agentResponse.suggestions)
      ? agentResponse.suggestions
      : [];
  }

  if (agentResponse?.recommendations) {
    state.recommendations = Array.isArray(agentResponse.recommendations)
      ? agentResponse.recommendations
      : [];
  }

  if (agentResponse?.sql) {
    state.sql = agentResponse.sql;
  }

  return state;
}
export default function AskDataApp() {
  const { toggleTheme } = useTheme();
  const [view, setView] = useState<"chat" | "history">("chat");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [currentThreadId, setCurrentThreadId] = useState<string>(`thread-${Date.now()}`); // ← 新增
  const [isLoading, setIsLoading] = useState(false);
  const [canvasState, setCanvasState] = useState<CanvasState>({
    chart: null,
    analysis: "",
    insights: [],
    table: null,
    suggestions: [],
    recommendations: [],
    sql: "",
  });

  const handleSend = useCallback(
    async (question: string) => {
      if (!question.trim() || isLoading) return;
      const threadId = currentThreadId;

      const userMsg: ChatMessage = {
        role: "user",
        content: question,
        timestamp: new Date(),
        threadId,  // ← 添加
      };
      setMessages((prev) => [...prev, userMsg]);
      // 新请求发出时立即清空 canvas，显示 empty state + loading
      setCanvasState({
        chart: null,
        analysis: "",
        insights: [],
        table: null,
        suggestions: [],
        recommendations: [],
        sql: "",
      });
      setIsLoading(true);

      try {
        await streamChat(
          { question, thread_id: threadId },
          async (evt: any, assistantMessage: string, agentResponse: any) => {
            if (assistantMessage) {
              const updatedMsg: ChatMessage = {
                role: "assistant",
                content: assistantMessage,
                timestamp: new Date(),
                threadId,  // ← 添加
              };
              setMessages((prev) => {
                // complete事件：移除所有临时步骤，添加最终答案
                if (evt?.event === "complete") {
                  // 过滤掉当前thread的所有临时步骤消息
                  const filtered = prev.filter(
                    m => !(m.role === "assistant" && m.threadId === threadId && m.isStep)
                  );
                  return [...filtered, updatedMsg];
                }
                
                // 其他事件：追加临时步骤消息
                return [...prev, { ...updatedMsg, isStep: true }];
              });

            }

            // 处理 complete 事件（agentResponse 已在 api-client.ts 中从 chart_json 提取）
            if (agentResponse && evt?.event === "complete") {
              const newState = mapToCanvasState(agentResponse);
              
              // 合并推荐问题和建议：优先使用 agentResponse，fallback 到已暂存的 canvasState
              setCanvasState((prev) => {
                const suggestions = newState.suggestions ?? prev.suggestions ?? [];
                const recommendations = newState.recommendations ?? prev.recommendations ?? [];
                
                // 同步到 messages（在 complete 时才显示推荐按钮）
                setMessages((msgs) => {
                  const last = msgs[msgs.length - 1];
                  if (last?.role !== "assistant") return msgs;
                  return [
                    ...msgs.slice(0, msgs.length - 1),
                    {
                      ...last,
                      agentResponse: {
                        ...(last.agentResponse ?? {}),
                        threadId,
                        ...agentResponse,
                        suggestions,
                        recommendations,  // 在这里才添加推荐问题到消息
                      },
                      suggestions,
                      recommendations,
                      sql: newState.sql,
                    },
                  ];
                });
                
                return {
                  ...prev,
                  ...newState,
                  suggestions,
                  recommendations,
                };
              });
            }

            // 独立事件：推荐问题（在 sql_executed 之后、chart_generated 之前）
            if (evt?.event === "recommendation_generated" && evt?.data?.recommendations) {
              const recommendations = evt.data.recommendations;
              
              // 只更新全局 canvasState（暂存推荐问题，等 complete 时再显示按钮）
              setCanvasState((prev) => ({
                ...prev,
                recommendations,
                suggestions: evt.data.suggestions || prev.suggestions,
              }));
              
              // 左侧状态栏会自动显示 evt.step ("已生成推荐问题")
              // 不需要在这里添加到 messages，推荐按钮在 complete 事件时才显示
            }

            // 在 complete 之前同步到 messages，避免闭包读空
            if (Array.isArray(evt?.data?.suggestions)) {
  const suggestions = evt.data.suggestions;

  setMessages((prev) => {
    const lastAssistantIndex = prev.findLastIndex(
      (m) => m.role === "assistant"
    );

    if (lastAssistantIndex === -1) {
      return prev;
    }

    return prev.map((m, index): ChatMessage => {
      if (index !== lastAssistantIndex) {
        return m;
      }

      return {
        ...m,
        threadId,
        agentResponse: {
          ...(m.agentResponse ?? {}),
          answer: m.agentResponse?.answer ?? "",
          suggestions,
        },
      };
    });
  });
}

            // chart_json 的处理已经在上面的 agentResponse 中完成
            // 这里只处理非 complete 事件的 chart_json（如 chart_generated 事件）
            if (evt?.data?.chart_json && evt?.event !== "complete") {
              const cj = evt.data.chart_json;
              setCanvasState((prev) => ({
                ...prev,
                chart: cj.chart || prev.chart,
                analysis: cj.answer || prev.analysis,
                insights: cj.insights || prev.insights,
                table: cj.table ? {
                  columns: Object.keys(cj.table[0]),
                  rows: cj.table,
                } : prev.table,
                suggestions: cj.suggestions || prev.suggestions,
                recommendations: cj.recommendations || prev.recommendations,
                sql: cj.sql || prev.sql,
              }));
            }
          }
        );
      } catch (err) {
        console.error("Stream failed", err);
        const errMsg: ChatMessage = {
          role: "assistant",
          content: "Sorry, something went wrong. Please try again.",
          timestamp: new Date(),
          threadId,
        };
        setMessages((prev) => [...prev, errMsg]);
      } finally {
        setIsLoading(false);
      }
    },
    [isLoading]
  );

  const handleSelectConversation = useCallback(
    (restoredMessages: ChatMessage[], _threadId: string) => {
      setMessages(restoredMessages);
      setCurrentThreadId(_threadId);
      // Reconstruct canvas state from the last assistant message
      const lastAi = [...restoredMessages].reverse().find((m) => m.role === "assistant");
      if (lastAi?.agentResponse) {
        setCanvasState(prev => ({
          ...prev,
          ...mapToCanvasState(lastAi.agentResponse),
        }));
      }
      setView("chat");
    },
    []
  );

  const handleNewChat = useCallback(() => {
    setMessages([]);
    setCurrentThreadId(`thread-${Date.now()}`); // ← 新增：创建新的 thread_id
    setCanvasState({
      chart: null,
      analysis: "",
      insights: [],
      table: null,
      suggestions: [],
      recommendations: [],
      sql: "",
    });
    setView("chat");
  }, []);


  return (
    <div className="h-screen bg-[var(--bg-base)] flex overflow-hidden">
      <div className="w-85 border-r border-[var(--border-base)] bg-[var(--bg-surface)] flex-shrink-0 flex flex-col">
        {/* Header */}
        <div className="p-4 border-b border-[var(--border-base)] bg-[var(--bg-base)]">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <span className="text-xl">{'🪁'}</span>
              <div>
                <h1 className="text-lg font-semibold text-[var(--text-primary)] font-['Roobert'] whitespace-nowrap">Awaken Data with a Word.</h1>
                <div className="inline-block px-2 py-0.5 bg-[var(--brand-purple)] text-[var(--text-primary)] text-xs font-semibold uppercase rounded">
                  PRO
                </div>
              </div>
            </div>
            <div className="flex items-center gap-1">
              {/* Theme Toggle */}
              <button
                onClick={toggleTheme}
                className="p-2 rounded-lg bg-[var(--bg-subtle)] text-[var(--text-secondary)] hover:bg-[var(--border-light)] hover:text-[var(--text-primary)] transition-colors"
                title="切换主题"
              >
                <Moon size={18} />
              </button>
              {/* Settings */}
              <Link
                href="/settings"
                className="p-2 rounded-lg bg-[var(--bg-subtle)] text-[var(--text-secondary)] hover:bg-[var(--border-light)] hover:text-[var(--text-primary)] transition-colors"
                title="模型设置"
              >
                <Settings size={18} />
              </Link>
            </div>
          </div>

          {/* View Tabs */}
          <div className="flex gap-1 bg-[var(--bg-subtle)] rounded-lg p-1">
            <button
              onClick={() => setView("chat")}
              className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-all ${
                view === "chat"
                  ? "bg-[var(--brand-primary)] text-white shadow-sm"
                  : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
              }`}
            >
              <MessageCircle size={14} />
              Chat
            </button>
            <button
              onClick={() => setView("history")}
              className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-all ${
                view === "history"
                  ? "bg-[var(--brand-primary)] text-white shadow-sm"
                  : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
              }`}
            >
              <ListTodo size={14} />
              History
            </button>
          </div>
        </div>

        {/* Content Area */}
        {view === "chat" ? (
          <>
            <ChatPanel messages={messages} onSend={handleSend} isLoading={isLoading} onSuggestionClick={handleSend} recommendations={canvasState.recommendations} />
            <ChatInput onSend={handleSend} disabled={isLoading} />
          </>
        ) : (
          <HistoryPanel onSelectConversation={handleSelectConversation} onNewChat={handleNewChat} />
        )}
      </div>

      <div className="flex-1 relative min-w-0">
        <div className="h-full">
          <GenerativeCanvas canvasState={canvasState} />
        </div>
      </div>
    </div>
  );
}
function ChatInput({ onSend, disabled }: { onSend: (q: string) => void; disabled: boolean }) {
  const [value, setValue] = useState("");

  const handleSubmit = () => {
    if (!value.trim() || disabled) return;
    onSend(value.trim());
    setValue("");
  };

  return (
    <div className="border-t border-[var(--border-base)] p-3 bg-[var(--bg-surface)]">
      <div className="flex items-center gap-2 rounded-xl border border-[var(--border-base)] bg-[var(--bg-muted)] px-3 py-2 focus-within:border-[var(--brand-accent)] focus-within:ring-1 focus-within:ring-[var(--brand-accent)]/50 transition-all">
        <input
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
          placeholder="Ask a question about your data..."
          disabled={disabled}
          className="flex-1 text-sm text-[var(--text-primary)] font-['Plus_Jakarta_Sans'] bg-transparent outline-none placeholder:text-[var(--text-tertiary)]"
        />
        <button
          onClick={handleSubmit}
          disabled={disabled || !value.trim()}
          className={`p-1.5 rounded-full transition-all
            ${
              disabled || !value.trim()
                ? "bg-[var(--border-light)] text-[var(--text-tertiary)] cursor-not-allowed"
                : "bg-[var(--brand-primary)] text-white hover:brightness-110"
            }`}
        >
          <Send size={16} />
        </button>
      </div>
    </div>
  );
}