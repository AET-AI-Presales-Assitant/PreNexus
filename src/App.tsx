import React, { useState, useEffect } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { Role, Document } from './lib/vectorStore';
import { User, Message } from './types';
import { useSessions, useAdminUsers, useAdminAnalytics } from './hooks/useApi';

import { Sidebar } from './components/Sidebar';
import { ChatArea } from './components/ChatArea';
import { AuthScreen } from './components/AuthScreen';
import { UserManagement } from './components/admin/UserManagement';
import { DataAnalytics } from './components/admin/DataAnalytics';
import { ImportData } from './components/admin/ImportData';

import { KnowledgeBase } from './components/KnowledgeBase';
import { apiUrl } from './lib/api';

const queryClient = new QueryClient();

function AppContent() {
  const [isLoggedIn, setIsLoggedIn] = useState(false);
  const [userRole, setUserRole] = useState<Role>('Employee');
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isProcessing, setIsProcessing] = useState(false);

  const [authMode, setAuthMode] = useState<'login' | 'register'>('login');
  const [authForm, setAuthForm] = useState({ username: '', password: '', name: '' });
  const [authError, setAuthError] = useState<string | null>(null);
  const [authSuccess, setAuthSuccess] = useState<string | null>(null);
  const [isAuthenticating, setIsAuthenticating] = useState(false);

  const [activeAdminTab, setActiveAdminTab] = useState<'users' | 'analytics' | 'import' | 'knowledge' | null>(null);
  const [isSidebarOpen, setIsSidebarOpen] = useState(window.innerWidth > 1024);
  const [documents, setDocuments] = useState<Document[]>([]);

  const { data: sessions = [], refetch: refetchSessions } = useSessions(currentUser?.id);
  const { data: dbUsers = [], refetch: refetchAdminUsers } = useAdminUsers(userRole === 'SuperManager' && isLoggedIn);
  const { data: dbAnalytics = [] } = useAdminAnalytics(userRole === 'SuperManager' && isLoggedIn);

  const normalizeRole = (r: any): Role => {
    const s = String(r || '').trim();
    const k = s.toLowerCase().replace(/[\s_]+/g, '');
    if (k === 'admin' || k === 'supermanager') return 'SuperManager';
    if (k === 'manager') return 'Manager';
    if (k === 'lead') return 'Lead';
    return 'Employee';
  };

  // Fetch documents from API
  const fetchDocuments = async () => {
    try {
      const response = await fetch(apiUrl('/admin/documents'));
      const data = await response.json();
      if (data.success && data.documents) {
        setDocuments(data.documents);
      }
    } catch (error) {
      console.error('Failed to fetch documents:', error);
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
      setUserRole(normalizeRole(user.role));
      setIsLoggedIn(true);
    }
  }, []);

  const createNewSession = async (title?: string) => {
    if (!currentUser) return;
    try {
      const response = await fetch(apiUrl('/sessions'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ userId: currentUser.id, title: title || `New Chat ${sessions.length + 1}` })
      });
      const data = await response.json();
      if (data.success) {
        refetchSessions();
        setCurrentSessionId(data.session.id);
        return data.session.id;
      }
    } catch (e) {
      console.error('Failed to create session', e);
    }
  };

  const handleDeleteSession = async (sessionId: string) => {
    try {
      const response = await fetch(apiUrl(`/sessions/${sessionId}`), {
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
      const response = await fetch(apiUrl(`/sessions/${sessionId}`), {
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
      const response = await fetch(apiUrl(`/sessions/${sessionId}/messages`));
      const data = await response.json();
      if (data.success) {
        setMessages(data.messages);
        setCurrentSessionId(sessionId);
        setActiveAdminTab(null);
      }
    } catch (e) {
      console.error('Failed to load messages', e);
    }
  };

  const handleImportDocument = async (_title: string, _content: string, _role: Role, _topic?: string) => {
    // Chỉ cần fetch lại documents từ server vì đã xử lý qua backend
    await fetchDocuments();
  };

  const handleAnalyzeGaps = async (queries: string[]) => {
    const response = await fetch(apiUrl('/admin/analyze_gaps'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ queries })
    });
    const data = await response.json();
    if (data.success) return data.result;
    return null;
  };

  const handleAuth = async (e: React.FormEvent) => {
    e.preventDefault();
    setAuthError(null);
    setAuthSuccess(null);
    setIsAuthenticating(true);
    const endpoint = authMode === 'login' ? '/api/login' : '/api/register';
    const controller = new AbortController();
    const timeoutMs = 15000;
    const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(apiUrl(endpoint.replace(/^\/api/, '')), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(authForm),
        signal: controller.signal,
      });
      const data = await response.json();
      if (data.success) {
        if (authMode === 'register') {
          setAuthSuccess('Registration successful! Please sign in.');
          setAuthMode('login');
          setAuthForm(prev => ({ ...prev, password: '' }));
        } else {
          setCurrentUser(data.user);
          setUserRole(normalizeRole(data.user.role));
          localStorage.setItem('rag_user', JSON.stringify(data.user));
          setIsLoggedIn(true);
          
          if (normalizeRole(data.user.role) === 'SuperManager') {
            setActiveAdminTab('knowledge');
          } else {
            setActiveAdminTab(null);
          }
        }
      } else {
        setAuthError(data.message || 'Authentication failed');
      }
    } catch (error) {
      if ((error as any)?.name === 'AbortError') {
        setAuthError('Request timed out. Please try again.');
      } else {
        setAuthError('Server connection failed');
      }
    } finally {
      window.clearTimeout(timeoutId);
      setIsAuthenticating(false);
    }
  };

  const sendMessage = async (query: string) => {
    if (!query.trim() || isProcessing) return;
    const text = query.trim();
    setInput('');
    const tempUserMsg: Message = { id: Date.now().toString(), sessionId: currentSessionId || '', role: 'user', content: text, createdAt: Date.now() };
    setMessages(prev => [...prev, tempUserMsg]);
    setIsProcessing(true);

    let sessionId = currentSessionId;
    if (!sessionId && currentUser) {
      sessionId = await createNewSession(query.substring(0, 30) + '...');
    }

    const agentMsgId = (Date.now() + 1).toString();
    const tempAgentMsg: Message = { id: agentMsgId, sessionId: sessionId || '', role: 'agent', content: '', citations: [], thoughts: [], createdAt: Date.now() };
    setMessages(prev => [...prev, tempAgentMsg]);

    try {
      if (sessionId) {
        await fetch(apiUrl('/messages'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ sessionId, role: 'user', content: text })
        });
      }

      const chatRes = await fetch(apiUrl('/chat'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          userId: currentUser?.id || null,
          userRole,
          sessionId: sessionId || null,
          topK: 4,
          history: [...messages, tempUserMsg].map(m => ({ role: m.role, content: m.content }))
        })
      });

      const contentType = chatRes.headers.get('content-type') || '';
      if (contentType.includes('application/json')) {
        const data = await chatRes.json().catch(() => null);
        const msgText = (data?.message || data?.error || 'Error processing request.') as string;
        setMessages(prev => prev.map(msg =>
          msg.id === agentMsgId ? { ...msg, content: msgText } : msg
        ));
        return;
      }

      if (!chatRes.body) throw new Error('No response body');

      const reader = chatRes.body.getReader();
      const decoder = new TextDecoder();
      let done = false;
      let buffer = '';
      let bufferedText = '';
      let allowAnswer = false;
      const stepOrder = ['Decomposition', 'Delegation', 'Critique', 'Synthesis'];
      const stepStatus: Record<string, string> = {};

      while (!done) {
        const { value, done: doneReading } = await reader.read();
        done = doneReading;
        if (value) {
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || ''; // keep the incomplete line in buffer

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              const dataStr = line.substring(6);
              if (!dataStr.trim()) continue;
              try {
                const data = JSON.parse(dataStr);
                if (data.type === 'trace') {
                  const newThought = {
                    step: data.step,
                    details: data.details,
                    status: data.status
                  };
                  if (newThought.step && typeof newThought.status === 'string') {
                    stepStatus[newThought.step] = newThought.status;
                    const ok = stepOrder.every(s => stepStatus[s] === 'success');
                    if (ok && !allowAnswer) {
                      allowAnswer = true;
                      if (bufferedText) {
                        const toFlush = bufferedText;
                        bufferedText = '';
                        setMessages(prev => prev.map(msg => 
                          msg.id === agentMsgId ? { ...msg, content: msg.content + toFlush } : msg
                        ));
                      }
                    }
                  }
                  setMessages(prev => prev.map(msg => 
                    msg.id === agentMsgId
                      ? {
                          ...msg,
                          thoughts: (() => {
                            const current = Array.isArray(msg.thoughts) ? msg.thoughts : [];
                            const idx = current.findIndex(t => t && t.step === newThought.step);
                            if (idx >= 0) {
                              const next = current.slice();
                              next[idx] = newThought;
                              return next;
                            }
                            return [...current, newThought];
                          })()
                        }
                      : msg
                  ));
                } else if (data.type === 'chunk') {
                  if (!allowAnswer) {
                    bufferedText += (data.content || '');
                  } else {
                    setMessages(prev => prev.map(msg => 
                      msg.id === agentMsgId ? { ...msg, content: msg.content + (data.content || '') } : msg
                    ));
                  }
                } else if (data.type === 'clear') {
                  bufferedText = '';
                  setMessages(prev => prev.map(msg => 
                    msg.id === agentMsgId ? { ...msg, content: '' } : msg
                  ));
                } else if (data.type === 'answer_start') {
                  if (!allowAnswer) {
                    allowAnswer = true;
                    if (bufferedText) {
                      const toFlush = bufferedText;
                      bufferedText = '';
                      setMessages(prev => prev.map(msg =>
                        msg.id === agentMsgId ? { ...msg, content: msg.content + toFlush } : msg
                      ));
                    }
                  }
                } else if (data.type === 'done') {
                  if (!allowAnswer && bufferedText) {
                    const toFlush = bufferedText;
                    bufferedText = '';
                    allowAnswer = true;
                    setMessages(prev => prev.map(msg => 
                      msg.id === agentMsgId ? { ...msg, content: msg.content + toFlush } : msg
                    ));
                  }
                  setMessages(prev => prev.map(msg => 
                    msg.id === agentMsgId ? { ...msg, citations: data.citations || [], usedDocs: data.used_docs || [] } : msg
                  ));
                } else if (data.type === 'error') {
                  setMessages(prev => prev.map(msg => 
                    msg.id === agentMsgId ? { ...msg, content: msg.content + '\n\n[Error: ' + data.message + ']' } : msg
                  ));
                }
              } catch (err) {
                console.error('Error parsing SSE data:', err);
              }
            }
          }
        }
      }
    } catch (error) {
      setMessages(prev => prev.map(msg => 
        msg.id === agentMsgId ? { ...msg, content: 'Error processing request.' } : msg
      ));
    } finally {
      setIsProcessing(false);
    }
  };

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isProcessing) return;
    await sendMessage(input.trim());
  };

  const handleDeleteDocument = async (id: string) => {
    try {
      const response = await fetch(apiUrl(`/admin/documents/${id}`), {
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
        onAuthModeChange={(mode) => {
          setAuthMode(mode);
          setAuthForm({ username: '', password: '', name: '' });
          setAuthError(null);
          setAuthSuccess(null);
        }}
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
          setAuthMode('login'); 
          setAuthForm({ username: '', password: '', name: '' });
          setAuthError(null);
          setAuthSuccess(null);
        }}
        onUpdateSessionTitle={handleUpdateSessionTitle}
        onDeleteSession={handleDeleteSession}
      />
      
      {activeAdminTab === 'users' ? (
        <div className="flex-1 overflow-hidden">
            <UserManagement users={dbUsers} onRefresh={refetchAdminUsers} />
        </div>
      ) : activeAdminTab === 'analytics' ? (
        <div className="flex-1 overflow-hidden">
            <DataAnalytics analytics={dbAnalytics} onAnalyzeGaps={async (queries) => (await handleAnalyzeGaps(queries)) || ''} />
        </div>
      ) : activeAdminTab === 'import' ? (
        <div className="flex-1 overflow-hidden">
            <ImportData onImport={handleImportDocument} />
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
      ) : userRole !== 'SuperManager' ? (
        <ChatArea
          onToggleSidebar={() => setIsSidebarOpen(!isSidebarOpen)}
          messages={messages}
          isProcessing={isProcessing}
          input={input}
          onInputChange={setInput}
          onSendMessage={handleSendMessage}
          onSendText={(text) => sendMessage(text)}
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
