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
  createdAt: number;
}

export interface Message {
  id: string;
  sessionId: string;
  role: 'user' | 'agent';
  content: string;
  createdAt: number;
}

export interface AnalyticsQuery {
  id: string;
  content: string;
  createdAt: string;
  userName: string;
  userRole: string;
  sessionTitle: string;
  answerContent?: string;
}
