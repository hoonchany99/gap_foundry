'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { getStatus, getReport, streamProgress, type ValidationStatus, type ReportResponse } from '@/lib/api';

// Markdown 렌더링을 위한 간단한 파서
function parseMarkdown(md: string): string {
  return md
    .replace(/^### (.*$)/gim, '<h3 class="text-lg font-semibold mt-6 mb-2 text-white">$1</h3>')
    .replace(/^## (.*$)/gim, '<h2 class="text-xl font-bold mt-8 mb-3 text-white border-b border-zinc-700 pb-2">$1</h2>')
    .replace(/^# (.*$)/gim, '<h1 class="text-2xl font-bold mt-10 mb-4 text-white">$1</h1>')
    .replace(/\*\*\*(.*?)\*\*\*/g, '<strong class="italic text-white">$1</strong>')
    .replace(/\*\*(.*?)\*\*/g, '<strong class="text-white">$1</strong>')
    .replace(/\*(.*?)\*/g, '<em class="text-zinc-300">$1</em>')
    .replace(/`([^`]+)`/g, '<code class="bg-zinc-800 px-1.5 py-0.5 rounded text-violet-300 text-sm">$1</code>')
    .replace(/^\s*[-*] (.*$)/gim, '<li class="ml-4 text-zinc-300">$1</li>')
    .replace(/\|(.+)\|/g, (match) => {
      const cells = match.split('|').filter(c => c.trim());
      return `<tr>${cells.map(c => `<td class="border border-zinc-700 px-3 py-1.5 text-sm">${c.trim()}</td>`).join('')}</tr>`;
    })
    .replace(/^---$/gim, '<hr class="border-zinc-700 my-6" />')
    .replace(/\n/g, '<br />');
}

const STATUS_LABELS: Record<string, { label: string; emoji: string; color: string }> = {
  queued: { label: '대기 중', emoji: '⏳', color: 'text-zinc-400' },
  pregate_checking: { label: 'PreGate 검사', emoji: '🔍', color: 'text-blue-400' },
  pregate_failed: { label: 'PreGate 실패', emoji: '❌', color: 'text-rose-400' },
  researching: { label: '리서치 중', emoji: '🔬', color: 'text-cyan-400' },
  analyzing: { label: '분석 중', emoji: '📊', color: 'text-amber-400' },
  generating_report: { label: '리포트 생성 중', emoji: '📝', color: 'text-violet-400' },
  completed: { label: '완료', emoji: '✅', color: 'text-emerald-400' },
  failed: { label: '실패', emoji: '❌', color: 'text-rose-400' },
};

const VERDICT_STYLES: Record<string, { bg: string; border: string; text: string; emoji: string }> = {
  LANDING_GO: { bg: 'bg-emerald-950/50', border: 'border-emerald-500', text: 'text-emerald-400', emoji: '🟢' },
  LANDING_HOLD: { bg: 'bg-amber-950/50', border: 'border-amber-500', text: 'text-amber-400', emoji: '🟡' },
  LANDING_NO: { bg: 'bg-rose-950/50', border: 'border-rose-500', text: 'text-rose-400', emoji: '🔴' },
};

export default function ValidatePage() {
  const params = useParams();
  const runId = params.runId as string;

  const [status, setStatus] = useState<ValidationStatus | null>(null);
  const [report, setReport] = useState<ReportResponse | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadStatus = async () => {
      try {
        const data = await getStatus(runId);
        setStatus(data);
        if (data.status === 'completed') {
          const reportData = await getReport(runId);
          setReport(reportData);
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Failed to load status');
      }
    };
    loadStatus();
  }, [runId]);

  useEffect(() => {
    if (!status || status.status === 'completed' || status.status === 'failed' || status.status === 'pregate_failed') {
      return;
    }

    const cleanup = streamProgress(
      runId,
      (data) => {
        if (data.type === 'log') {
          setLogs(prev => [...prev, data.message]);
        } else if (data.type === 'status') {
          setStatus(prev => prev ? { ...prev, status: data.status, progress: data.progress, current_step: data.current_step, verdict: data.verdict } : null);
        } else if (data.type === 'done' && data.status === 'completed') {
          getReport(runId).then(setReport).catch(console.error);
        }
      },
      () => {
        const interval = setInterval(async () => {
          try {
            const data = await getStatus(runId);
            setStatus(data);
            if (data.status === 'completed') {
              const reportData = await getReport(runId);
              setReport(reportData);
              clearInterval(interval);
            } else if (['failed', 'pregate_failed'].includes(data.status)) {
              clearInterval(interval);
            }
          } catch (e) { console.error(e); }
        }, 5000);
        return () => clearInterval(interval);
      }
    );
    return cleanup;
  }, [runId, status?.status]);

  const statusInfo = status ? STATUS_LABELS[status.status] || STATUS_LABELS.queued : STATUS_LABELS.queued;
  const verdictStyle = status?.verdict ? VERDICT_STYLES[status.verdict] : null;

  return (
    <main className="min-h-screen bg-gradient-to-br from-zinc-950 via-zinc-900 to-violet-950">
      <div className="fixed inset-0 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-violet-900/20 via-transparent to-transparent pointer-events-none" />
      
      <div className="relative z-10 container mx-auto px-4 py-8 max-w-4xl">
        <div className="mb-8">
          <Link href="/"><Button variant="ghost" className="text-zinc-400 hover:text-white">← 새 아이디어 검증</Button></Link>
        </div>

        {error && (
          <Alert variant="destructive" className="mb-6 bg-rose-950/50 border-rose-500/50">
            <AlertTitle>오류</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <Card className="bg-zinc-900/80 border-zinc-800 mb-6">
          <CardHeader>
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="text-2xl flex items-center gap-3">
                  <span className="text-3xl">{statusInfo.emoji}</span>
                  <span className={statusInfo.color}>{statusInfo.label}</span>
                </CardTitle>
                <p className="text-sm text-zinc-500 mt-1">Run ID: {runId}</p>
              </div>
              {verdictStyle && (
                <Badge variant="outline" className={`text-lg px-4 py-2 ${verdictStyle.border} ${verdictStyle.text} ${verdictStyle.bg}`}>
                  {verdictStyle.emoji} {status?.verdict?.replace('LANDING_', '')}
                </Badge>
              )}
            </div>
          </CardHeader>
          
          <CardContent>
            {status && !['completed', 'failed', 'pregate_failed'].includes(status.status) && (
              <div className="space-y-2 mb-6">
                <div className="flex justify-between text-sm">
                  <span className="text-zinc-400">{status.current_step || '진행 중...'}</span>
                  <span className="text-violet-400">{status.progress}%</span>
                </div>
                <Progress value={status.progress} className="h-2" />
              </div>
            )}

            {logs.length > 0 && status?.status !== 'completed' && (
              <div className="bg-zinc-950 rounded-lg p-4 max-h-48 overflow-y-auto font-mono text-xs">
                {logs.slice(-10).map((log, i) => <div key={i} className="text-zinc-400 py-0.5">{log}</div>)}
              </div>
            )}

            {status?.error_message && (
              <Alert variant="destructive" className="bg-rose-950/50 border-rose-500/50">
                <AlertTitle>오류 상세</AlertTitle>
                <AlertDescription>{status.error_message}</AlertDescription>
              </Alert>
            )}
          </CardContent>
        </Card>

        {report && (
          <Card className="bg-zinc-900/80 border-zinc-800">
            <CardHeader className="border-b border-zinc-800">
              <div className="flex items-center justify-between">
                <CardTitle className="text-xl">📋 검증 리포트</CardTitle>
                <a href={`http://localhost:8000/report/${runId}/download`} download>
                  <Button variant="outline" size="sm" className="border-zinc-700 hover:bg-zinc-800">📥 다운로드</Button>
                </a>
              </div>
            </CardHeader>
            <CardContent className="p-6">
              <article 
                className="prose prose-invert prose-zinc max-w-none prose-headings:text-white prose-p:text-zinc-300"
                dangerouslySetInnerHTML={{ __html: parseMarkdown(report.report_markdown) }}
              />
            </CardContent>
          </Card>
        )}

        {status && !['completed', 'failed', 'pregate_failed'].includes(status.status) && (
          <div className="text-center py-12">
            <div className="inline-flex items-center gap-3 text-zinc-400">
              <div className="w-6 h-6 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" />
              <span>AI가 열심히 분석 중입니다... (약 10-15분 소요)</span>
            </div>
            <p className="text-sm text-zinc-600 mt-4">이 페이지를 떠나도 분석은 계속됩니다.</p>
          </div>
        )}
      </div>
    </main>
  );
}
