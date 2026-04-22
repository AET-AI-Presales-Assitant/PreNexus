import { Role } from '../lib/vectorStore';

export interface User {
  id: string;
  username: string;
  name: string;
  role: Role;
  createdAt: string;
}

export interface Session {
  id: string;
  userId: string;
  title: string;
  workspaceId?: string | null;
  createdAt: number;
}

export interface Workspace {
  id: string;
  name: string;
  createdAt: string;
}

export interface Message {
  id: string;
  sessionId: string;
  role: 'user' | 'agent';
  content: string;
  citations?: Citation[];
  usedDocs?: UsedDoc[];
  thoughts?: { step: string; details: string; status: string }[];
  persistedId?: string;
  cacheId?: string;
  cacheHit?: boolean;
  thumb?: 1 | -1 | 0;
  createdAt: number;
}

export interface Citation {
  id: string;
  title: string;
  source: string;
  category: string;
  role: string;
  score?: number;
  page?: number | null;
  snippet: string;
}

export interface UsedDoc {
  id: string;
  title: string;
  content: string;
  score?: number;
  metadata?: { source?: string; category?: string; role?: string };
}

export interface AnalyticsQuery {
  id: string;
  content: string;
  createdAt: string;
  userName: string;
  userRole: string;
  sessionTitle: string;
  answerContent?: string;
  feedbackValue?: number;
  feedbackNote?: string;
}
