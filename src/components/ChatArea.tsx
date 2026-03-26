import { motion } from 'motion/react';
import { User, Bot, Loader2, Send, Menu } from 'lucide-react';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Message } from '../types';
import { AgentTrace } from '../lib/agent';
import { Role } from '../lib/vectorStore';
import { useEffect, useRef, FormEvent } from 'react';

interface ChatAreaProps {
  isSidebarOpen: boolean;
  onToggleSidebar: () => void;
  messages: Message[];
  isProcessing: boolean;
  latestThought: AgentTrace | null;
  input: string;
  onInputChange: (value: string) => void;
  onSendMessage: (e: FormEvent) => void;
  userRole: Role;
  sessionTitle?: string;
}

export function ChatArea({
  isSidebarOpen,
  onToggleSidebar,
  messages,
  isProcessing,
  latestThought,
  input,
  onInputChange,
  onSendMessage,
  userRole,
  sessionTitle
}: ChatAreaProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isProcessing]);

  return (
    <div className="flex-1 flex flex-col min-w-0 bg-white relative">
      <header className="h-16 flex items-center justify-between px-6 bg-white/80 backdrop-blur-md sticky top-0 z-30 shrink-0">
        <div className="flex items-center w-1/4">
          <Button 
            variant="ghost" 
            size="icon" 
            onClick={onToggleSidebar} 
            className="lg:hidden"
          >
            <Menu className="w-5 h-5" />
          </Button>
        </div>
        
        <div className="flex-1 flex justify-center text-center">
          <h2 className="text-lg font-bold text-neutral-900 truncate px-4">{sessionTitle || 'New Conversation'}</h2>
        </div>
        
        <div className="w-1/4 flex justify-end">
          {/* Spacer for centering */}
        </div>
      </header>

      <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-6">
        {messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center max-w-md mx-auto">
            <div className="w-20 h-20 bg-gradient-to-br from-indigo-50 to-violet-50 rounded-3xl flex items-center justify-center mb-6 shadow-inner">
              <Bot className="w-10 h-10 text-indigo-600" />
            </div>
            <h3 className="text-xl font-bold text-neutral-900 mb-2">How can I help with your presales?</h3>
            <p className="text-sm text-neutral-500 leading-relaxed">
              Ask me about past case studies, technical capabilities, or generate an RFP response using our internal knowledge base.
            </p>
          </div>
        ) : (
          <div className="max-w-4xl mx-auto space-y-6">
            {messages.map((msg, i) => (
              <motion.div 
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                key={i} 
                className={`flex gap-4 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}
              >
                <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 shadow-sm ${
                  msg.role === 'user' ? 'bg-neutral-900' : 'bg-indigo-100'
                }`}>
                  {msg.role === 'user' ? <User className="w-4 h-4 text-white" /> : <Bot className="w-4 h-4 text-indigo-600" />}
                </div>
                <div className={`max-w-[85%] md:max-w-[75%] rounded-2xl px-5 py-3.5 text-sm shadow-sm ${
                  msg.role === 'user' 
                    ? 'bg-indigo-600 text-white rounded-tr-sm' 
                    : 'bg-neutral-50 border border-neutral-100 text-neutral-800 rounded-tl-sm'
                }`}>
                  <div className="whitespace-pre-wrap leading-relaxed">{msg.content}</div>
                </div>
              </motion.div>
            ))}
          </div>
        )}
        {isProcessing && (
          <div className="max-w-4xl mx-auto">
            <div className="flex gap-4">
              <div className="w-8 h-8 rounded-full bg-indigo-100 flex items-center justify-center shrink-0 shadow-sm">
                <Bot className="w-4 h-4 text-indigo-600" />
              </div>
              <div className="w-full max-w-[85%] md:max-w-[75%]">
                {latestThought && (
                  <p className="text-[10px] font-bold text-indigo-500 uppercase tracking-wider mb-2 ml-1 flex items-center gap-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 animate-pulse" />
                    {latestThought.step}: {latestThought.details}
                  </p>
                )}
                <div className="bg-neutral-50 border border-neutral-100 rounded-2xl rounded-tl-sm px-5 py-4 shadow-sm flex items-center gap-3">
                  <div className="flex gap-1">
                    <span className="w-1.5 h-1.5 bg-indigo-400 rounded-full animate-bounce [animation-delay:-0.3s]" />
                    <span className="w-1.5 h-1.5 bg-indigo-400 rounded-full animate-bounce [animation-delay:-0.15s]" />
                    <span className="w-1.5 h-1.5 bg-indigo-400 rounded-full animate-bounce" />
                  </div>
                  <span className="text-sm text-neutral-500 font-medium">Agent is thinking...</span>
                </div>
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <div className="p-4 md:p-6 bg-white/80 backdrop-blur-md sticky bottom-0 border-t border-neutral-100">
        <form onSubmit={onSendMessage} className="relative max-w-4xl mx-auto flex items-center bg-white rounded-2xl border border-neutral-200 shadow-sm focus-within:border-indigo-500 focus-within:ring-2 focus-within:ring-indigo-200 transition-all overflow-hidden p-1">
          <Input
            type="text"
            value={input}
            onChange={(e) => onInputChange(e.target.value)}
            placeholder="Ask a question..."
            disabled={isProcessing}
            className="flex-1 border-0 focus-visible:ring-0 focus-visible:ring-offset-0 bg-transparent h-12 px-4 text-base shadow-none hover:border-0 rounded-none"
          />
          <Button
            type="submit"
            disabled={!input.trim() || isProcessing}
            className="h-10 w-10 shrink-0 bg-indigo-500 hover:bg-indigo-600 text-white rounded-xl shadow-none mr-1 flex items-center justify-center p-0 transition-colors"
          >
            <Send className="w-4 h-4 ml-0.5" />
          </Button>
        </form>
      </div>
    </div>
  );
}
