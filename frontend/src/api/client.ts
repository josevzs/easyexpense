import axios from 'axios';
import type {
  UploadSummary, ParsedData, CategorizationResponse,
  ProviderSettings, ReportResponse,
} from '../types';

const api = axios.create({ baseURL: '/api' });

// ── Upload & Fetch ──────────────────────────────────────
export async function uploadFile(file: File): Promise<UploadSummary> {
  const form = new FormData();
  form.append('file', file);
  const { data } = await api.post<UploadSummary>('/upload', form);
  return data;
}

export async function fetchRegistry(registryId: string): Promise<UploadSummary> {
  const { data } = await api.post<UploadSummary>('/fetch', { registry_id: registryId });
  return data;
}

// ── Expenses ────────────────────────────────────────────
export async function getExpenses(sessionId: string): Promise<ParsedData> {
  const { data } = await api.get<ParsedData>(`/expenses/${sessionId}`);
  return data;
}

export async function patchExpenseCategory(
  sessionId: string,
  entryId: number,
  category: string,
): Promise<void> {
  await api.patch(`/expenses/${sessionId}/${entryId}`, { category });
}

export async function getCategories(sessionId: string): Promise<{ presets: string[]; custom: string[] }> {
  const { data } = await api.get(`/categories/${sessionId}`);
  return data;
}

// ── Categorization ─────────────────────────────────────
export type SSEProgressEvent =
  | { type: 'start'; total: number; chunks: number }
  | { type: 'progress'; completed: number; total: number; chunk: number; chunks: number }
  | { type: 'result'; suggestions: CategorizationResponse['suggestions']; new_categories: string[] }
  | { type: 'done' }
  | { type: 'error'; message: string };

/**
 * Streams AI categorization via SSE.
 * Calls onEvent for each SSE message until done or error.
 */
export async function runCategorizationStream(
  sessionId: string,
  onEvent: (event: SSEProgressEvent) => void,
  entryIds?: number[],
): Promise<void> {
  const resp = await fetch('/api/categorize/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, entry_ids: entryIds ?? null }),
  });

  if (!resp.ok || !resp.body) {
    throw new Error(`HTTP ${resp.status}`);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const event = JSON.parse(line.slice(6)) as SSEProgressEvent;
          onEvent(event);
          if (event.type === 'done' || event.type === 'error') return;
        } catch {
          // ignore malformed events
        }
      }
    }
  }
}

export async function applyCategorizations(
  sessionId: string,
  applications: Array<{ entry_id: number; category: string }>,
): Promise<{ applied_count: number }> {
  const { data } = await api.post('/categorize/apply', {
    session_id: sessionId,
    applications,
  });
  return data;
}

export async function suggestCategories(sessionId: string): Promise<string[]> {
  const { data } = await api.post<{ categories: string[] }>('/categories/suggest', {
    session_id: sessionId,
  });
  return data.categories;
}

// ── Settings ────────────────────────────────────────────
export async function getSettings(): Promise<ProviderSettings> {
  const { data } = await api.get<ProviderSettings>('/settings');
  return data;
}

export async function saveSettings(settings: ProviderSettings): Promise<void> {
  await api.post('/settings', settings);
}

// ── Report ──────────────────────────────────────────────
export async function generateReport(
  sessionId: string,
  tripName: string,
  formats: string[],
  options?: {
    report_mode?: 'global' | 'personal';
    personal_member?: string;
    exclude_personal_expenses?: boolean;
    exclude_categories?: string[];
  },
): Promise<ReportResponse> {
  const { data } = await api.post<ReportResponse>('/report', {
    session_id: sessionId,
    trip_name: tripName,
    formats,
    report_mode: options?.report_mode ?? 'global',
    personal_member: options?.personal_member ?? null,
    exclude_personal_expenses: options?.exclude_personal_expenses ?? false,
    exclude_categories: options?.exclude_categories ?? [],
  });
  return data;
}
