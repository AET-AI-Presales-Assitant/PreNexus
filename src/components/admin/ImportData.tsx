import React, { useState } from 'react';
import { Upload, FileText, CheckCircle, AlertCircle, Loader2, Clock, Check, X } from 'lucide-react';
import { Button } from '../ui/button';
import { Role } from '../../lib/vectorStore';
import { apiUrl } from '../../lib/api';

interface ImportDataProps {
  onImport: (title: string, content: string, role: Role, topic?: string) => Promise<void>;
}

interface UploadProgress {
  file: File;
  progress: number;
  status: 'uploading' | 'processing' | 'success' | 'error' | 'rolled_back';
  message?: string;
  jobId?: string;
  numChunksTotal?: number;
  numChunksSuccess?: number;
  numSummaryDocs?: number;
  numChunkDocs?: number;
  numEmbeddings?: number;
  embeddingModel?: string;
  errors?: string[];
}

export function ImportData({ onImport }: ImportDataProps) {
  const [activeTab, setActiveTab] = useState<'upload' | 'progress'>('upload');
  const [role, setRole] = useState<Role>('Employee');
  const [dragActive, setDragActive] = useState(false);
  const [uploadTasks, setUploadTasks] = useState<UploadProgress[]>([]);

  const refreshJob = async (jobId: string) => {
    const response = await fetch(apiUrl(`/admin/ingest_jobs/${jobId}`));
    const data = await response.json();
    if (!data.success) throw new Error(data?.error ? `${data.message || 'Failed to fetch job'}: ${data.error}` : (data.message || 'Failed to fetch job'));
    return data.job;
  };

  const startPolling = (fileName: string, jobId: string) => {
    const interval = setInterval(async () => {
      try {
        const job = await refreshJob(jobId);
        const st = String(job.status || 'processing');
        const nextStatus: UploadProgress['status'] =
          st === 'success' ? 'success' :
          st === 'error' ? 'error' :
          st === 'rolled_back' ? 'rolled_back' :
          'processing';

        setUploadTasks(prev => prev.map(t => {
          if (t.file.name !== fileName) return t;
          return {
            ...t,
            status: nextStatus,
            progress: nextStatus === 'success' || nextStatus === 'error' || nextStatus === 'rolled_back'
              ? 100
              : Math.max(t.progress, 35),
            message: nextStatus === 'success'
              ? 'Imported successfully'
              : nextStatus === 'error'
                ? (job.error || 'Failed to process file')
                : nextStatus === 'rolled_back'
                  ? 'Rolled back'
                  : 'Processing',
            numChunksTotal: job.numChunksTotal ?? t.numChunksTotal,
            numChunksSuccess: job.numChunksSuccess ?? t.numChunksSuccess,
            numSummaryDocs: job.numSummaryDocs ?? t.numSummaryDocs,
            numChunkDocs: job.numChunkDocs ?? t.numChunkDocs,
            numEmbeddings: job.numEmbeddings ?? t.numEmbeddings,
            embeddingModel: job.embeddingModel ?? t.embeddingModel,
            errors: Array.isArray(job.errors) ? job.errors : t.errors
          };
        }));

        if (st === 'success') {
          clearInterval(interval);
          await onImport(fileName, "File imported", role, 'General');
        }
        if (st === 'error' || st === 'rolled_back') {
          clearInterval(interval);
        }
      } catch (e: any) {
        setUploadTasks(prev => prev.map(t =>
          t.file.name === fileName ? { ...t, status: 'error', progress: 100, message: e?.message || 'Failed to poll job' } : t
        ));
        clearInterval(interval);
      }
    }, 1200);
  };

  const retryTask = async (task: UploadProgress) => {
    if (!task.jobId) return;
    const response = await fetch(apiUrl(`/admin/ingest_jobs/${task.jobId}/retry`), { method: 'POST' });
    const data = await response.json();
    if (!data.success) throw new Error(data?.error ? `${data.message || 'Retry failed'}: ${data.error}` : (data.message || 'Retry failed'));
    const job = data.job;
    setUploadTasks(prev => prev.map(t => t.file.name === task.file.name ? {
      ...t,
      status: 'processing',
      progress: 35,
      message: 'Processing',
      jobId: job?.id,
      errors: []
    } : t));
    if (job?.id) startPolling(task.file.name, job.id);
  };

  const rollbackTask = async (task: UploadProgress) => {
    if (!task.jobId) return;
    const response = await fetch(apiUrl(`/admin/ingest_jobs/${task.jobId}/rollback`), { method: 'POST' });
    const data = await response.json();
    if (!data.success) throw new Error(data.message || 'Rollback failed');
    setUploadTasks(prev => prev.map(t => t.file.name === task.file.name ? {
      ...t,
      status: 'rolled_back',
      progress: 100,
      message: 'Rolled back'
    } : t));
    await onImport(task.file.name, "Rolled back", role, 'General');
  };

  const processFile = async (file: File) => {
    // Chuyển sang tab progress ngay lập tức
    setActiveTab('progress');
    
    const newTask: UploadProgress = { file, progress: 10, status: 'uploading' };
    setUploadTasks(prev => [newTask, ...prev]);

    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('role', role);

      const response = await fetch(apiUrl('/admin/import'), {
        method: 'POST',
        body: formData,
      });

      const data = await response.json();

      if (data.success) {
        const job = data.job;
        setUploadTasks(prev => prev.map(task =>
          task.file.name === file.name
            ? { ...task, progress: 35, status: 'processing', message: 'Processing', jobId: job?.id }
            : task
        ));
        if (job?.id) startPolling(file.name, job.id);
      } else {
        const errMsg = data?.error ? `${data.message || 'Failed to process file'}: ${data.error}` : (data.message || 'Failed to process file');
        setUploadTasks(prev => prev.map(task => 
          task.file.name === file.name 
            ? { ...task, progress: 100, status: 'error', message: errMsg }
            : task
        ));
      }
    } catch (error) {
      console.error(error);
      setUploadTasks(prev => prev.map(task => 
        task.file.name === file.name 
          ? { ...task, progress: 100, status: 'error', message: 'Network error or server unreachable' }
          : task
      ));
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      processFile(e.target.files[0]);
    }
  };

  const handleUpload = async (file: File) => {
     await processFile(file);
  };

  return (
    <div className="flex flex-col h-full bg-white">
      <div className="p-6 border-b border-neutral-100 flex justify-between items-center">
        <div>
          <h2 className="text-xl font-bold text-neutral-900">Import Data</h2>
          <p className="text-sm text-neutral-500 mt-1">Upload documents to the Knowledge Base</p>
        </div>
        
        {/* Tabs */}
        <div className="flex bg-neutral-100 p-1 rounded-lg">
          <button
            onClick={() => setActiveTab('upload')}
            className={`px-4 py-2 text-sm font-medium rounded-md transition-colors ${
              activeTab === 'upload' 
                ? 'bg-white text-indigo-600 shadow-sm' 
                : 'text-neutral-500 hover:text-neutral-700'
            }`}
          >
            Upload
          </button>
          <button
            onClick={() => setActiveTab('progress')}
            className={`px-4 py-2 text-sm font-medium rounded-md transition-colors flex items-center gap-2 ${
              activeTab === 'progress' 
                ? 'bg-white text-indigo-600 shadow-sm' 
                : 'text-neutral-500 hover:text-neutral-700'
            }`}
          >
            Progress
            {uploadTasks.filter(t => t.status === 'uploading' || t.status === 'processing').length > 0 && (
              <span className="flex h-2 w-2 relative">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-indigo-500"></span>
              </span>
            )}
          </button>
        </div>
      </div>
      
      <div className="flex-1 overflow-auto p-6">
        {activeTab === 'upload' ? (
          <div className="grid gap-8">
              {/* Upload Section */}
              <div className="space-y-6">
                  <div 
                      className={`border-2 border-dashed rounded-xl p-10 flex flex-col items-center justify-center text-center transition-colors ${dragActive ? 'border-indigo-500 bg-indigo-50' : 'border-neutral-200 hover:border-indigo-400 hover:bg-neutral-50'}`}
                      onDragEnter={() => setDragActive(true)}
                      onDragLeave={() => setDragActive(false)}
                      onDragOver={(e) => e.preventDefault()}
                      onDrop={(e) => {
                          e.preventDefault();
                          setDragActive(false);
                          if (e.dataTransfer.files && e.dataTransfer.files[0]) {
                              handleUpload(e.dataTransfer.files[0]);
                          }
                      }}
                  >
                      <div className="w-16 h-16 bg-indigo-100 text-indigo-600 rounded-full flex items-center justify-center mb-4">
                          <Upload className="w-8 h-8" />
                      </div>
                      <h3 className="text-lg font-semibold text-neutral-900 mb-2">Upload Document</h3>
                      <p className="text-neutral-500 mb-6 max-w-sm">
                          Drag and drop your file here, or click to browse.
                          <br />
                          <span className="text-xs">Supports PDF, TXT, MD, JSON, Images</span>
                      </p>
                      
                      <input 
                          type="file" 
                          id="file-upload" 
                          className="hidden" 
                          onChange={handleFileChange}
                          accept=".pdf,.txt,.md,.json,.jpg,.jpeg,.png"
                      />
                      <label 
                          htmlFor="file-upload"
                          className="cursor-pointer bg-indigo-600 hover:bg-indigo-700 text-white px-6 py-2.5 rounded-lg font-medium transition-colors shadow-sm shadow-indigo-200"
                      >
                          Browse Files
                      </label>
                  </div>

                  <div className="bg-neutral-50 rounded-xl p-6 border border-neutral-200">
                      <h4 className="font-semibold text-neutral-900 mb-4 flex items-center gap-2">
                          <FileText className="w-4 h-4" /> Access Control
                      </h4>
                      <div className="flex gap-4 flex-wrap">
                          {(['Employee', 'Lead', 'Manager', 'SuperManager'] as Role[]).map((r) => (
                              <label key={r} className="flex items-center gap-2 cursor-pointer bg-white px-4 py-2 rounded-lg border border-neutral-200 shadow-sm hover:border-indigo-300 transition-all">
                                  <input
                                      type="radio"
                                      name="role"
                                      value={r}
                                      checked={role === r}
                                      onChange={(e) => setRole(e.target.value as Role)}
                                      className="text-indigo-600 focus:ring-indigo-500"
                                  />
                                  <span className="text-sm font-medium text-neutral-700">{r === 'SuperManager' ? 'Super Manager' : r}</span>
                              </label>
                          ))}
                      </div>
                      <p className="text-xs text-neutral-500 mt-3">
                          Select who can access this document. The AI will also suggest a role based on content.
                      </p>
                  </div>
              </div>
          </div>
        ) : (
          <div className="max-w-3xl mx-auto space-y-4">
            {uploadTasks.length === 0 ? (
              <div className="text-center py-20 bg-neutral-50 rounded-xl border border-neutral-200 border-dashed">
                <Clock className="w-12 h-12 text-neutral-300 mx-auto mb-4" />
                <h3 className="text-lg font-medium text-neutral-900">No recent uploads</h3>
                <p className="text-neutral-500 mt-1">Upload a file to see its progress here.</p>
                <Button 
                  variant="outline" 
                  className="mt-6"
                  onClick={() => setActiveTab('upload')}
                >
                  Go to Upload
                </Button>
              </div>
            ) : (
              uploadTasks.map((task, i) => (
                <div key={i} className="bg-white border border-neutral-200 rounded-xl p-5 shadow-sm">
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-3">
                      <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
                        task.status === 'success' ? 'bg-green-100 text-green-600' :
                        task.status === 'error' ? 'bg-red-100 text-red-600' :
                        task.status === 'rolled_back' ? 'bg-neutral-100 text-neutral-600' :
                        'bg-indigo-100 text-indigo-600'
                      }`}>
                        {task.status === 'success' ? <Check className="w-5 h-5" /> :
                         task.status === 'error' ? <X className="w-5 h-5" /> :
                         task.status === 'rolled_back' ? <X className="w-5 h-5" /> :
                         <FileText className="w-5 h-5" />}
                      </div>
                      <div>
                        <h4 className="font-medium text-neutral-900 truncate max-w-md" title={task.file.name}>
                          {task.file.name}
                        </h4>
                        <p className="text-xs text-neutral-500 flex items-center gap-2 mt-0.5">
                          <span>{(task.file.size / 1024 / 1024).toFixed(2)} MB</span>
                          <span className="w-1 h-1 bg-neutral-300 rounded-full"></span>
                          <span className="capitalize">{task.status}</span>
                          {task.embeddingModel && (
                            <>
                              <span className="w-1 h-1 bg-neutral-300 rounded-full"></span>
                              <span>{task.embeddingModel}</span>
                            </>
                          )}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      {task.status === 'error' && (
                        <Button variant="outline" size="sm" className="h-8" onClick={() => retryTask(task)}>
                          Retry
                        </Button>
                      )}
                      {task.status === 'success' && (
                        <Button variant="outline" size="sm" className="h-8" onClick={() => rollbackTask(task)}>
                          Rollback
                        </Button>
                      )}
                      <div className="text-right min-w-[76px]">
                        {task.status === 'uploading' || task.status === 'processing' ? (
                          <span className="text-sm font-bold text-indigo-600">{task.progress}%</span>
                        ) : task.status === 'success' ? (
                          <span className="text-sm font-medium text-green-600 flex items-center justify-end gap-1"><CheckCircle className="w-4 h-4"/> Done</span>
                        ) : task.status === 'rolled_back' ? (
                          <span className="text-sm font-medium text-neutral-600 flex items-center justify-end gap-1"><X className="w-4 h-4"/> Rolled back</span>
                        ) : (
                          <span className="text-sm font-medium text-red-600 flex items-center justify-end gap-1"><AlertCircle className="w-4 h-4"/> Failed</span>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Progress bar */}
                  <div className="w-full bg-neutral-100 rounded-full h-2 mt-4 overflow-hidden">
                    <div 
                      className={`h-2 rounded-full transition-all duration-300 ${
                        task.status === 'success' ? 'bg-green-500' :
                        task.status === 'error' ? 'bg-red-500' :
                        task.status === 'rolled_back' ? 'bg-neutral-400' :
                        'bg-indigo-600'
                      }`}
                      style={{ width: `${task.progress}%` }}
                    ></div>
                  </div>
                  
                  {/* Status Message */}
                  {task.message && (
                    <p className={`text-xs mt-3 ${
                      task.status === 'success' ? 'text-green-600' :
                      task.status === 'error' ? 'text-red-600' :
                      task.status === 'rolled_back' ? 'text-neutral-600' :
                      'text-indigo-600'
                    }`}>
                      {task.message}
                    </p>
                  )}
                  
                  {/* Processing animation */}
                  {(task.status === 'uploading' || task.status === 'processing') && (
                    <p className="text-xs text-indigo-600 mt-3 flex items-center gap-2">
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      Analyzing and chunking document with AI...
                    </p>
                  )}

                  {(typeof task.numChunksTotal === 'number' || typeof task.numEmbeddings === 'number' || (task.errors && task.errors.length > 0)) && (
                    <div className="mt-3 text-xs text-neutral-600 flex flex-wrap gap-x-4 gap-y-1">
                      {typeof task.numChunksTotal === 'number' ? <span>Chunks: {task.numChunksSuccess ?? 0}/{task.numChunksTotal}</span> : null}
                      {typeof task.numSummaryDocs === 'number' ? <span>Summaries: {task.numSummaryDocs}</span> : null}
                      {typeof task.numChunkDocs === 'number' ? <span>Chunk docs: {task.numChunkDocs}</span> : null}
                      {typeof task.numEmbeddings === 'number' ? <span>Embeddings: {task.numEmbeddings}</span> : null}
                      {task.errors && task.errors.length > 0 ? <span>Errors: {task.errors.length}</span> : null}
                    </div>
                  )}

                  {task.errors && task.errors.length > 0 && (
                    <div className="mt-2 text-xs text-neutral-600 bg-neutral-50 border border-neutral-200 rounded-lg p-3 whitespace-pre-wrap">
                      {task.errors.slice(0, 5).map((e, idx) => (
                        <div key={idx}>- {e}</div>
                      ))}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  );
}
