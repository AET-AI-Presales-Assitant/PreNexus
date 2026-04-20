import { useState, MouseEvent } from 'react';
import { Document, RoleLevels, Role } from '../lib/vectorStore';
import { Book, Code, Briefcase, CheckSquare, Search, FileText, Calendar, MoreVertical, Edit2, Trash2, X, SlidersHorizontal, ChevronDown } from 'lucide-react';
import { Input } from './ui/input';
import { Button } from './ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "./ui/dropdown-menu";

interface KnowledgeBaseProps {
  documents: Document[];
  userRole: Role;
  onDeleteDocument?: (id: string) => void;
  onEditDocument?: (id: string, newTitle: string, newContent: string) => void;
}

const KNOWLEDGE_TYPES = [
  {
    id: 'skills_tech',
    label: 'Skills & Capabilities',
    icon: <Code className="w-5 h-5 text-blue-500" />,
    color: 'bg-blue-50 border-blue-100 text-blue-700'
  },
  {
    id: 'case_study',
    label: 'Case Studies',
    icon: <Briefcase className="w-5 h-5 text-indigo-500" />,
    color: 'bg-emerald-50 border-emerald-100 text-emerald-700'
  },
  {
    id: 'presales',
    label: 'Presale Workflows',
    icon: <CheckSquare className="w-5 h-5 text-emerald-500" />,
    color: 'bg-purple-50 border-purple-100 text-purple-700'
  },
  {
    id: 'General', // Fallback for uncategorized or older docs
    label: 'General Knowledge',
    icon: <Book className="w-5 h-5 text-slate-500" />,
    color: 'bg-slate-50 border-slate-100 text-slate-700'
  }
];

export function KnowledgeBase({
  documents,
  userRole,
  onDeleteDocument,
  onEditDocument,
}: KnowledgeBaseProps) {
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedType, setSelectedType] = useState<string | null>(null);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [sourceFilter, setSourceFilter] = useState<string>('');
  const [tagFilter, setTagFilter] = useState<string>('');
  const [dateFrom, setDateFrom] = useState<string>('');
  const [dateTo, setDateTo] = useState<string>('');
  const [sortBy, setSortBy] = useState<'newest' | 'oldest' | 'relevance'>('newest');
  const [selectedDoc, setSelectedDoc] = useState<Document | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [editForm, setEditForm] = useState({ title: '', content: '' });

  const normalize = (text: string) => {
    const t = (text || '').toLowerCase().normalize('NFKD').replace(/[\u0300-\u036f]/g, '');
    return t.replace(/[^a-z0-9]+/g, ' ').trim();
  };

  const tokenize = (text: string) => normalize(text).split(' ').filter(Boolean);

  const getTypeId = (doc: Document) => (doc.topic && KNOWLEDGE_TYPES.find(t => t.id === doc.topic) ? doc.topic : 'General');

  const getDocTags = (doc: Document) => {
    const raw = Array.isArray(doc.tags) ? doc.tags : [];
    const cleaned = raw.map(t => String(t || '').trim()).filter(Boolean);
    if (cleaned.length > 0) return cleaned.map(t => (t.startsWith('#') ? t : `#${t}`));
    return (doc.content.match(/#\w+/g) || []).slice(0, 12);
  };

  const parseDateToMs = (s: string, endOfDay: boolean) => {
    if (!s) return null;
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
    if (!m) return null;
    const y = Number(m[1]);
    const mo = Number(m[2]) - 1;
    const d = Number(m[3]);
    const dt = endOfDay ? new Date(y, mo, d, 23, 59, 59, 999) : new Date(y, mo, d, 0, 0, 0, 0);
    return dt.getTime();
  };

  const queryTokens = tokenize(searchTerm);
  const sourceNeedle = normalize(sourceFilter);
  const tagNeedle = normalize(tagFilter);
  const fromMs = parseDateToMs(dateFrom, false);
  const toMs = parseDateToMs(dateTo, true);

  const accessibleDocs = documents.filter(doc => RoleLevels[userRole] >= RoleLevels[doc.role]);

  const filteredDocs = accessibleDocs.filter(doc => {
    const typeId = getTypeId(doc);
    if (selectedType && typeId !== selectedType) return false;
    if (sourceNeedle) {
      const src = normalize(doc.source || '');
      if (!src.includes(sourceNeedle)) return false;
    }
    if (tagNeedle) {
      const tags = getDocTags(doc).map(t => normalize(t));
      if (!tags.some(t => t.includes(tagNeedle))) return false;
    }
    if (fromMs !== null || toMs !== null) {
      const ts = typeof doc.createdAt === 'number' ? doc.createdAt : 0;
      if (fromMs !== null && ts < fromMs) return false;
      if (toMs !== null && ts > toMs) return false;
    }
    if (queryTokens.length > 0) {
      const hay = tokenize(`${doc.title} ${doc.content} ${(doc.source || '')} ${getDocTags(doc).join(' ')} ${typeId} ${doc.role}`);
      const haySet = new Set(hay);
      const overlap = queryTokens.reduce((n, t) => n + (haySet.has(t) ? 1 : 0), 0);
      if (overlap === 0) return false;
    }
    return true;
  });

  const relevanceScore = (doc: Document) => {
    if (queryTokens.length === 0) return 0;
    const typeId = getTypeId(doc);
    const titleN = normalize(doc.title);
    const contentN = normalize(doc.content);
    const srcN = normalize(doc.source || '');
    const tagsN = normalize(getDocTags(doc).join(' '));
    const hayTokens = tokenize(`${titleN} ${tagsN} ${srcN} ${typeId} ${contentN}`);
    const haySet = new Set(hayTokens);
    const overlap = queryTokens.reduce((n, t) => n + (haySet.has(t) ? 1 : 0), 0);
    const phraseBoost = normalize(searchTerm) && (titleN.includes(normalize(searchTerm)) ? 3 : 0);
    const tagBoost = queryTokens.some(t => tagsN.includes(t)) ? 1 : 0;
    return overlap + phraseBoost + tagBoost;
  };

  const displayDocs = filteredDocs.slice().sort((a, b) => {
    if (sortBy === 'newest') return (b.createdAt || 0) - (a.createdAt || 0);
    if (sortBy === 'oldest') return (a.createdAt || 0) - (b.createdAt || 0);
    const sa = relevanceScore(a);
    const sb = relevanceScore(b);
    if (sb !== sa) return sb - sa;
    return (b.createdAt || 0) - (a.createdAt || 0);
  });

  const countsByType = accessibleDocs.reduce((acc, doc) => {
    const typeId = getTypeId(doc);
    acc[typeId] = (acc[typeId] || 0) + 1;
    return acc;
  }, {} as Record<string, number>);

  const handleEditClick = (doc: Document, e: MouseEvent) => {
    e.stopPropagation();
    setSelectedDoc(doc);
    setEditForm({ title: doc.title, content: doc.content });
    setIsEditing(true);
  };

  const handleSaveEdit = () => {
    if (selectedDoc && onEditDocument) {
      onEditDocument(selectedDoc.id, editForm.title, editForm.content);
      // Update local state for immediate feedback if needed, though props should update
      setSelectedDoc({ ...selectedDoc, title: editForm.title, content: editForm.content });
    }
    setIsEditing(false);
  };

  const handleDeleteClick = (id: string, e: MouseEvent) => {
    e.stopPropagation();
    if (confirm('Are you sure you want to delete this document?')) {
      if (onDeleteDocument) onDeleteDocument(id);
      if (selectedDoc?.id === id) setSelectedDoc(null);
    }
  };

  // Helper to format date
  const formatDate = (timestamp?: number) => {
    if (!timestamp) return '—';
    return new Date(timestamp).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  };

  const clearAllFilters = () => {
    setSearchTerm('');
    setSelectedType(null);
    setSourceFilter('');
    setTagFilter('');
    setDateFrom('');
    setDateTo('');
    setSortBy('newest');
  };

  const canClearAll = Boolean(
    searchTerm.trim() ||
    selectedType !== null ||
    sourceFilter.trim() ||
    tagFilter.trim() ||
    dateFrom ||
    dateTo ||
    sortBy !== 'newest'
  );

  return (
    <div className="flex flex-col h-full bg-neutral-50 overflow-hidden">
      <header className="px-8 py-6 bg-white border-b border-neutral-200 shrink-0">
        <div>
          <h1 className="text-2xl font-bold text-neutral-900 flex items-center gap-2">
            <Book className="w-6 h-6 text-indigo-600" />
            Knowledge Base
          </h1>
          <p className="text-neutral-500 mt-1">Browse internal capabilities, case studies, and workflows.</p>
        </div>

        {/* Filters */}
        <div className="flex gap-2 mt-6 overflow-x-auto pb-2 scrollbar-hide">
          <button
            onClick={() => setSelectedType(null)}
            className={`px-4 py-2 rounded-full text-sm font-medium whitespace-nowrap transition-colors ${
              selectedType === null 
                ? 'bg-[#1e293b] text-white' 
                : 'bg-white border border-neutral-200 text-neutral-600 hover:bg-neutral-50'
            }`}
          >
            All Knowledge
          </button>
          {KNOWLEDGE_TYPES.map(type => {
            const count = countsByType[type.id] || 0;
            if (count === 0 && selectedType !== type.id) return null;
            
            return (
              <button
                key={type.id}
                onClick={() => setSelectedType(type.id)}
                className={`px-4 py-2 rounded-full text-sm font-medium whitespace-nowrap transition-colors flex items-center gap-2 ${
                  selectedType === type.id 
                    ? type.color.split(' ')[0] + ' ' + type.color.split(' ')[2] + ' border border-transparent ring-1 ring-black/5' 
                    : 'bg-white border border-neutral-200 text-neutral-600 hover:bg-neutral-50'
                }`}
              >
                {type.label}
                <span className="bg-white/50 px-1.5 py-0.5 rounded text-xs ml-1">{count}</span>
              </button>
            )
          })}
        </div>

        <div className="mt-4">
          <div className="flex flex-col md:flex-row gap-3 items-stretch">
            <div className="relative flex-1">
              <Input
                type="text"
                placeholder="Search knowledge..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="pl-10 h-10 bg-white focus:bg-white"
              />
              <Search className="w-4 h-4 text-neutral-400 absolute left-3.5 top-3" />
            </div>
            <div className="flex gap-2">
              <Button
                type="button"
                variant="outline"
                className="h-10 px-3 flex items-center justify-center gap-2"
                onClick={() => setFiltersOpen(v => !v)}
              >
                <SlidersHorizontal className="w-4 h-4" />
                Filters
                <ChevronDown className={`w-4 h-4 transition-transform ${filtersOpen ? 'rotate-180' : ''}`} />
              </Button>
              <Button
                type="button"
                variant="ghost"
                className="h-10 px-3 text-sm text-neutral-600 hover:text-neutral-900 disabled:opacity-50 disabled:pointer-events-none"
                disabled={!canClearAll}
                onClick={clearAllFilters}
              >
                Clear all
              </Button>
            </div>
          </div>

          {filtersOpen && (
            <div className="mt-3 flex flex-wrap gap-3 items-center">
              <div className="min-w-[220px] flex-1">
                <Input
                  type="text"
                  placeholder="Filter by source file..."
                  value={sourceFilter}
                  onChange={(e) => setSourceFilter(e.target.value)}
                  className="h-10 bg-white"
                />
              </div>
              <div className="min-w-[180px] flex-1">
                <Input
                  type="text"
                  placeholder="Filter by tag..."
                  value={tagFilter}
                  onChange={(e) => setTagFilter(e.target.value)}
                  className="h-10 bg-white"
                />
              </div>
              <div className="min-w-[170px]">
                <Input
                  type="date"
                  value={dateFrom}
                  onChange={(e) => setDateFrom(e.target.value)}
                  className="h-10 bg-white"
                />
              </div>
              <div className="min-w-[170px]">
                <Input
                  type="date"
                  value={dateTo}
                  onChange={(e) => setDateTo(e.target.value)}
                  className="h-10 bg-white"
                />
              </div>
              <div className="min-w-[190px]">
                <select
                  value={sortBy}
                  onChange={(e) => setSortBy(e.target.value as any)}
                  className="w-full h-10 bg-white border border-neutral-200 rounded-lg px-3 text-sm text-neutral-700"
                >
                  <option value="newest">Newest</option>
                  <option value="oldest">Oldest</option>
                  <option value="relevance">Relevance</option>
                </select>
              </div>
            </div>
          )}
        </div>
      </header>

      <div className="flex-1 overflow-y-auto p-8">
        <div className="max-w-[1200px] mx-auto space-y-10">
          {displayDocs.length === 0 ? (
            <div className="text-center py-20">
              <div className="w-16 h-16 bg-neutral-100 rounded-full flex items-center justify-center mx-auto mb-4">
                <FileText className="w-8 h-8 text-neutral-400" />
              </div>
              <h3 className="text-lg font-semibold text-neutral-900">No documents found</h3>
              <p className="text-neutral-500 mt-1">Try adjusting your search or filters.</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {displayDocs.map(doc => {
                const typeId = getTypeId(doc);
                const tags = getDocTags(doc);
                return (
                <div 
                  key={doc.id} 
                  onClick={() => setSelectedDoc(doc)}
                  className="bg-white border border-neutral-200 rounded-2xl p-6 hover:shadow-lg transition-all group flex flex-col h-[320px] cursor-pointer relative"
                >
                  {/* Topic Badge & Actions */}
                  <div className="flex justify-between items-start mb-4">
                    <span className={`text-[11px] px-3 py-1 rounded-full font-medium ${
                      typeId === 'skills_tech' ? 'bg-blue-50 text-blue-600 border border-blue-100' :
                      typeId === 'case_study' ? 'bg-emerald-50 text-emerald-600 border border-emerald-100' :
                      typeId === 'presales' ? 'bg-purple-50 text-purple-600 border border-purple-100' :
                      'bg-slate-50 text-slate-600 border border-slate-100'
                    }`}>
                      {typeId === 'skills_tech' ? 'Tech Capability' :
                       typeId === 'case_study' ? 'Case Study' :
                       typeId === 'presales' ? 'Workflow' : 'General'}
                    </span>
                    
                    {userRole === 'SuperManager' && (
                      <div className="opacity-0 group-hover:opacity-100 transition-opacity">
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild onClick={(e) => e.stopPropagation()}>
                            <Button variant="ghost" size="icon" className="h-6 w-6 text-neutral-400 hover:text-neutral-900 -mr-2 -mt-1">
                              <MoreVertical className="w-4 h-4" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end" className="w-32">
                            <DropdownMenuItem onClick={(e) => handleEditClick(doc, e as any)}>
                              <Edit2 className="w-3.5 h-3.5 mr-2" /> Edit
                            </DropdownMenuItem>
                            <DropdownMenuItem 
                              className="text-red-600 focus:text-red-600"
                              onClick={(e) => handleDeleteClick(doc.id, e as any)}
                            >
                              <Trash2 className="w-3.5 h-3.5 mr-2" /> Delete
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                    )}
                  </div>

                  {/* Title */}
                  <h3 className="text-[17px] font-bold text-neutral-900 line-clamp-2 leading-snug mb-3">
                    {doc.title}
                  </h3>
                  
                  {/* Content preview */}
                <p className="text-[13px] text-neutral-500 line-clamp-3 mb-4 flex-1">
                  {(() => {
                    const content = doc.content;
                    const match = content.match(/#\w+\s*$/m) || content.match(/#\w+(?!.*#\w+)/s);
                    if (match) {
                      const lastTagIndex = content.lastIndexOf(match[0]) + match[0].length;
                      const textResult = content.substring(lastTagIndex).trim();
                      
                      return <span className="font-semibold text-neutral-700">{textResult}</span>;
                    }
                    return content.replace(/\*\*/g, '');
                  })()}
                </p>

                  {/* Tags */}
                  <div className="flex flex-wrap gap-2 mb-6">
                    {tags.slice(0, 3).map((tag, i) => (
                      <span key={i} className="text-[11px] bg-neutral-100 text-neutral-600 px-2 py-1 rounded-md">
                        {tag}
                      </span>
                    ))}
                    {tags.length > 3 && (
                      <span className="text-[11px] bg-neutral-50 text-neutral-500 px-2 py-1 rounded-md border border-neutral-100">
                        +{tags.length - 3} more
                      </span>
                    )}
                  </div>

                  {/* Footer - Date */}
                  <div className="pt-4 border-t border-neutral-100 flex items-center text-neutral-400 text-xs mt-auto">
                    <Calendar className="w-3.5 h-3.5 mr-1.5" />
                    {formatDate(doc.createdAt)}
                  </div>
                </div>
              )})}
            </div>
          )}
        </div>
      </div>

      {/* Detail Modal */}
      {selectedDoc && !isEditing && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={() => setSelectedDoc(null)}>
          <div 
            className="bg-white rounded-2xl w-full max-w-3xl max-h-[90vh] flex flex-col shadow-2xl overflow-hidden"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-center justify-between p-6 border-b border-neutral-100">
              <span className={`text-[11px] px-3 py-1 rounded-full font-medium ${
                selectedDoc.topic === 'skills_tech' ? 'bg-blue-50 text-blue-600 border border-blue-100' :
                selectedDoc.topic === 'case_study' ? 'bg-emerald-50 text-emerald-600 border border-emerald-100' :
                selectedDoc.topic === 'presales' ? 'bg-purple-50 text-purple-600 border border-purple-100' :
                'bg-slate-50 text-slate-600 border border-slate-100'
              }`}>
                {selectedDoc.topic || 'General'}
              </span>
              <div className="flex items-center gap-2">
                {userRole === 'SuperManager' && (
                  <>
                    <Button variant="ghost" size="icon" onClick={(e) => handleEditClick(selectedDoc, e)}>
                      <Edit2 className="w-4 h-4 text-neutral-500" />
                    </Button>
                    <Button variant="ghost" size="icon" onClick={(e) => handleDeleteClick(selectedDoc.id, e)} className="hover:text-red-600 hover:bg-red-50">
                      <Trash2 className="w-4 h-4" />
                    </Button>
                  </>
                )}
                <div className="w-px h-6 bg-neutral-200 mx-2"></div>
                <Button variant="ghost" size="icon" onClick={() => setSelectedDoc(null)}>
                  <X className="w-5 h-5 text-neutral-500" />
                </Button>
              </div>
            </div>
            
            <div className="p-8 overflow-y-auto flex-1">
              <h2 className="text-2xl font-bold text-neutral-900 mb-4">{selectedDoc.title}</h2>
              <div className="flex flex-wrap gap-2 mb-8">
                {getDocTags(selectedDoc).map((tag, i) => (
                  <span key={i} className="text-[12px] bg-neutral-100 text-neutral-600 px-2 py-1 rounded-md">
                    {tag}
                  </span>
                ))}
              </div>
              
              <div className="prose prose-sm md:prose-base max-w-none text-neutral-600 whitespace-pre-wrap">
                {(() => {
                  const content = selectedDoc.content;
                  const match = content.match(/#\w+\s*$/m) || content.match(/#\w+(?!.*#\w+)/s);

                  if (match) {
                    // Lấy vị trí kết thúc của hashtag cuối cùng
                    const lastTagIndex = content.lastIndexOf(match[0]) + match[0].length;
                    
                    // Cắt chuỗi từ sau hashtag đó và xóa khoảng trắng thừa ở 2 đầu
                    const textResult = content.substring(lastTagIndex).trim();

                    return (
                      <>
                        <div>
                          {textResult}
                        </div>
                      </>
                    );
                  }
                })()}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Edit Modal */}
      {isEditing && selectedDoc && (
        <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl w-full max-w-3xl flex flex-col shadow-2xl overflow-hidden">
            <div className="p-6 border-b border-neutral-100 flex justify-between items-center bg-neutral-50">
              <h2 className="text-lg font-bold text-neutral-900 flex items-center gap-2">
                <Edit2 className="w-5 h-5 text-indigo-600" /> Edit Document
              </h2>
              <Button variant="ghost" size="icon" onClick={() => setIsEditing(false)}>
                <X className="w-5 h-5 text-neutral-500" />
              </Button>
            </div>
            <div className="p-6 space-y-4">
              <div>
                <label className="block text-sm font-medium text-neutral-700 mb-1">Title</label>
                <Input 
                  value={editForm.title} 
                  onChange={e => setEditForm({...editForm, title: e.target.value})}
                  className="font-medium"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-neutral-700 mb-1">Content</label>
                <textarea 
                  value={editForm.content}
                  onChange={e => setEditForm({...editForm, content: e.target.value})}
                  className="w-full h-64 p-3 border border-neutral-200 rounded-lg focus:ring-2 focus:ring-indigo-500 outline-none resize-none font-sans text-sm"
                />
              </div>
            </div>
            <div className="p-4 border-t border-neutral-100 flex justify-end gap-3 bg-neutral-50">
              <Button variant="ghost" onClick={() => setIsEditing(false)}>Cancel</Button>
              <Button onClick={handleSaveEdit} className="bg-indigo-600 hover:bg-indigo-700 text-white">Save Changes</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
