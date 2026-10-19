export type Role = "user" | "assistant";

export interface Message {
  id: string;
  role: Role;
  content: string;
  timestamp: Date;
  isStreaming?: boolean;
  imageIds?: string[];
  error?: boolean;
  /** Id of the backend log record for this answer (from X-Log-Id). */
  logId?: string;
  /** UTC date of that log record (from X-Log-Date). */
  logDate?: string;
  feedback?: "up" | "down";
}

export interface Conversation {
  id: string;
  title: string;
  messages: Message[];
  lastMessage: string;
  updatedAt: Date;
  unread?: number;
  pinned?: boolean;
  favorite?: boolean;
}
