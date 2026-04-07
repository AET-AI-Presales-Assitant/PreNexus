export const API_BASE_URL = (import.meta as any).env?.VITE_API_BASE_URL || '/api';

export function apiUrl(path: string) {
  const p = String(path || '');
  if (!p) return API_BASE_URL;
  if (p.startsWith('http://') || p.startsWith('https://')) return p;
  if (p.startsWith('/')) return `${API_BASE_URL}${p}`;
  return `${API_BASE_URL}/${p}`;
}
