// ============================================
// Backend API Client — SSE Streaming Chat
// ============================================
// Connects frontend to backend /api/chat/stream endpoint.
// Uses plain fetch + ReadableStream (no external deps).
// ============================================

const BACKEND_URL = "http://127.0.0.1:8000";

// ----- Type definitions -----

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
  agentResponse?: AgentResponse;
  threadId?: string;
  isStep?: boolean;  // 标记是否为临时步骤消息（不保存到后端历史）
}

export interface AgentResponse {
  answer: string;
  sql?: string;
  table?: Record<string, any>[];
  chart?: Record<string, any>;
  suggestions?: string[];
  recommendations?: string[];
  unanswerable?: boolean;
  metadata?: Record<string, any>;
}

export interface ConversationMessage {
  role: string;
  content: string;
  timestamp: string;
  agent_response?: AgentResponse;
}

export interface ConversationHistory {
  thread_id: string;
  question: string;
  messages: ConversationMessage[];
  created_at?: string;
  updated_at?: string;
}

export interface SSEEvent {
  event:
    | "start"
    | "thinking"
    | "schema_retrieved"
    | "sql_generated"
    | "sql_validated"
    | "sql_executed"
    | "recommendation_generated"
    | "chart_generated"
    | "complete"
    | "error";
  step?: string;
  data?: Record<string, any>;
  timestamp: string;
}

export interface ChatRequest {
  question: string;
  thread_id?: string;
}

export type StreamCallback = (
  event: SSEEvent,
  assistantMessage: string,
  agentResponse: AgentResponse | null
) => void;

// ----- Helpers -----

/** Accumulate text chunks from a ReadableStream into an SSE event string */
async function processStream(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  decoder: TextDecoder,
  callback: StreamCallback,
  threadId: string
): Promise<AgentResponse> {
  let buffer = "";
  let assistantMessage = "";
  let agentResponse: AgentResponse | null = null;

  // 1. 内部嵌入的解析与回调函数（逻辑保持 100% 相同）
  function flushEvent(block: string) {
    if (!block.startsWith("data: ")) return;
    try {
      const data = JSON.parse(block.slice(6));
      const evt: SSEEvent = {
        event: data.event,
        step: data.step,
        data: data.data,
        timestamp: data.timestamp,
      };

      // 积累来自 "complete" 事件的回答
      if (
        evt.event === "complete" &&
        evt.data &&
        typeof evt.data === "object"
      ) {
        // 处理两种格式：直接的 answer 或 chart_json.answer
        if ("answer" in evt.data) {
          agentResponse = evt.data as AgentResponse;
          assistantMessage = agentResponse.answer;
        } else if ("chart_json" in evt.data && evt.data.chart_json) {
          agentResponse = evt.data.chart_json as AgentResponse;
          assistantMessage = agentResponse.answer;
        }
      } else if (agentResponse === null) {
        assistantMessage = evt.step ? `${evt.step}` : "";
      }

      // 触发外部的回调
      callback(evt, assistantMessage, agentResponse);
    } catch {
      // 忽略损坏的 SSE 数据块
    }
  }

  try {
    // 2. 🔄 核心读取循环：使用 while (true) 替代旧的递归
    while (true) {
      // ✅ 这里的 await 此时 100% 合法且类型安全
      const { done, value } = await reader.read();

      if (done) {
        // 数据流结束，刷新缓冲区内残留的最后一部分数据
        if (buffer.trim()) {
          flushEvent(buffer.trim());
        }
        break; // 退出循环
      }

      // 将 Uint8Array 转换为文本并拼接到缓冲区
      buffer += decoder.decode(value, { stream: true });

      // 3. 🔍 修复换行符：将 "\\n\\n" 修改为真实的换行符 "\n\n"
      let idx: number;
      while ((idx = buffer.indexOf("\n\n")) !== -1) {
        const singleEvent = buffer.slice(0, idx).trim();
        flushEvent(singleEvent);
        buffer = buffer.slice(idx + 2); // 移动缓冲区，跳过这一对换行符
      }
    }

    // 4. 返回最终组装好的 AgentResponse
    return agentResponse ?? { answer: assistantMessage };

  } catch (error) {
    console.error("读取数据流时遇到异常:", error);
    throw error; // 抛出异常让外层调用者感知到
  }
}


// ----- Public API -----

/**
 * Send a chat question to the backend and stream the SSE response.
 *
 * @param request   ChatRequest body
 * @param callback  Called for every SSE event with (event, assistantMessage, agentResponse)
 * @returns The final AgentResponse (fully parsed from the "complete" event)
 */
export async function streamChat(
  request: ChatRequest,
  callback: StreamCallback
): Promise<AgentResponse> {
  const response = await fetch(`${BACKEND_URL}/api/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    throw new Error(`Chat request failed: ${response.status} ${response.statusText}`);
  }

  if (!response.body) {
    throw new Error("Stream body is empty");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();

  return processStream(reader, decoder, callback, request.thread_id ?? "");
}

/**
 * Fetch conversation history.
 */
export async function fetchHistory(threadId?: string): Promise<ChatMessage[]> {
  const params = threadId ? `?thread_id=${encodeURIComponent(threadId)}` : "";
  const response = await fetch(`${BACKEND_URL}/api/chat/history${params}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch history: ${response.status}`);
  }
  const data = await response.json();
  // data is either an array of conversation histories or a single conversation
  const conversations: ConversationHistory[] = Array.isArray(data) ? data : [data];
  const allMessages: ChatMessage[] = [];

  for (const conv of conversations) {
    if (!conv?.messages) continue;
    for (const msg of conv.messages) {
      const m: ChatMessage = {
        role: msg.role as "user" | "assistant",
        content: msg.content,
        timestamp: new Date(msg.timestamp),
        agentResponse: msg.agent_response,
        threadId: conv.thread_id,
      };
      allMessages.push(m);
    }
  }
  return allMessages;
}

/**
 * Delete a conversation by thread_id.
 */
export async function deleteHistory(threadId: string): Promise<void> {
  const response = await fetch(`${BACKEND_URL}/api/chat/history/${threadId}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    throw new Error(`Failed to delete history: ${response.status}`);
  }
}

/**
 * Fetch all conversations overview.
 * Returns an array of conversation summaries (without full messages).
 */
export async function fetchAllConversations(): Promise<ConversationOverview[]> {
  const response = await fetch(`${BACKEND_URL}/api/chat/history`);
  if (!response.ok) {
    throw new Error(`Failed to fetch conversations: ${response.status}`);
  }
  const data = await response.json();
  // The backend returns an array of ConversationHistory objects
  return data.map((conv: ConversationHistory) => ({
    thread_id: conv.thread_id,
    question: conv.messages?.[0]?.content ?? "",
    messageCount: conv.messages?.length ?? 0,
    timestamp: conv.updated_at ?? conv.created_at ?? "",
  }));
}

export interface ConversationOverview {
  thread_id: string;
  question: string;
  messageCount: number;
  timestamp: string;
}

/**
 * Load a single conversation by thread_id and return ChatMessage[].
 */
export async function loadConversation(threadId: string): Promise<ChatMessage[]> {
  const response = await fetch(
    `${BACKEND_URL}/api/chat/history?thread_id=${encodeURIComponent(threadId)}`
  );
  if (!response.ok) {
    throw new Error(`Failed to load conversation: ${response.status}`);
  }
  const data = await response.json();
  const convs: ConversationHistory[] = Array.isArray(data) ? data : [data];
  const allMessages: ChatMessage[] = [];
  for (const conv of convs) {
    if (!conv?.messages) continue;
    for (const msg of conv.messages) {
      const m: ChatMessage = {
        role: msg.role as "user" | "assistant",
        content: msg.content,
        timestamp: new Date(msg.timestamp),
        agentResponse: msg.agent_response,
        threadId: conv.thread_id,
      };
      allMessages.push(m);
    }
  }
  return allMessages;
}

/**
 * Submit user feedback for a message.
 */
export async function submitFeedback(
  threadId: string,
  messageIndex: number,
  feedbackType: "thumbs_up" | "thumbs_down" | "flag",
  comment?: string
): Promise<{ success: boolean; message: string }> {
  const response = await fetch(`${BACKEND_URL}/api/chat/feedback`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      thread_id: threadId,
      message_index: messageIndex,
      feedback_type: feedbackType,
      comment,
    }),
  });

  if (!response.ok) {
    throw new Error(`Failed to submit feedback: ${response.status}`);
  }

  return await response.json();
}
