import { GoogleGenerativeAI } from '@google/generative-ai';

export type Role = 'Guest' | 'Employee' | 'Admin';

export type KnowledgeType = 
  | 'Skills, capabilities, Tech stack, solution' 
  | 'Case studies, past project' 
  | 'Presale checklist or workflow';

export const RoleLevels: Record<Role, number> = {
  Guest: 1,
  Employee: 2,
  Admin: 3,
};

export interface Document {
  id: string;
  title: string;
  content: string;
  role: Role;
  topic?: KnowledgeType | string;
  embedding?: number[];
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
