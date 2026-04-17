import { useMemo, useState, useEffect } from 'react';
import { ThumbsDown, ThumbsUp, Flag } from 'lucide-react';
import { Message } from '../types';
import { apiUrl } from '../lib/api';
import { Button } from './ui/button';
import { Dialog, DialogContent } from './ui/dialog';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "./ui/dropdown-menu";

type ReportKind = 'citation_not_relevant' | 'hallucination_report';

function safeUserId() {
  try {
    const raw = localStorage.getItem('rag_user');
    if (!raw) return null;
    const u = JSON.parse(raw);
    return u?.id ? String(u.id) : null;
  } catch {
    return null;
  }
}

export function FeedbackBar({ message }: { message: Message }) {
  const userId = useMemo(() => safeUserId(), []);
  const [sending, setSending] = useState(false);
  const [thumb, setThumb] = useState<1 | -1 | 0>(message.thumb || 0);

  useEffect(() => {
    setThumb(message.thumb || 0);
  }, [message.thumb]);

  const [reportOpen, setReportOpen] = useState(false);
  const [reportKind, setReportKind] = useState<ReportKind>('citation_not_relevant');
  const [note, setNote] = useState('');
  const [selectedCitationIds, setSelectedCitationIds] = useState<Record<string, boolean>>({});

  const sessionId = message?.sessionId ? String(message.sessionId) : '';
  const messageId = message?.persistedId ? String(message.persistedId) : (message?.id ? String(message.id) : '');
  const canSend = Boolean(userId && sessionId && messageId);

  const citations = Array.isArray(message.citations) ? message.citations : [];
  const cacheId = (message as any)?.cacheId ? String((message as any).cacheId) : '';

  const postFeedback = async (payload: any) => {
    if (!canSend) return false;
    setSending(true);
    try {
      const res = await fetch(apiUrl('/feedback'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json().catch(() => null);
      return Boolean(res.ok && data?.success);
    } finally {
      setSending(false);
    }
  };

  const sendThumb = async (v: 1 | -1) => {
    if (!canSend || sending) return;
    const citationsPayload = citations.slice(0, 20).map((c) => ({
      id: String((c as any)?.id || ''),
      title: String((c as any)?.title || ''),
      source: String((c as any)?.source || ''),
      category: String((c as any)?.category || ''),
      role: String((c as any)?.role || '')
    }));
    const ok = await postFeedback({
      userId,
      sessionId,
      messageId,
      kind: 'thumbs',
      value: v,
      citations: citationsPayload,
      metadata: { hasCitations: citations.length > 0, cachedAnswerId: cacheId || null }
    });
    if (ok) setThumb(v);
  };

  const submitReport = async () => {
    if (!canSend || sending) return;
    const picked = Object.entries(selectedCitationIds).filter(([, v]) => v).map(([k]) => k);
    const citationsPayload = reportKind === 'citation_not_relevant'
      ? citations.filter(c => picked.includes(String((c as any)?.id || ''))).map(c => ({
          id: String((c as any)?.id || ''),
          title: String((c as any)?.title || ''),
          source: String((c as any)?.source || ''),
          category: String((c as any)?.category || ''),
          role: String((c as any)?.role || '')
        }))
      : undefined;

    const ok = await postFeedback({
      userId,
      sessionId,
      messageId,
      kind: reportKind,
      note: note.trim() || null,
      citations: citationsPayload,
      metadata: {
        citationsCount: citations.length,
        selectedCitationsCount: picked.length,
        cachedAnswerId: cacheId || null
      }
    });
    if (ok) {
      setReportOpen(false);
      setNote('');
      setSelectedCitationIds({});
    }
  };

  if (message.role !== 'agent') return null;
  if (!message.content) return null;

  const isNoData = (content: string) => {
    const t = (content || '').toLowerCase();
    return (
      t.includes("kiến thức liên quan tới chủ đề này sẽ được bổ sung") ||
      t.includes("kien thuc lien quan toi chu de nay se duoc bo sung") ||
      t.includes("relevant knowledge for this topic will be added shortly") ||
      t.includes("không có dữ liệu nội bộ") ||
      t.includes("no internal data")
    );
  };

  if (isNoData(message.content)) return null;

  return (
    <div className="mt-2 flex items-center gap-2">
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="h-7 px-2 text-xs"
        disabled={!canSend || sending || thumb === 1}
        onClick={() => sendThumb(1)}
      >
        <ThumbsUp className="w-3.5 h-3.5 mr-1" />
        Helpful
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="h-7 px-2 text-xs"
        disabled={!canSend || sending || thumb === -1}
        onClick={() => sendThumb(-1)}
      >
        <ThumbsDown className="w-3.5 h-3.5 mr-1" />
        Not helpful
      </Button>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-xs"
            disabled={!canSend || sending}
          >
            <Flag className="w-3.5 h-3.5 mr-1" />
            Report
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-56">
          <DropdownMenuItem
            onClick={(e) => {
              e.stopPropagation();
              setReportKind('citation_not_relevant');
              setReportOpen(true);
            }}
          >
            Citation not relevant
          </DropdownMenuItem>
          <DropdownMenuItem
            onClick={(e) => {
              e.stopPropagation();
              setReportKind('hallucination_report');
              setReportOpen(true);
            }}
          >
            Hallucination report
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <Dialog open={reportOpen} onOpenChange={setReportOpen}>
        <DialogContent className="bg-white rounded-2xl w-full max-w-2xl h-[75vh] flex flex-col shadow-2xl overflow-hidden p-0">
          <div className="p-4 border-b border-neutral-100 bg-neutral-50 shrink-0">
            <div className="text-lg font-semibold text-neutral-900">
              {reportKind === 'citation_not_relevant' ? 'Citation not relevant' : 'Hallucination report'}
            </div>
            <div className="mt-1 text-xs text-neutral-500">
              Feedback được lưu để tuning retrieval/synthesis.
            </div>
          </div>

          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {reportKind === 'citation_not_relevant' ? (
              <div className="space-y-2">
                <div className="text-sm font-semibold text-neutral-900">Chọn citations không liên quan</div>
                {citations.length === 0 ? (
                  <div className="text-sm text-neutral-500">Không có citations cho message này.</div>
                ) : (
                  <div className="space-y-2">
                    {citations.slice(0, 20).map((c, idx) => {
                      const cid = String((c as any)?.id || idx);
                      const checked = Boolean(selectedCitationIds[cid]);
                      const title = String((c as any)?.title || 'Citation');
                      const source = String((c as any)?.source || '');
                      return (
                        <label key={cid} className="flex items-start gap-3 rounded-lg border border-neutral-200 bg-white p-3">
                          <input
                            type="checkbox"
                            className="mt-1"
                            checked={checked}
                            onChange={(e) => setSelectedCitationIds(prev => ({ ...prev, [cid]: e.target.checked }))}
                          />
                          <div className="min-w-0">
                            <div className="text-sm font-semibold text-neutral-900 truncate">{title}</div>
                            {source ? <div className="text-xs text-neutral-500 truncate">{source}</div> : null}
                          </div>
                        </label>
                      );
                    })}
                  </div>
                )}
              </div>
            ) : null}

            <div className="space-y-2">
              <div className="text-sm font-semibold text-neutral-900">Ghi chú (tuỳ chọn)</div>
              <textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder={reportKind === 'hallucination_report'
                  ? 'Mô tả phần bị bịa/sai và nếu có, câu trả lời đúng mong muốn...'
                  : 'Vì sao citations này không liên quan?'}
                className="w-full h-28 rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-indigo-200"
              />
            </div>
          </div>

          <div className="p-4 border-t border-neutral-100 bg-white shrink-0 flex items-center justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-9"
              onClick={() => setReportOpen(false)}
              disabled={sending}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="default"
              size="sm"
              className="h-9"
              onClick={submitReport}
              disabled={!canSend || sending}
            >
              Submit
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
