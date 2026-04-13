import { History, MessageSquare, Shield, Users, LogOut, User as UserIcon, Bot, X, Database, MoreVertical, Edit2, Trash2, Book } from 'lucide-react';
import { Button } from './ui/button';
import { User, Session } from '../types';
import { Role } from '../lib/vectorStore';
import { cn } from '../lib/utils';
import { useState, FormEvent } from 'react';
import { Input } from './ui/input';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "./ui/dropdown-menu";

interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
  userRole: Role;
  currentUser: User | null;
  sessions: Session[];
  currentSessionId: string | null;
  onNewConversation: () => void;
  onSelectSession: (id: string) => void;
  onSelectAdminTab: (tab: 'users' | 'analytics' | 'import' | 'knowledge') => void;
  activeAdminTab: 'users' | 'analytics' | 'import' | 'knowledge' | null;
  onLogout: () => void;
  onUpdateSessionTitle?: (id: string, title: string) => void;
  onDeleteSession?: (id: string) => void;
}

export function Sidebar({
  isOpen,
  onClose,
  userRole,
  currentUser,
  sessions,
  currentSessionId,
  onNewConversation,
  onSelectSession,
  onSelectAdminTab,
  activeAdminTab,
  onLogout,
  onUpdateSessionTitle,
  onDeleteSession
}: SidebarProps) {
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState('');

  const handleEditSubmit = (e: FormEvent, id: string) => {
    e.preventDefault();
    if (editTitle.trim() && onUpdateSessionTitle) {
      onUpdateSessionTitle(id, editTitle.trim());
    }
    setEditingSessionId(null);
  };
  return (
    <>
      {/* Overlay for mobile */}
      {isOpen && (
        <div 
          className="fixed inset-0 bg-black/20 backdrop-blur-sm z-40 lg:hidden"
          onClick={onClose}
        />
      )}

      <div className={cn(
        "fixed lg:relative inset-y-0 left-0 w-80 border-r flex flex-col h-full shrink-0 z-50 transition-transform duration-300 ease-in-out lg:translate-x-0",
        userRole === 'SuperManager' ? "bg-[#1e293b] border-neutral-800" : "bg-[#F0F4F9] border-neutral-200",
        !isOpen && "-translate-x-full"
      )}>
        <div className={cn("p-6 border-b flex items-center justify-between", userRole === 'SuperManager' ? "border-neutral-800" : "border-neutral-200")}>
          <div className="flex items-center gap-3">
            <div className={cn("w-10 h-10 rounded-xl flex items-center justify-center shadow-md", userRole === 'SuperManager' ? "bg-indigo-500" : "bg-indigo-600")}>
              <Bot className="w-6 h-6 text-white" />
            </div>
            <div className="flex flex-col">
              <h1 className={cn("text-lg font-bold tracking-tight leading-tight", userRole === 'SuperManager' ? "text-white" : "text-neutral-900")}>
                AI Presales
              </h1>
              <span className={cn("text-sm font-medium leading-tight", userRole === 'SuperManager' ? "text-slate-400" : "text-neutral-500")}>Assistant</span>
            </div>
          </div>
          <Button variant="ghost" size="icon" onClick={onClose} className={cn("lg:hidden hover:border-transparent", userRole === 'SuperManager' ? "text-slate-400 hover:bg-slate-800 hover:text-white" : "text-neutral-500 hover:bg-neutral-200")}>
            <X className="w-5 h-5" />
          </Button>
        </div>

        <div className="p-6 flex-1 overflow-y-auto space-y-8 custom-scrollbar">
          {userRole !== 'SuperManager' && (
          <section>
            <Button 
              onClick={onNewConversation} 
              variant="ghost"
              className="w-full p-2 justify-start gap-3 h-10 text-neutral-600 hover:text-neutral-900 hover:bg-neutral-200/50 hover:border-transparent transition-colors font-semibold text-sm rounded-lg"
            >
              <Edit2 className="w-4 h-4" /> New Conversation
            </Button>
          </section>
          )}

        {userRole === 'SuperManager' && (
          <section className="space-y-4">
            <h2 className="text-xs font-bold text-slate-500 uppercase tracking-wider pl-2">
              Administrator
            </h2>
            <div className="space-y-1">
              <Button
                variant={activeAdminTab === 'users' ? 'secondary' : 'ghost'}
                className={cn(
                  "w-full justify-start gap-3 h-10 text-sm font-medium rounded-lg", 
                  activeAdminTab === 'users' 
                    ? "bg-indigo-500/10 text-indigo-400 shadow-sm hover:bg-indigo-500/10" 
                    : "text-slate-400 hover:bg-slate-800 hover:text-white hover:border-transparent"
                )}
                onClick={() => onSelectAdminTab('users')}
              >
                <Users className="w-4 h-4" /> User Management
              </Button>
              <Button
                variant={activeAdminTab === 'analytics' ? 'secondary' : 'ghost'}
                className={cn(
                  "w-full justify-start gap-3 h-10 text-sm font-medium rounded-lg", 
                  activeAdminTab === 'analytics' 
                    ? "bg-indigo-500/10 text-indigo-400 shadow-sm hover:bg-indigo-500/10" 
                    : "text-slate-400 hover:bg-slate-800 hover:text-white hover:border-transparent"
                )}
                onClick={() => onSelectAdminTab('analytics')}
              >
                <History className="w-4 h-4" /> Analytics
              </Button>
              <Button
                variant={activeAdminTab === 'knowledge' ? 'secondary' : 'ghost'}
                className={cn(
                  "w-full justify-start gap-3 h-10 text-sm font-medium rounded-lg", 
                  activeAdminTab === 'knowledge' 
                    ? "bg-indigo-500/10 text-indigo-400 shadow-sm hover:bg-indigo-500/10" 
                    : "text-slate-400 hover:bg-slate-800 hover:text-white hover:border-transparent"
                )}
                onClick={() => onSelectAdminTab('knowledge')}
              >
                <Book className="w-4 h-4" /> Knowledge Base
              </Button>
              <Button
                variant={activeAdminTab === 'import' ? 'secondary' : 'ghost'}
                className={cn(
                  "w-full justify-start gap-3 h-10 text-sm font-medium rounded-lg", 
                  activeAdminTab === 'import' 
                    ? "bg-indigo-500/10 text-indigo-400 shadow-sm hover:bg-indigo-500/10" 
                    : "text-slate-400 hover:bg-slate-800 hover:text-white hover:border-transparent"
                )}
                onClick={() => onSelectAdminTab('import')}
              >
                <Database className="w-4 h-4" /> Import Data
              </Button>
            </div>
          </section>
        )}

        {/* Chat history */}
        {userRole !== 'SuperManager' && sessions.length > 0 && (
          <section className="space-y-4 flex flex-col h-full overflow-hidden">
            <h2 className="text-xs font-bold text-neutral-500 uppercase tracking-wider pl-2 shrink-0">
              Recent Chats
            </h2>
            <div className="space-y-1 flex-1 overflow-y-auto pr-1 custom-scrollbar">
              {sessions.map(session => (
                <div key={session.id} className="relative group flex items-center">
                  {editingSessionId === session.id ? (
                    <form 
                      onSubmit={(e) => handleEditSubmit(e, session.id)}
                      className="flex-1 px-3 py-1 bg-white border border-indigo-200 rounded-md shadow-sm mx-1 flex items-center"
                    >
                      <Input
                        autoFocus
                        value={editTitle}
                        onChange={(e) => setEditTitle(e.target.value)}
                        onBlur={(e) => handleEditSubmit(e, session.id)}
                        className="h-7 border-none shadow-none focus-visible:ring-0 px-0 text-sm bg-transparent"
                      />
                    </form>
                  ) : (
                    <>
                      <Button
                        variant={currentSessionId === session.id ? 'secondary' : 'ghost'}
                        className={cn(
                          "w-full justify-start gap-3 text-sm truncate pr-8 h-10 font-medium rounded-lg",
                          currentSessionId === session.id 
                            ? "bg-white text-indigo-700 shadow-sm hover:bg-white" 
                            : "text-neutral-600 hover:bg-neutral-200/50 hover:text-neutral-900 hover:border-transparent"
                        )}
                        onClick={() => onSelectSession(session.id)}
                      >
                        <MessageSquare className="w-4 h-4 shrink-0" />
                        <span className="truncate">{session.title}</span>
                      </Button>
                      
                      <div className="absolute right-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button variant="ghost" size="icon" className="h-7 w-7 text-neutral-500 hover:text-neutral-900 hover:border-transparent">
                              <MoreVertical className="w-3.5 h-3.5" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end" className="w-36">
                            <DropdownMenuItem onClick={(e) => {
                              e.stopPropagation();
                              setEditTitle(session.title);
                              setEditingSessionId(session.id);
                            }}>
                              <Edit2 className="w-3.5 h-3.5 mr-2" /> Rename
                            </DropdownMenuItem>
                            <DropdownMenuItem 
                              className="text-red-600 focus:text-red-600"
                              onClick={(e) => {
                                e.stopPropagation();
                                if (onDeleteSession) onDeleteSession(session.id);
                              }}
                            >
                              <Trash2 className="w-3.5 h-3.5 mr-2" /> Delete
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                    </>
                  )}
                </div>
              ))}
            </div>
          </section>
        )}
        </div>

        <div className={cn("p-6 border-t", userRole === 'SuperManager' ? "border-neutral-800 bg-[#1e293b]" : "border-neutral-100 bg-[#F0F4F9]")}>
          <div className="flex items-center justify-between mb-3">
            <h2 className={cn("text-xs font-semibold uppercase tracking-wider flex items-center gap-2", userRole === 'SuperManager' ? "text-slate-500" : "text-neutral-500")}>
              <Shield className="w-4 h-4" /> Profile
            </h2>
            <Button variant="ghost" size="sm" onClick={onLogout} className={cn("h-8 px-2 hover:border-transparent", userRole === 'SuperManager' ? "text-red-400 hover:text-red-300 hover:bg-red-950/30" : "text-red-600 hover:text-red-700 hover:bg-red-50")}>
              <LogOut className="w-3.5 h-3.5 mr-1" /> Sign Out
            </Button>
          </div>
          <div className={cn("border shadow-sm rounded-xl p-3 flex items-center gap-3", userRole === 'SuperManager' ? "bg-slate-800/50 border-slate-700/50" : "bg-white border-neutral-200")}>
            <div className={cn(
              "w-9 h-9 rounded-full flex items-center justify-center font-bold text-sm",
              userRole === 'SuperManager' ? 'bg-red-500/20 text-red-400' : userRole === 'Employee' ? 'bg-indigo-100 text-indigo-600' : userRole === 'Lead' ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'
            )}>
              {currentUser?.name?.charAt(0).toUpperCase() || <UserIcon className="w-4 h-4" />}
            </div>
            <div className="min-w-0 flex-1">
              <div className={cn("text-sm font-bold truncate leading-tight", userRole === 'SuperManager' ? "text-white" : "text-neutral-900")}>{currentUser?.name || ''}</div>
              <div className={cn("text-[11px] font-medium tracking-wide mt-0.5", userRole === 'SuperManager' ? "text-slate-400" : "text-neutral-500")}>{userRole} Account</div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
