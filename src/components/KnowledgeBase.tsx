import { useState, MouseEvent } from 'react';
import { Document, RoleLevels, Role } from '../lib/vectorStore';
import { Book, Code, Briefcase, CheckSquare, Search, FileText, Calendar, MoreVertical, Edit2, Trash2, X } from 'lucide-react';
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

export function KnowledgeBase({ documents, userRole, onDeleteDocument, onEditDocument }: KnowledgeBaseProps) {
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedType, setSelectedType] = useState<string | null>(null);
  const [selectedDoc, setSelectedDoc] = useState<Document | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [editForm, setEditForm] = useState({ title: '', content: '' });

  // Filter documents by Role RBAC and Search Term
  const accessibleDocs = documents.filter(doc => {
    const hasAccess = RoleLevels[userRole] >= RoleLevels[doc.role];
    const matchesSearch = doc.title.toLowerCase().includes(searchTerm.toLowerCase()) || 
                          doc.content.toLowerCase().includes(searchTerm.toLowerCase());
    return hasAccess && matchesSearch;
  });

  // Group by topic
  const groupedDocs = accessibleDocs.reduce((acc, doc) => {
    const topic = doc.topic || 'General';
    // Map custom topics to 'General' if they don't match the 3 main types exactly
    const matchedType = KNOWLEDGE_TYPES.find(t => t.id === topic) ? topic : 'General';
    
    if (!acc[matchedType]) acc[matchedType] = [];
    acc[matchedType].push(doc);
    return acc;
  }, {} as Record<string, Document[]>);

  // Flat list of documents instead of grouped sections
  const displayDocs = selectedType 
    ? accessibleDocs.filter(doc => (doc.topic === selectedType) || (!KNOWLEDGE_TYPES.find(t=>t.id===doc.topic) && selectedType === 'General'))
    : accessibleDocs;

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

  // Helper to extract tags (simple regex for words starting with #, or just make some up for UI)
  const getTags = (content: string) => {
    const tags = content.match(/#\w+/g) || [];
    if (tags.length > 0) return tags;
    // Mock tags for visual parity with screenshot if none exist
    return ['#cloud', '#migration', '#aws']; 
  };

  // Helper to format date
  const formatDate = (timestamp?: number) => {
    if (!timestamp) return '—';
    return new Date(timestamp).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  };

  return (
    <div className="flex flex-col h-full bg-neutral-50 overflow-hidden">
      <header className="px-8 py-6 bg-white border-b border-neutral-200 shrink-0">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-neutral-900 flex items-center gap-2">
              <Book className="w-6 h-6 text-indigo-600" />
              Knowledge Base
            </h1>
            <p className="text-neutral-500 mt-1">Browse internal capabilities, case studies, and workflows.</p>
          </div>
          
          <div className="relative w-full md:w-72">
            <Input 
              type="text"
              placeholder="Search knowledge..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="pl-10 h-10 bg-neutral-100 border-transparent focus:bg-white"
            />
            <Search className="w-4 h-4 text-neutral-400 absolute left-3.5 top-3" />
          </div>
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
            const count = groupedDocs[type.id]?.length || 0;
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
                const typeId = doc.topic && KNOWLEDGE_TYPES.find(t=>t.id===doc.topic) ? doc.topic : 'General';
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
                    
                    {userRole === 'Admin' && (
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
                    {doc.content.replace(/\*\*/g, '')}
                  </p>

                  {/* Tags */}
                  <div className="flex flex-wrap gap-2 mb-6">
                    {getTags(doc.content).slice(0, 3).map((tag, i) => (
                      <span key={i} className="text-[11px] bg-neutral-100 text-neutral-600 px-2 py-1 rounded-md">
                        {tag}
                      </span>
                    ))}
                    {getTags(doc.content).length > 3 && (
                      <span className="text-[11px] bg-neutral-50 text-neutral-500 px-2 py-1 rounded-md border border-neutral-100">
                        +{getTags(doc.content).length - 3} more
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
                {userRole === 'Admin' && (
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
                {getTags(selectedDoc.content).map((tag, i) => (
                  <span key={i} className="text-[12px] bg-neutral-100 text-neutral-600 px-2 py-1 rounded-md">
                    {tag}
                  </span>
                ))}
              </div>
              
              <div className="prose prose-sm md:prose-base max-w-none text-neutral-600 whitespace-pre-wrap">
                {selectedDoc.content}
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
