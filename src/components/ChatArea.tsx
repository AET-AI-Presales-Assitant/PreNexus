import { motion } from 'motion/react';
import { User, Bot, Loader2, Send, Menu, ChevronDown, ChevronRight, CheckCircle2, AlertCircle, CircleDashed, Info } from 'lucide-react';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Message } from '../types';
import { Role } from '../lib/vectorStore';
import { useEffect, useRef, FormEvent, useState } from 'react';
import { Dialog, DialogContent } from './ui/dialog';

function renderWithParenthesisItalics(text: string) {
  const nodes: any[] = [];
  const re = /\(([^)]+)\)/g;
  let lastIndex = 0;
  let m: RegExpExecArray | null = null;
  while ((m = re.exec(text)) !== null) {
    const start = m.index;
    const end = re.lastIndex;
    if (start > lastIndex) nodes.push(text.slice(lastIndex, start));
    nodes.push(<em key={`${start}-${end}`} className="text-neutral-600">{text.slice(start, end)}</em>);
    lastIndex = end;
  }
  if (lastIndex < text.length) nodes.push(text.slice(lastIndex));
  return nodes;
}

function renderInlineEmphasis(text: string) {
  const nodes: any[] = [];
  const re = /\*\*(.+?)\*\*/g;
  let lastIndex = 0;
  let m: RegExpExecArray | null = null;
  while ((m = re.exec(text)) !== null) {
    const start = m.index;
    const end = re.lastIndex;
    if (start > lastIndex) nodes.push(...renderWithParenthesisItalics(text.slice(lastIndex, start)));
    const boldText = m[1] || '';
    nodes.push(
      <strong key={`${start}-${end}`} className="font-semibold text-neutral-900">
        {renderWithParenthesisItalics(boldText)}
      </strong>
    );
    lastIndex = end;
  }
  if (lastIndex < text.length) nodes.push(...renderWithParenthesisItalics(text.slice(lastIndex)));
  return nodes;
}

function AgentMessageContent({ content }: { content: string }) {
  const raw = (content || '').replace(/\r\n/g, '\n');
  const lines = raw.split('\n');
  return (
    <div className="whitespace-pre-wrap leading-relaxed text-sm text-neutral-800">
      {lines.map((l, i) => {
        const t = l.trim();
        const isNote = /^lưu ý:|^ghi chú:|^note:/i.test(t);
        return (
          <span key={i}>
            {isNote ? <em className="text-neutral-600">{renderInlineEmphasis(l)}</em> : renderInlineEmphasis(l)}
            {i < lines.length - 1 ? <br /> : null}
          </span>
        );
      })}
    </div>
  );
}

function SourcesUsed({ citations, usedDocs }: { citations: any[]; usedDocs?: any[] }) {
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<any | null>(null);
  const docsById = new Map<string, any>();
  for (const d of (usedDocs || [])) {
    if (d && d.id) docsById.set(String(d.id), d);
  }

  if (!Array.isArray(citations) || citations.length === 0) return null;

  const selectedDoc = selected ? docsById.get(String(selected.id)) : null;
  const metaSource = selectedDoc?.metadata?.source || selected?.source;
  const metaCategory = selectedDoc?.metadata?.category || selected?.category;
  const metaRole = selectedDoc?.metadata?.role || selected?.role;
  const content = selectedDoc?.content;

  const getTags = (text: string) => {
    const tags = (text || '').match(/#\w+/g) || [];
    return tags.slice(0, 8);
  };

  const badgeClass = (category: string) => {
    const c = (category || '').toLowerCase();
    if (c.includes('skills') || c.includes('tech')) return 'bg-blue-50 text-blue-600 border border-blue-100';
    if (c.includes('case')) return 'bg-emerald-50 text-emerald-600 border border-emerald-100';
    if (c.includes('presales') || c.includes('proposal')) return 'bg-purple-50 text-purple-600 border border-purple-100';
    if (c.includes('checklist')) return 'bg-blue-50 text-blue-600 border border-blue-100';
    if (c.includes('know')) return 'bg-purple-50 text-purple-600 border border-purple-100';
    return 'bg-slate-50 text-slate-600 border border-slate-100';
  };

  const viewTitle = selected?.title || selected?.source || 'Document';
  const viewCategory = metaCategory || 'General';
  const viewContent = content || selected?.snippet || '';
  const tags = getTags(viewContent);

  return (
    <div className="mt-4">
      <div className="text-[11px] font-bold text-neutral-500 tracking-wider uppercase mb-2">Knowledge sources used</div>
      <div className="space-y-2">
        {citations.map((c, idx) => (
          <div key={`${c.id}-${idx}`} className="flex items-center gap-3 bg-white/60 border border-neutral-200 rounded-xl px-3 py-2">
            <div className="shrink-0 w-7 h-7 rounded-full bg-indigo-50 flex items-center justify-center">
              <Info className="w-4 h-4 text-indigo-500" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-sm font-semibold text-neutral-900 truncate">{c.title || c.source || 'Document'}</div>
            </div>
            {c.category ? (
              <div className="shrink-0 text-[11px] font-bold text-neutral-700 bg-neutral-100 border border-neutral-200 rounded-full px-2 py-0.5">
                {c.category}
              </div>
            ) : null}
            <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={() => { setSelected(c); setOpen(true); }}>
              View
            </Button>
          </div>
        ))}
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="bg-white rounded-2xl w-full max-w-3xl max-h-[90vh] flex flex-col shadow-2xl overflow-hidden p-0">
          <div className="flex items-center justify-between p-6 border-b border-neutral-100">
            <span className={`text-[11px] px-3 py-1 rounded-full font-medium ${badgeClass(viewCategory)}`}>
              {viewCategory}
            </span>
          </div>

          <div className="p-8 overflow-y-auto flex-1">
            <h2 className="text-2xl font-bold text-neutral-900 mb-4">{viewTitle}</h2>

            {(tags.length > 0 || metaSource || metaRole || typeof selected?.page === 'number') ? (
              <div className="flex flex-wrap gap-2 mb-8">
                {tags.map((tag, i) => (
                  <span key={i} className="text-[12px] bg-neutral-100 text-neutral-600 px-2 py-1 rounded-md">
                    {tag}
                  </span>
                ))}
                {metaSource ? (
                  <span className="text-[12px] bg-neutral-50 text-neutral-600 px-2 py-1 rounded-md border border-neutral-100">
                    {metaSource}
                  </span>
                ) : null}
                {metaRole ? (
                  <span className="text-[12px] bg-neutral-50 text-neutral-600 px-2 py-1 rounded-md border border-neutral-100">
                    {metaRole}
                  </span>
                ) : null}
                {typeof selected?.page === 'number' ? (
                  <span className="text-[12px] bg-neutral-50 text-neutral-600 px-2 py-1 rounded-md border border-neutral-100">
                    page {selected.page}
                  </span>
                ) : null}
              </div>
            ) : null}

            <div className="prose prose-sm md:prose-base max-w-none text-neutral-600 whitespace-pre-wrap">
              {viewContent}
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function ReasoningProtocol({ thoughts, isProcessing }: { thoughts: any[], isProcessing: boolean }) {
  if (!thoughts || thoughts.length === 0) return null;

  const order = ["Decomposition", "Delegation", "Critique", "Synthesis"];
  const latestByStep = new Map<string, any>();
  for (const t of thoughts) {
    if (!t || !t.step) continue;
    latestByStep.set(t.step, t);
  }
  const orderedThoughts = [
    ...order.map(s => latestByStep.get(s)).filter(Boolean),
    ...thoughts.filter(t => t && t.step && !order.includes(t.step))
  ];

  const firstPending = order.map(s => latestByStep.get(s)).find(t => t && t.status === 'pending');
  const current = (isProcessing && firstPending) ? firstPending : (latestByStep.get('Synthesis') || orderedThoughts[orderedThoughts.length - 1]);
  const headerText = isProcessing ? (current?.step || 'Thinking') : 'Reasoning Protocol';
  const headerSubtext = isProcessing ? (current?.details || '') : '';

  return (
    <div className="mb-1">
      <button
        className="flex items-center gap-2 text-left hover:opacity-90 transition-opacity"
      >
        <Bot className="w-3.5 h-3.5 text-indigo-500" />
        <span className="text-[11px] font-bold text-indigo-600 uppercase tracking-wider">{headerText}</span>
      </button>
      {headerSubtext && (
        <div className="mt-0.5 text-[11px] text-neutral-500">{headerSubtext}</div>
      )}
    </div>
  );
}

interface ChatAreaProps {
  isSidebarOpen: boolean;
  onToggleSidebar: () => void;
  messages: Message[];
  isProcessing: boolean;
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
  input,
  onInputChange,
  onSendMessage,
  userRole,
  sessionTitle
}: ChatAreaProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const lastAgentIndex = (() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i]?.role === 'agent') return i;
    }
    return -1;
  })();

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
                <div className="max-w-[85%] md:max-w-[75%]">
                  {isProcessing && msg.role === 'agent' && i === lastAgentIndex && msg.thoughts && msg.thoughts.length > 0 && (
                    <ReasoningProtocol thoughts={msg.thoughts} isProcessing={true} />
                  )}
                  <div className={`rounded-2xl px-5 py-3.5 text-sm shadow-sm ${
                    msg.role === 'user' 
                      ? 'bg-indigo-600 text-white rounded-tr-sm' 
                      : 'bg-neutral-50 border border-neutral-100 text-neutral-800 rounded-tl-sm'
                  }`}>
                    {msg.role === 'agent' && isProcessing && msg.content === '' && (
                      <div className="flex items-center gap-2 mt-1 mb-1">
                        <div className="flex gap-1">
                          <span className="w-1.5 h-1.5 bg-indigo-400 rounded-full animate-bounce [animation-delay:-0.3s]" />
                          <span className="w-1.5 h-1.5 bg-indigo-400 rounded-full animate-bounce [animation-delay:-0.15s]" />
                          <span className="w-1.5 h-1.5 bg-indigo-400 rounded-full animate-bounce" />
                        </div>
                      </div>
                    )}
                    {msg.content && (msg.role === 'agent'
                      ? <AgentMessageContent content={msg.content} />
                      : <div className="whitespace-pre-wrap leading-relaxed">{msg.content}</div>
                    )}
                    {msg.role === 'agent' && Array.isArray(msg.citations) && msg.citations.length > 0 && (
                      <SourcesUsed citations={msg.citations} usedDocs={msg.usedDocs} />
                    )}
                  </div>
                </div>
              </motion.div>
            ))}
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
