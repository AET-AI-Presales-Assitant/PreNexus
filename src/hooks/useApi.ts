import { useQuery } from '@tanstack/react-query';
import { Session, User, AnalyticsQuery } from '../types';

const BASE_URL = 'http://localhost:3005/api';

export const useSessions = (userId: string | undefined) => {
  return useQuery({
    queryKey: ['sessions', userId],
    queryFn: async () => {
      if (!userId) return [];
      const response = await fetch(`${BASE_URL}/sessions?userId=${userId}`);
      const data = await response.json();
      return data.sessions as Session[];
    },
    enabled: !!userId,
  });
};

export const useSessionMessages = (sessionId: string | null) => {
  return useQuery({
    queryKey: ['messages', sessionId],
    queryFn: async () => {
      if (!sessionId) return [];
      const response = await fetch(`${BASE_URL}/sessions/${sessionId}/messages`);
      const data = await response.json();
      return data.messages;
    },
    enabled: !!sessionId,
  });
};

export const useAdminUsers = (isAdmin: boolean) => {
  return useQuery({
    queryKey: ['admin', 'users'],
    queryFn: async () => {
      const response = await fetch(`${BASE_URL}/admin/users`);
      const data = await response.json();
      return data.users as User[];
    },
    enabled: isAdmin,
  });
};

export const useAdminAnalytics = (isAdmin: boolean) => {
  return useQuery({
    queryKey: ['admin', 'analytics'],
    queryFn: async () => {
      const response = await fetch(`${BASE_URL}/admin/analytics`);
      const data = await response.json();
      return data.queries as AnalyticsQuery[];
    },
    enabled: isAdmin,
  });
};
