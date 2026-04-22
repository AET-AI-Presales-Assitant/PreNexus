import { useQuery } from '@tanstack/react-query';
import { Session, User, AnalyticsQuery, Workspace } from '../types';

import { apiUrl } from '../lib/api';

export const useWorkspaces = (userId: string | undefined) => {
  return useQuery({
    queryKey: ['workspaces', userId],
    queryFn: async () => {
      if (!userId) return [];
      const response = await fetch(apiUrl(`/workspaces?userId=${userId}`));
      const data = await response.json();
      return data.workspaces as Workspace[];
    },
    enabled: !!userId,
  });
};

export const useSessions = (userId: string | undefined) => {
  return useQuery({
    queryKey: ['sessions', userId],
    queryFn: async () => {
      if (!userId) return [];
      const response = await fetch(apiUrl(`/sessions?userId=${userId}`));
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
      const response = await fetch(apiUrl(`/sessions/${sessionId}/messages`));
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
      const response = await fetch(apiUrl(`/admin/users`));
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
      const response = await fetch(apiUrl(`/admin/analytics`));
      const data = await response.json();
      return data.queries as AnalyticsQuery[];
    },
    enabled: isAdmin,
  });
};
