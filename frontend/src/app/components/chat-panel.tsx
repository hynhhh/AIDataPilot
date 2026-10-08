"use client";

import { useState, useRef, useEffect } from "react";
import { FileText, ThumbsUp, ThumbsDown } from "lucide-react";
import { BarChartComponent } from "./chart-components/bar-chart";
import { LineChartComponent } from "./chart-components/line-chart";
import { AllocationTableComponent } from "./chart-components/allocation-table";
import type { ChatMessage, AgentResponse } from "@/utils/api-client";
import { submitFeedback } from "@/utils/api-client";

/* ─── Suggestion Chip ─── */
function SuggestionChip({
  text,
  onClick,
  disabled,
}: {
  text: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`px-3 py-1.5 text-xs font-medium rounded-full border transition-all
        ${
          disabled
            ? "opacity-40 cursor-not-allowed bg-[var(--bg-subtle)] border-[var(--border-base)]"
            : "border-[var(--border-base)] bg-[var(--brand-accent)]/10 text-[var(--brand-primary)] hover:bg-[var(--brand-accent)]/25 hover:border-[var(--brand-accent)]"
        }`}
    >
      {text}
    </button>
  );
}

/* ─── Data Table ─── */
function DataTable({ data }: { data: Record<string, any>[] }) {
  if (!data || data.length === 0) return null;
  const columns = Object.keys(data[0]);
  return (
    <div className="mt-2 overflow-x-auto rounded-lg border border-[var(--border-base)]">
      <table className="w-full text-xs font-['Plus_Jakarta_Sans']">
        <thead className="bg-[var(--bg-muted)]">
          <tr>
            {columns.map((col) => (
              <th key={col} className="text-left px-3 py-2 font-semibold text-[var(--text-primary)] border-b border-[var(--border-base)]">
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((row, i) => (
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

/* ─── Chart/Table Renderer from ECharts config ─── */
function ChartOrTable({ response }: { response: AgentResponse }) {
  if (!response.chart) return null;
  const chart = response.chart;

  if (chart.type === "table" && response.table) {
    return <DataTable data={response.table} />;
  }

  if (chart.type === "pie") {
    const pieData = chart.series?.[0]?.data ?? [];
    if (pieData.length > 0) {
      const allocations = pieData.map((item: any) => ({
        ticker: item.name,
        allocation: item.value,
        currentValue: item.value,
        totalReturn: 0,
      }));
      return <AllocationTableComponent allocations={allocations} size="small" />;
    }
  }

  if (chart.type === "line" && chart.xAxis?.data && chart.series?.[0]?.data) {
    const xData = chart.xAxis.data;
    const yData = chart.series[0].data;
    return (
      <div className="mt-2">
        <LineChartComponent
          data={xData.map((x: string, i: number) => ({ date: x, portfolio: yData[i] ?? 0, spy: 0 }))}
          size="normal"
        />
      </div>
    );
  }

  if (chart.type === "bar" && chart.series?.[0]?.data) {
    const yData = chart.series[0].data;
    return (
      <div className="mt-2">
        <BarChartComponent
          data={yData.map((v: number, i: number) => ({ ticker: `Item ${i + 1}`, return: v }))}
          size="normal"
        />
      </div>
    );
  }

  if (chart.type === "metric") {
    return (
      <div className="mt-2 p-3 bg-[#86ECE4]/10 rounded-lg border border-[#86ECE4]/30">
        <div className="text-2xl font-bold text-[#030507] font-['Roobert']">{chart.value}</div>
        <div className="text-xs text-[#575758] font-['Plus_Jakarta_Sans']">{chart.label}</div>
      </div>
    );
  }

  return null;
}

/* ─── Streaming Indicator ─── */
function StreamingIndicator() {
  return (
    <div className="flex gap-2 items-start">
      <div className="w-6 h-6 rounded-full bg-[#BEC9FF] flex items-center justify-center flex-shrink-0 mt-0.5">
        <span className="text-[10px] font-bold text-[#030507]">AI</span>
      </div>
      <div className="flex-1 rounded-xl bg-[#F0F0F4] px-4 py-3">
        <div className="flex items-center gap-2">
          <div className="flex gap-1">
            {[0, 1, 2].map((d) => (
              <span
                key={d}
                className="w-2 h-2 rounded-full bg-[var(--brand-primary)] animate-bounce"
                style={{ animationDelay: `${d * 150}ms` }}
              />
            ))}
          </div>
          <span className="text-xs text-[var(--text-secondary)] font-['Plus_Jakarta_Sans']">Processing...</span>
        </div>
      </div>
    </div>
  );
}

/* ─── Assistant Message Bubble ─── */
function AssistantMessage({
  message,
  onSuggestionClick,
  recommendations,
  messageIndex,
}: {
  message: ChatMessage;
  onSuggestionClick?: (text: string) => void;
  recommendations: string[];
  messageIndex: number;
}) {
  const response = message.agentResponse;
  const [feedback, setFeedback] = useState<"thumbs_up" | "thumbs_down" | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [feedbackMsg, setFeedbackMsg] = useState<string | null>(null);

  if (!response) {
    return (
      <div className="flex gap-2">
        <div className="w-6 h-6 rounded-full bg-[var(--brand-purple)] flex items-center justify-center flex-shrink-0 mt-0.5">
          <span className="text-[10px] font-bold text-[var(--text-primary)]">AI</span>
        </div>
        <div className="flex-1">
          <p className="text-sm text-[var(--text-primary)] font-['Plus_Jakarta_Sans'] leading-relaxed whitespace-pre-wrap">
            {message.content}
          </p>
        </div>
      </div>
    );
  }

  const hasSuggestions = response.suggestions && response.suggestions.length > 0;
  // 优先使用消息自己的 recommendations，如果没有则使用全局的
  const messageRecommendations = response.recommendations || recommendations;
  const hasRecommendations = messageRecommendations && messageRecommendations.length > 0;

  const handleFeedback = async (type: "thumbs_up" | "thumbs_down") => {
    if (feedback || isSubmitting || !message.threadId) return;

    setIsSubmitting(true);
    try {
      const result = await submitFeedback(message.threadId, messageIndex, type);
      setFeedback(type);
      setFeedbackMsg(result.message ?? "反馈已收到，谢谢！");
    } catch (error) {
      console.error("Failed to submit feedback:", error);
      setFeedbackMsg("反馈提交失败，请重试。");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="flex gap-2">
      <div className="w-6 h-6 rounded-full bg-[var(--brand-purple)] flex items-center justify-center flex-shrink-0 mt-0.5">
        <span className="text-[10px] font-bold text-[var(--text-primary)]">AI</span>
      </div>
      <div className="flex-1 space-y-3">
        {/* 不可回答：显示提示文字 + 推荐问题；有推荐问题：显示"处理完成"+推荐问题 */}
        <div>
          {response.unanswerable ? (
            <p className="text-sm text-[var(--text-primary)] font-['Plus_Jakarta_Sans'] leading-relaxed whitespace-pre-wrap">
              {response.answer}
            </p>
          ) : (
            <p className="text-sm text-[var(--text-primary)] font-['Plus_Jakarta_Sans'] leading-relaxed whitespace-pre-wrap">
              {hasRecommendations ? "处理完成" : response.answer}
            </p>
          )}
        </div>
        {/* 推荐问题时不显示图表（图表在右侧画布区域显示） */}
        {!hasRecommendations && response.chart && <ChartOrTable response={response} />}
        {hasRecommendations && (
          <div>
            <p className="text-xs font-medium text-[var(--text-secondary)] mb-1.5 font-['Plus_Jakarta_Sans']">💡 你可以继续问：</p>
            <div className="flex flex-wrap gap-1.5">
              {messageRecommendations.map((r, i) => (
                <button
                  key={i}
                  onClick={() => onSuggestionClick?.(r)}
                  className="px-3 py-1.5 text-xs font-medium rounded-full border border-[var(--brand-accent)] bg-[var(--brand-accent)]/10 text-[var(--brand-primary)] hover:bg-[var(--brand-accent)]/25 hover:border-[var(--brand-accent)] transition-all"
                >
                  {r}
                </button>
              ))}
            </div>
          </div>
        )}
        {hasSuggestions && (
          <div className="flex flex-wrap gap-1.5 pt-1">
            {response.suggestions?.map((s, i) => (
              <SuggestionChip
                key={i}
                text={s}
                onClick={() => onSuggestionClick?.(s)}
              />
            ))}
          </div>
        )}
        {/* Feedback Buttons */}
        <div className="flex items-center gap-2 pt-1">
          <button
            onClick={() => handleFeedback("thumbs_up")}
            disabled={!!feedback || isSubmitting}
            className={`flex items-center gap-1.5 px-2.5 py-1.5 text-sm rounded-md transition-all ${
              feedback === "thumbs_up"
                ? "bg-green-100 text-green-700 border border-green-300"
                : feedback
                ? "opacity-40 cursor-not-allowed text-[var(--text-tertiary)]"
                : "text-[var(--text-tertiary)] hover:text-green-600 hover:bg-green-50"
            }`}
            title="Good response"
          >
            <ThumbsUp className="h-4 w-4" />
          </button>
          <button
            onClick={() => handleFeedback("thumbs_down")}
            disabled={!!feedback || isSubmitting}
            className={`flex items-center gap-1.5 px-2.5 py-1.5 text-sm rounded-md transition-all ${
              feedback === "thumbs_down"
                ? "bg-red-100 text-red-700 border border-red-300"
                : feedback
                ? "opacity-40 cursor-not-allowed text-[var(--text-tertiary)]"
                : "text-[var(--text-tertiary)] hover:text-red-600 hover:bg-red-50"
            }`}
            title="Bad response"
          >
            <ThumbsDown className="h-4 w-4" />
          </button>
        </div>
        {feedbackMsg && (
          <p className="text-xs text-[var(--text-secondary)] pt-1 font-['Plus_Jakarta_Sans']">
            {feedbackMsg}
          </p>
        )}
      </div>
    </div>
  );
}

/* ─── ChatPanel ─── */
interface ChatPanelProps {
  messages: ChatMessage[];
  onSend: (question: string) => void;
  isLoading: boolean;
  onSuggestionClick?: (text: string) => void;
  recommendations: string[];
}

export function ChatPanel({
  messages,
  onSend,
  isLoading,
  onSuggestionClick,
  recommendations,
}: ChatPanelProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  return (
    <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
      {messages.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-full text-center space-y-3">
          <div className="w-12 h-12 rounded-full bg-[var(--brand-accent)]/20 flex items-center justify-center">
            <span className="text-2xl">🪁</span>
          </div>
          <div>
            <p className="text-sm font-semibold text-[var(--text-primary)] font-['Roobert']">Ask Data</p>
            <p className="text-xs text-[var(--text-secondary)] font-['Plus_Jakarta_Sans'] mt-1">
              Ask a question to analyze your data. The AI will generate
              charts, tables, and insights.
            </p>
          </div>
        </div>
      ) : (
        <>
          {messages.map((msg, i) => {
            if (msg.role === "user") {
              return (
                <div key={`user-${i}`} className="flex justify-end">
                  <div className="max-w-[80%] rounded-xl bg-[var(--brand-primary)] px-4 py-2.5">
                    <p className="text-sm text-white font-['Plus_Jakarta_Sans']">
                      {msg.content}
                    </p>
                  </div>
                </div>
              );
            }
            
            // 计算后端消息索引（排除临时步骤消息）
            const backendIndex = messages
              .slice(0, i + 1)
              .filter(m => !m.isStep)
              .length - 1;
            
            return (
              <AssistantMessage
                key={`ai-${i}`}
                message={msg}
                messageIndex={backendIndex}
                onSuggestionClick={onSuggestionClick}
                recommendations={recommendations}
              />
            );
          })}
          {isLoading && <StreamingIndicator />}
        </>
      )}
      <div ref={messagesEndRef} />
    </div>
  );
}

export default ChatPanel;

