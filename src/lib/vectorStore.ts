import { GoogleGenerativeAI } from '@google/generative-ai';

export type Role = 'Employee' | 'Lead' | 'Manager' | 'SuperManager';

export const Roles: Role[] = ['Employee', 'Lead', 'Manager', 'SuperManager'];

export type KnowledgeType = 
  | 'Skills, capabilities, Tech stack, solution' 
  | 'Case studies, past project' 
  | 'Presale checklist or workflow';

export const RoleLevels: Record<Role, number> = {
  Employee: 1,
  Lead: 2,
  Manager: 3,
  SuperManager: 4,
};

export interface Document {
  id: string;
  title: string;
  content: string;
  role: Role;
  topic?: KnowledgeType | string;
  embedding?: number[];
  createdAt?: number;
  source?: string;
  tags?: string[];
}

export async function getEmbedding(text: string, ai: GoogleGenerativeAI): Promise<number[]> {
  const model = ai.getGenerativeModel({ model: 'gemini-embedding-001' });
  const result = await model.embedContent(text);
  return result.embedding.values || [];
}

export function cosineSimilarity(a: number[], b: number[]): number {
  if (a.length !== b.length || a.length === 0) return 0;
  let dotProduct = 0;
  let normA = 0;
  let normB = 0;
  for (let i = 0; i < a.length; i++) {
    dotProduct += a[i] * b[i];
    normA += a[i] * a[i];
    normB += b[i] * b[i];
  }
  if (normA === 0 || normB === 0) return 0;
  return dotProduct / (Math.sqrt(normA) * Math.sqrt(normB));
}
