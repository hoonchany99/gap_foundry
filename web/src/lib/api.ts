/**
 * Gap Foundry API Client
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export interface ValidationRequest {
  idea_one_liner: string;
  target_customer: string;
  problem_statement: string;
  current_alternatives: string;
  geo_market: 'KR' | 'US' | 'Global';
  business_type: 'B2B' | 'B2C' | 'B2B2C';
  constraints?: string;
  success_definition?: string;
}

export interface PreGateRequest {
  idea_one_liner: string;
  target_customer: string;
  problem_statement: string;
  current_alternatives?: string;
}

export interface PreGateResponse {
  is_valid: boolean;
  score: number;
  fail_reasons: string[];
  warnings: string[];
  suggestions: string[];
}

export interface ValidationStatus {
  run_id: string;
  status: 'queued' | 'pregate_checking' | 'pregate_failed' | 'researching' | 'analyzing' | 'generating_report' | 'completed' | 'failed';
  progress: number;
  current_step: string | null;
  verdict: string | null;
  created_at: string;
  updated_at: string | null;
  report_url: string | null;
  error_message: string | null;
}

export interface ReportResponse {
  run_id: string;
  verdict: string;
  report_markdown: string;
  created_at: string;
}

export interface JobSummary {
  run_id: string;
  status: string;
  verdict: string | null;
  created_at: string;
  idea_preview: string;
}

/**
 * PreGate 빠른 체크 (동기, LLM 호출 없음)
 */
export async function checkPreGate(data: PreGateRequest): Promise<PreGateResponse> {
  const res = await fetch(`${API_BASE}/pregate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  
  if (!res.ok) {
    throw new Error(`PreGate check failed: ${res.statusText}`);
  }
  
  return res.json();
}

/**
 * 아이디어 검증 요청 (비동기)
 */
export async function submitValidation(data: ValidationRequest): Promise<ValidationStatus> {
  const res = await fetch(`${API_BASE}/validate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || 'Validation request failed');
  }
  
  return res.json();
}

/**
 * 작업 상태 조회
 */
export async function getStatus(runId: string): Promise<ValidationStatus> {
  const res = await fetch(`${API_BASE}/status/${runId}`);
  
  if (!res.ok) {
    throw new Error(`Status check failed: ${res.statusText}`);
  }
  
  return res.json();
}

/**
 * 리포트 조회
 */
export async function getReport(runId: string): Promise<ReportResponse> {
  const res = await fetch(`${API_BASE}/report/${runId}`);
  
  if (!res.ok) {
    throw new Error(`Report fetch failed: ${res.statusText}`);
  }
  
  return res.json();
}

/**
 * 최근 작업 목록 조회
 */
export async function getJobs(limit: number = 20): Promise<JobSummary[]> {
  const res = await fetch(`${API_BASE}/jobs?limit=${limit}`);
  
  if (!res.ok) {
    throw new Error(`Jobs fetch failed: ${res.statusText}`);
  }
  
  return res.json();
}

/**
 * SSE 스트림 연결
 */
export function streamProgress(runId: string, onMessage: (data: any) => void, onError?: (error: Error) => void): () => void {
  const eventSource = new EventSource(`${API_BASE}/stream/${runId}`);
  
  eventSource.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      onMessage(data);
      
      if (data.type === 'done') {
        eventSource.close();
      }
    } catch (e) {
      console.error('Failed to parse SSE message:', e);
    }
  };
  
  eventSource.onerror = (event) => {
    console.error('SSE error:', event);
    onError?.(new Error('SSE connection failed'));
    eventSource.close();
  };
  
  // Cleanup function
  return () => eventSource.close();
}
