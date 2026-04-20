import React, { useMemo, useState } from 'react';
import { AnalyticsQuery } from '../../types';
import { BarChart, Sparkles, AlertCircle, BookOpen, Lightbulb, Users, ThumbsUp, ThumbsDown, MessageSquare, Clock } from 'lucide-react';
import { Button } from '../ui/button';

interface DataAnalyticsProps {
  analytics: AnalyticsQuery[];
  onAnalyzeGaps?: (queries: string[]) => Promise<string>;
}

interface AIInsight {
  topInterests: { topic: string, reason: string }[];
  knowledgeGaps: { question: string, suggestion: string }[];
}

export function DataAnalytics({ analytics, onAnalyzeGaps }: DataAnalyticsProps) {
  const [analysisResult, setAnalysisResult] = useState<AIInsight | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);

  const handleAnalyze = async () => {
    if (!onAnalyzeGaps) return;
    setIsAnalyzing(true);
    try {
      const uniqueQueries = Array.from(new Set(analytics.map(a => a.content)));
      const result = await onAnalyzeGaps(uniqueQueries);
      
      if (!result) {
        console.error("Analysis returned empty result");
        return;
      }
      
      try {
        // Có thể backend vẫn sót vài ký tự Markdown nên frontend cần "gọt" lần cuối trước khi parse
        let cleanResult = result.trim();
        if (cleanResult.startsWith("```")) {
          cleanResult = cleanResult.replace(/^```(?:json)?\s*/, '').replace(/\s*```$/, '');
        }
        
        // Thêm kiểm tra ngoặc nhọn {} để lấy nội dung JSON thật sự nếu có rác
        const startIdx = cleanResult.indexOf('{');
        const endIdx = cleanResult.lastIndexOf('}');
        if (startIdx !== -1 && endIdx !== -1 && endIdx > startIdx) {
          cleanResult = cleanResult.substring(startIdx, endIdx + 1);
        }

        setAnalysisResult(JSON.parse(cleanResult));
      } catch (parseError) {
        console.error("Failed to parse analysis result:", parseError);
        console.log("Raw result was:", result);
      }
    } catch (error) {
      console.error("Analysis failed", error);
    } finally {
      setIsAnalyzing(false);
    }
  };

  // Get Top 5 Frequent Questions
  const topQuestions = useMemo(() => {
    const counts: Record<string, number> = {};
    const normalizedMap: Record<string, string> = {};

    analytics.forEach(q => {
      // Group by answerContent if available (questions with same answer), otherwise fallback to question content
      // Normalize key: lowercase and trim
      const key = (q.answerContent || q.content).trim().toLowerCase();
      
      if (!counts[key]) {
          counts[key] = 0;
          // Keep the first question variation as the display text (or maybe we should display the answer?)
          // User request: "group questions that have the same answer"
          // If we group by answer, displaying the QUESTION might be misleading if they are different.
          // But typically "Top Questions" implies we list questions.
          // Let's display the Question Content of the first occurrence.
          normalizedMap[key] = q.content;
      }
      counts[key]++;
    });

    return Object.entries(counts)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5)
      .map(([key, count]) => ({
        content: normalizedMap[key],
        count
      }));
  }, [analytics]);

  // Calculate KPIs
  const kpis = useMemo(() => {
    const totalQueries = analytics.length;
    const uniqueUsers = new Set(analytics.map(q => q.userName)).size;
    
    let totalFeedback = 0;
    let positiveFeedback = 0;
    let negativeFeedback = 0;

    analytics.forEach(q => {
      if (q.feedbackValue !== undefined && q.feedbackValue !== null) {
        totalFeedback++;
        if (q.feedbackValue === 1) positiveFeedback++;
        if (q.feedbackValue === -1) negativeFeedback++;
      }
    });

    const positiveRate = totalFeedback > 0 ? Math.round((positiveFeedback / totalFeedback) * 100) : 0;

    return {
      totalQueries,
      uniqueUsers,
      totalFeedback,
      positiveRate,
      positiveFeedback,
      negativeFeedback
    };
  }, [analytics]);

  return (
    <div className="flex flex-col h-full bg-white overflow-hidden">
      <div className="p-6 border-b border-neutral-100">
        <h2 className="text-xl font-bold text-neutral-900">Dashboard & Analytics</h2>
        <p className="text-sm text-neutral-500 mt-1">System overview and usage statistics</p>
      </div>

      <div className="flex-1 overflow-auto p-6 space-y-8 bg-neutral-50/50">
        
        {/* KPI Cards */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className="bg-white p-5 rounded-xl border border-neutral-200 shadow-sm flex items-center gap-4">
            <div className="w-12 h-12 bg-indigo-50 rounded-lg flex items-center justify-center shrink-0">
              <MessageSquare className="w-6 h-6 text-indigo-600" />
            </div>
            <div>
              <p className="text-sm font-medium text-neutral-500">Total Queries</p>
              <h3 className="text-2xl font-bold text-neutral-900">{kpis.totalQueries}</h3>
            </div>
          </div>
          
          <div className="bg-white p-5 rounded-xl border border-neutral-200 shadow-sm flex items-center gap-4">
            <div className="w-12 h-12 bg-blue-50 rounded-lg flex items-center justify-center shrink-0">
              <Users className="w-6 h-6 text-blue-600" />
            </div>
            <div>
              <p className="text-sm font-medium text-neutral-500">Unique Users</p>
              <h3 className="text-2xl font-bold text-neutral-900">{kpis.uniqueUsers}</h3>
            </div>
          </div>

          <div className="bg-white p-5 rounded-xl border border-neutral-200 shadow-sm flex items-center gap-4">
            <div className="w-12 h-12 bg-emerald-50 rounded-lg flex items-center justify-center shrink-0">
              <ThumbsUp className="w-6 h-6 text-emerald-600" />
            </div>
            <div>
              <p className="text-sm font-medium text-neutral-500">Positive Feedback</p>
              <div className="flex items-baseline gap-2">
                <h3 className="text-2xl font-bold text-neutral-900">{kpis.positiveRate}%</h3>
                <span className="text-xs font-medium text-emerald-600">({kpis.positiveFeedback})</span>
              </div>
            </div>
          </div>

          <div className="bg-white p-5 rounded-xl border border-neutral-200 shadow-sm flex items-center gap-4">
            <div className="w-12 h-12 bg-rose-50 rounded-lg flex items-center justify-center shrink-0">
              <ThumbsDown className="w-6 h-6 text-rose-600" />
            </div>
            <div>
              <p className="text-sm font-medium text-neutral-500">Negative Feedback</p>
              <h3 className="text-2xl font-bold text-neutral-900">{kpis.negativeFeedback}</h3>
            </div>
          </div>
        </div>

        {/* Top 5 Questions Section */}
        <section>
          <div className="flex items-center justify-between mb-4">
             <h3 className="text-lg font-semibold text-neutral-800 flex items-center gap-2">
               <BarChart className="w-5 h-5 text-indigo-600" />
               Top 5 Most Asked Questions
             </h3>
             <div className="bg-indigo-50 px-3 py-1 rounded-full text-xs font-semibold text-indigo-700">
                Total Queries: {analytics.length}
             </div>
          </div>
          
          <div className="bg-white border border-neutral-200 rounded-xl overflow-hidden shadow-sm">
            <table className="w-full text-left">
              <thead className="bg-neutral-50">
                <tr className="text-xs font-semibold text-neutral-500 uppercase tracking-wider border-b border-neutral-200">
                  <th className="px-6 py-4">Question</th>
                  <th className="px-6 py-4 w-32 text-center">Frequency</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100">
                {topQuestions.map((q, idx) => (
                  <tr key={idx} className="text-sm hover:bg-neutral-50 transition-colors">
                    <td className="px-6 py-4 font-medium text-neutral-900 truncate max-w-2xl" title={q.content}>
                      {q.content}
                    </td>
                    <td className="px-6 py-4 text-center">
                      <span className="inline-flex items-center justify-center bg-neutral-100 text-neutral-700 font-bold px-3 py-1 rounded-full text-xs">
                        {q.count} times
                      </span>
                    </td>
                  </tr>
                ))}
                {topQuestions.length === 0 && (
                    <tr>
                        <td colSpan={2} className="px-6 py-10 text-center text-neutral-500">No questions have been asked yet.</td>
                    </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
        
        {/* Recent Queries Log */}
        <section>
          <div className="flex items-center justify-between mb-4">
             <h3 className="text-lg font-semibold text-neutral-800 flex items-center gap-2">
               <Clock className="w-5 h-5 text-indigo-600" />
               Recent User Queries
             </h3>
          </div>
          
          <div className="bg-white border border-neutral-200 rounded-xl overflow-hidden shadow-sm">
            <div className="overflow-x-auto">
              <table className="w-full text-left min-w-[800px]">
                <thead className="bg-neutral-50">
                  <tr className="text-xs font-semibold text-neutral-500 uppercase tracking-wider border-b border-neutral-200">
                    <th className="px-6 py-4 w-40">Time</th>
                    <th className="px-6 py-4 w-40">User</th>
                    <th className="px-6 py-4">Query & Answer</th>
                    <th className="px-6 py-4 w-24 text-center">Feedback</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-neutral-100">
                  {analytics.slice(0, 20).map((q, idx) => (
                    <tr key={idx} className="text-sm hover:bg-neutral-50 transition-colors">
                      <td className="px-6 py-4 text-neutral-500 whitespace-nowrap">
                        {new Date(q.createdAt).toLocaleString('vi-VN', {
                          month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
                        })}
                      </td>
                      <td className="px-6 py-4">
                        <div className="font-medium text-neutral-900">{q.userName}</div>
                        <div className="text-xs text-neutral-500">{q.userRole}</div>
                      </td>
                      <td className="px-6 py-4">
                        <div className="font-medium text-neutral-900 mb-1">{q.content}</div>
                        {q.answerContent && (
                          <div className="text-xs text-neutral-500 line-clamp-2">
                            <span className="font-semibold text-neutral-400">Agent: </span>
                            {q.answerContent}
                          </div>
                        )}
                      </td>
                      <td className="px-6 py-4 text-center">
                        {q.feedbackValue === 1 ? (
                          <div className="inline-flex items-center justify-center w-8 h-8 rounded-full bg-emerald-50 text-emerald-600" title={q.feedbackNote || 'Positive'}>
                            <ThumbsUp className="w-4 h-4" />
                          </div>
                        ) : q.feedbackValue === -1 ? (
                          <div className="inline-flex items-center justify-center w-8 h-8 rounded-full bg-rose-50 text-rose-600" title={q.feedbackNote || 'Negative'}>
                            <ThumbsDown className="w-4 h-4" />
                          </div>
                        ) : (
                          <span className="text-neutral-300">-</span>
                        )}
                      </td>
                    </tr>
                  ))}
                  {analytics.length === 0 && (
                      <tr>
                          <td colSpan={4} className="px-6 py-10 text-center text-neutral-500">No queries recorded yet.</td>
                      </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </section>

        {/* AI Analysis Section */}
        <section className="bg-gradient-to-br from-indigo-50 to-violet-50 rounded-xl p-6 border border-indigo-100">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold text-indigo-900 flex items-center gap-2">
              <Sparkles className="w-5 h-5 text-indigo-600" />
              AI Knowledge Insights
            </h3>
            <Button 
                onClick={handleAnalyze} 
                disabled={isAnalyzing || analytics.length === 0}
                className="bg-indigo-600 hover:bg-indigo-700 text-white"
            >
                {isAnalyzing ? 'Analyzing Data...' : 'Generate Insights'}
            </Button>
          </div>
          
          <p className="text-sm text-indigo-700 mb-6">
            AI will analyze the queries above to tell you what employees care about most, and identify missing knowledge gaps so you can upload new documents.
          </p>

          {analysisResult ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* Top Interests Card */}
              <div className="bg-white rounded-xl p-5 border border-indigo-100 shadow-sm flex flex-col h-full">
                <h4 className="text-indigo-900 font-bold mb-4 flex items-center gap-2">
                  <BookOpen className="w-4 h-4 text-indigo-500" />
                  What Employees Are Asking About
                </h4>
                <div className="space-y-4 flex-1">
                  {analysisResult.topInterests?.map((item, i) => (
                    <div key={i} className="bg-indigo-50/50 rounded-lg p-3 border border-indigo-50">
                      <div className="font-semibold text-indigo-900 text-sm mb-1">{item.topic}</div>
                      <div className="text-xs text-indigo-700 leading-relaxed">{item.reason}</div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Knowledge Gaps Card */}
              <div className="bg-white rounded-xl p-5 border border-rose-100 shadow-sm flex flex-col h-full relative overflow-hidden">
                <div className="absolute top-0 right-0 w-16 h-16 bg-rose-50 rounded-bl-full -z-10" />
                <h4 className="text-rose-900 font-bold mb-4 flex items-center gap-2">
                  <AlertCircle className="w-4 h-4 text-rose-500" />
                  Missing Knowledge Gaps
                </h4>
                <div className="space-y-4 flex-1">
                  {analysisResult.knowledgeGaps?.map((gap, i) => (
                    <div key={i} className="bg-rose-50/50 rounded-lg p-3 border border-rose-50">
                      <div className="font-semibold text-rose-900 text-sm mb-2 pb-2 border-b border-rose-100/50">
                        "{gap.question}"
                      </div>
                      <div className="flex items-start gap-2">
                        <Lightbulb className="w-3.5 h-3.5 text-amber-500 shrink-0 mt-0.5" />
                        <div className="text-xs text-rose-700 leading-relaxed font-medium">
                          {gap.suggestion}
                        </div>
                      </div>
                    </div>
                  ))}
                  {(!analysisResult.knowledgeGaps || analysisResult.knowledgeGaps.length === 0) && (
                    <div className="text-sm text-green-600 flex items-center gap-2 justify-center h-full">
                      <Sparkles className="w-4 h-4" /> No significant knowledge gaps detected!
                    </div>
                  )}
                </div>
              </div>
            </div>
          ) : (
            <div className="text-center py-10 bg-white/50 text-indigo-400 text-sm border-2 border-dashed border-indigo-200 rounded-xl">
              Click "Generate Insights" to run the AI analysis on user queries.
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
