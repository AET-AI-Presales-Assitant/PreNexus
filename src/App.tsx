import React, { useState, useEffect } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { GoogleGenerativeAI } from "@google/generative-ai";

import { Role, Document, getEmbedding } from './lib/vectorStore';
import { RAGAgent, AgentTrace, analyzeDocument } from './lib/agent';
import { User, Message } from './types';
import { useSessions, useAdminUsers, useAdminAnalytics } from './hooks/useApi';

import { Sidebar } from './components/Sidebar';
import { ChatArea } from './components/ChatArea';
import { AuthScreen } from './components/AuthScreen';
import { UserManagement } from './components/admin/UserManagement';
import { DataAnalytics } from './components/admin/DataAnalytics';
import { ImportData } from './components/admin/ImportData';

import { KnowledgeBase } from './components/KnowledgeBase';

const API_KEY = process.env.GEMINI_API_KEY || '';
const ai = new GoogleGenerativeAI(API_KEY);
const agent = new RAGAgent(API_KEY);

const queryClient = new QueryClient();

function AppContent() {
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [userRole, setUserRole] = useState<Role>('Employee');
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isProcessing, setIsProcessing] = useState(false);
  const [latestThought, setLatestThought] = useState<AgentTrace | null>(null);

  const [authMode, setAuthMode] = useState<'select' | 'login' | 'register'>('select');
  const [authForm, setAuthForm] = useState({ username: '', password: '', name: '' });
  const [authError, setAuthError] = useState<string | null>(null);
  const [authSuccess, setAuthSuccess] = useState<string | null>(null);
  const [isAuthenticating, setIsAuthenticating] = useState(false);

  const [activeAdminTab, setActiveAdminTab] = useState<'users' | 'analytics' | 'import' | 'knowledge' | null>(null);
  const [isSidebarOpen, setIsSidebarOpen] = useState(window.innerWidth > 1024);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [isLoadingDocs, setIsLoadingDocs] = useState(false);

  const { data: sessions = [], refetch: refetchSessions } = useSessions(currentUser?.id);
  const { data: dbUsers = [] } = useAdminUsers(userRole === 'Admin' && isLoggedIn);
  const { data: dbAnalytics = [] } = useAdminAnalytics(userRole === 'Admin' && isLoggedIn);

  // Fetch documents from API
  const fetchDocuments = async () => {
    setIsLoadingDocs(true);
    try {
      const response = await fetch('http://localhost:3005/api/admin/documents');
      const data = await response.json();
      if (data.success && data.documents) {
        setDocuments(data.documents);
      }
    } catch (error) {
      console.error('Failed to fetch documents:', error);
    } finally {
      setIsLoadingDocs(false);
    }
  };

  useEffect(() => {
    if (isLoggedIn) {
      fetchDocuments();
    }
  }, [isLoggedIn]);

  // We no longer need to initialize local embeddings since it's handled by ChromaDB on backend
  // useEffect(() => {
  //   const initEmbeddings = async () => { ...
  // }, []);

  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth <= 1024) {
        setIsSidebarOpen(false);
      } else {
        setIsSidebarOpen(true);
      }
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  useEffect(() => {
    const savedUser = localStorage.getItem('rag_user');
    if (savedUser) {
      const user = JSON.parse(savedUser);
      setCurrentUser(user);
      setUserRole(user.role);
      setIsLoggedIn(true);
    }
  }, []);

  const createNewSession = async (title?: string) => {
    if (!currentUser) return;
    try {
      const response = await fetch('http://localhost:3005/api/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ userId: currentUser.id, title: title || `New Chat ${sessions.length + 1}` })
      });
      const data = await response.json();
      if (data.success) {
        refetchSessions();
        setCurrentSessionId(data.session.id);
        setLatestThought(null);
        return data.session.id;
      }
    } catch (e) {
      console.error('Failed to create session', e);
    }
  };

  const handleDeleteSession = async (sessionId: string) => {
    try {
      const response = await fetch(`http://localhost:3005/api/sessions/${sessionId}`, {
        method: 'DELETE'
      });
      if (response.ok) {
        refetchSessions();
        if (currentSessionId === sessionId) {
          setMessages([]);
          setCurrentSessionId(null);
        }
      }
    } catch (e) {
      console.error('Failed to delete session', e);
    }
  };

  const handleUpdateSessionTitle = async (sessionId: string, title: string) => {
    try {
      const response = await fetch(`http://localhost:3005/api/sessions/${sessionId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title })
      });
      if (response.ok) {
        refetchSessions();
      }
    } catch (e) {
      console.error('Failed to update session title', e);
    }
  };
  const loadSessionMessages = async (sessionId: string) => {
    try {
      const response = await fetch(`http://localhost:3005/api/sessions/${sessionId}/messages`);
      const data = await response.json();
      if (data.success) {
        setMessages(data.messages);
        setCurrentSessionId(sessionId);
        setLatestThought(null);
        setActiveAdminTab(null);
      }
    } catch (e) {
      console.error('Failed to load messages', e);
    }
  };

  const handleImportDocument = async (title: string, content: string, role: Role, topic?: string) => {
    // Chỉ cần fetch lại documents từ server vì đã xử lý qua backend
    await fetchDocuments();
  };

  const handleAnalyzeGaps = async (queries: string[]) => {
    const prompt = `
      You are an AI analyst for a Presales Knowledge Base. Analyze the following user queries to provide insights for the admin.

      USER QUERIES:
      ${queries.slice(0, 100).join('\n')}

      REQUIREMENTS:
      Return the result STRICTLY as a JSON object matching this structure:
      {
        "topInterests": [
          {
            "topic": "string (e.g., Technical capabilities, case studies)",
            "reason": "string (Why presales team is asking about this)"
          }
        ],
        "knowledgeGaps": [
          {
            "question": "string (The specific question or topic missing)",
            "suggestion": "string (Actionable advice for the admin to add document)"
          }
        ]
      }

      Limit topInterests to 3 items, and knowledgeGaps to 2-3 items. No markdown, only JSON.
    `;
    const model = ai.getGenerativeModel({ 
      model: process.env.GEMINI_MODEL || 'gemini-1.5-flash',
      generationConfig: {
        responseMimeType: 'application/json'
      }
    });
    const response = await model.generateContent(prompt);
    return response.response.text();
  };

  const handleAuth = async (e: React.FormEvent) => {
    e.preventDefault();
    setAuthError(null);
    setAuthSuccess(null);
    setIsAuthenticating(true);
    const endpoint = authMode === 'login' ? '/api/login' : '/api/register';
    try {
      const response = await fetch(`http://localhost:3005${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(authForm)
      });
      const data = await response.json();
      if (data.success) {
        if (authMode === 'register') {
          setAuthSuccess('Registration successful! Please sign in.');
          setAuthMode('login');
          setAuthForm(prev => ({ ...prev, password: '' }));
        } else {
          setCurrentUser(data.user);
          setUserRole(data.user.role);
          if (data.user.role !== 'Guest') localStorage.setItem('rag_user', JSON.stringify(data.user));
          setIsLoggedIn(true);
          
          if (data.user.role === 'Admin') {
            setActiveAdminTab('analytics');
          } else {
            setActiveAdminTab(null);
          }
        }
      } else {
        setAuthError(data.message || 'Authentication failed');
      }
    } catch (error) {
      setAuthError('Server connection failed');
    } finally {
      setIsAuthenticating(false);
    }
  };

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isProcessing) return;
    const query = input.trim();
    setInput('');
    const tempUserMsg: Message = { id: Date.now().toString(), sessionId: currentSessionId || '', role: 'user', content: query, createdAt: Date.now() };
    setMessages(prev => [...prev, tempUserMsg]);
    setIsProcessing(true);

    let sessionId = currentSessionId;
    if (!sessionId && currentUser && userRole !== 'Guest') {
      sessionId = await createNewSession(query.substring(0, 30) + '...');
    }

    try {
      if (sessionId) {
        await fetch('http://localhost:3005/api/messages', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ sessionId, role: 'user', content: query })
        });
      }

      const answer = await agent.execute(query, documents, userRole, (trace) => setLatestThought(trace), [...messages, tempUserMsg]);

      if (sessionId) {
        await fetch('http://localhost:3005/api/messages', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ sessionId, role: 'agent', content: answer })
        });
      }
      const tempAgentMsg: Message = { id: (Date.now() + 1).toString(), sessionId: sessionId || '', role: 'agent', content: answer, createdAt: Date.now() };
      setMessages(prev => [...prev, tempAgentMsg]);
    } catch (error) {
      setMessages(prev => [...prev, { id: 'err', sessionId: '', role: 'agent', content: 'Error processing request.', createdAt: Date.now() }]);
    } finally {
      setIsProcessing(false);
    }
  };

  const handleDeleteDocument = async (id: string) => {
    try {
      const response = await fetch(`http://localhost:3005/api/admin/documents/${id}`, {
        method: 'DELETE'
      });
      const data = await response.json();
      if (data.success) {
        setDocuments(prev => prev.filter(doc => doc.id !== id));
      } else {
        console.error("Failed to delete document:", data.message);
      }
    } catch (error) {
      console.error("Error deleting document:", error);
    }
  };

  const handleEditDocument = (id: string, newTitle: string, newContent: string) => {
    // Để edit thì cần một endpoint API update (tạm thời để cập nhật local state, thực tế sẽ cần backend update metadata ChromaDB)
    setDocuments(prev => prev.map(doc => 
      doc.id === id ? { ...doc, title: newTitle, content: newContent } : doc
    ));
  };

  if (!isLoggedIn) {
    return (
      <AuthScreen
        authMode={authMode}
        userRole={userRole}
        onAuthModeChange={(mode) => {
          setAuthMode(mode);
          setAuthForm({ username: '', password: '', name: '' });
          setAuthError(null);
          setAuthSuccess(null);
        }}
        onUserRoleChange={setUserRole}
        onContinueAsGuest={() => { setUserRole('Guest'); setIsLoggedIn(true); }}
        handleAuth={handleAuth}
        authForm={authForm}
        onAuthFormChange={setAuthForm}
        authError={authError}
        authSuccess={authSuccess}
        isAuthenticating={isAuthenticating}
      />
    );
  }

  return (
    <div className="flex h-screen bg-neutral-50 text-neutral-900 font-sans">
      <Sidebar
        isOpen={isSidebarOpen}
        onClose={() => setIsSidebarOpen(false)}
        userRole={userRole}
        currentUser={currentUser}
        sessions={sessions}
        currentSessionId={currentSessionId}
        onNewConversation={() => { 
          setMessages([]); 
          setCurrentSessionId(null); 
          setLatestThought(null); 
          setActiveAdminTab(null);
          if (window.innerWidth <= 1024) setIsSidebarOpen(false);
        }}
        onSelectSession={(id) => {
          loadSessionMessages(id);
          if (window.innerWidth <= 1024) setIsSidebarOpen(false);
        }}
        onSelectAdminTab={(tab) => {
          setActiveAdminTab(tab);
          if (window.innerWidth <= 1024) setIsSidebarOpen(false);
        }}
        activeAdminTab={activeAdminTab}
        onLogout={() => { 
          setIsLoggedIn(false); 
          setCurrentUser(null); 
          localStorage.removeItem('rag_user'); 
          setMessages([]); 
          setCurrentSessionId(null); 
          setAuthMode('select'); 
          setAuthForm({ username: '', password: '', name: '' });
          setAuthError(null);
          setAuthSuccess(null);
        }}
        onUpdateSessionTitle={handleUpdateSessionTitle}
        onDeleteSession={handleDeleteSession}
      />
      
      {activeAdminTab === 'users' ? (
        <div className="flex-1 overflow-hidden">
            <UserManagement users={dbUsers} />
        </div>
      ) : activeAdminTab === 'analytics' ? (
        <div className="flex-1 overflow-hidden">
            <DataAnalytics analytics={dbAnalytics} onAnalyzeGaps={async (queries) => (await handleAnalyzeGaps(queries)) || ''} />
        </div>
      ) : activeAdminTab === 'import' ? (
        <div className="flex-1 overflow-hidden">
            <ImportData onImport={handleImportDocument} existingDocs={documents} />
        </div>
      ) : activeAdminTab === 'knowledge' ? (
        <div className="flex-1 overflow-hidden">
          <KnowledgeBase 
            documents={documents} 
            userRole={userRole} 
            onDeleteDocument={handleDeleteDocument}
            onEditDocument={handleEditDocument}
          />
        </div>
      ) : userRole !== 'Admin' ? (
        <ChatArea
          isSidebarOpen={isSidebarOpen}
          onToggleSidebar={() => setIsSidebarOpen(!isSidebarOpen)}
          messages={messages}
          isProcessing={isProcessing}
          latestThought={latestThought}
          input={input}
          onInputChange={setInput}
          onSendMessage={handleSendMessage}
          userRole={userRole}
          sessionTitle={sessions.find(s => s.id === currentSessionId)?.title}
        />
      ) : (
        <div className="flex-1 flex items-center justify-center text-neutral-400">
           Select an option from the sidebar
        </div>
      )}
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AppContent />
    </QueryClientProvider>
  );
}
