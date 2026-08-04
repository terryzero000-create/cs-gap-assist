import type {
  ApiErrorPayload,
  CitationGraphResponse,
  ExperimentSuggestResponse,
  GapAnalysisResponse,
  KnowledgeSearchResponse,
  ModelConfig,
  NoteCreateRequest,
  NoteRecord,
  PaperCollectionUpdateRequest,
  PaperDeleteResponse,
  PaperListResponse,
  PaperRecord,
  PaperUploadResponse,
  PaperUploadTaskResponse,
  ReadingQAResponse,
  ReproductionAgentRequest,
  ReproductionAgentResponse,
  ResearchPlanAgentRequest,
  ResearchPlanAgentResponse,
} from '../types';

const API_PREFIX = '/api/v1';
const apiKeyStorageKey = 'cs-gap-assist-api-key';

export class ApiClientError extends Error {
  readonly errorCode: string;
  readonly retryable: boolean;
  readonly details: Record<string, unknown>;
  readonly status: number;

  constructor(payload: Partial<ApiErrorPayload>, status: number) {
    super(payload.error || '请求失败');
    this.name = 'ApiClientError';
    this.errorCode = payload.error_code || 'REQUEST_FAILED';
    this.retryable = Boolean(payload.retryable);
    this.details = payload.details || {};
    this.status = status;
  }
}

export function getStoredApiKey(): string {
  return window.sessionStorage.getItem(apiKeyStorageKey) ?? '';
}

export function setStoredApiKey(value: string): void {
  const normalized = value.trim();
  if (normalized) {
    window.sessionStorage.setItem(apiKeyStorageKey, normalized);
  } else {
    window.sessionStorage.removeItem(apiKeyStorageKey);
  }
}

async function apiFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const token = getStoredApiKey();
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  return fetch(input, { ...init, headers });
}

async function parseResponse<T>(response: Response): Promise<T> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new ApiClientError(
      {
        error: '服务返回了无法解析的响应。',
        error_code: 'INVALID_SERVER_RESPONSE',
        retryable: response.status >= 500,
      },
      response.status,
    );
  }
  if (!response.ok) {
    const payload = typeof body === 'object' && body !== null ? body as Partial<ApiErrorPayload> : {};
    throw new ApiClientError(payload, response.status);
  }
  return body as T;
}

function idempotencyKey(): string {
  return globalThis.crypto?.randomUUID?.() ?? `upload-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

async function waitForUpload(
  statusUrl: string,
  onStatus?: (task: PaperUploadTaskResponse) => void,
): Promise<PaperUploadTaskResponse> {
  for (let attempt = 0; attempt < 600; attempt += 1) {
    const task = await parseResponse<PaperUploadTaskResponse>(await apiFetch(statusUrl));
    onStatus?.(task);
    if (task.status === 'ready') {
      return task;
    }
    if (task.status === 'failed') {
      throw new ApiClientError(
        {
          error: task.error ?? '论文处理失败。',
          error_code: task.error_code ?? 'INGESTION_FAILED',
          retryable: task.retryable,
          details: { upload_id: task.upload_id, status_url: task.status_url },
        },
        422,
      );
    }
    await new Promise((resolve) => window.setTimeout(resolve, Math.min(250 + attempt * 25, 1500)));
  }
  throw new ApiClientError(
    {
      error: '论文仍在后台处理中，请稍后刷新论文列表。',
      error_code: 'UPLOAD_POLL_TIMEOUT',
      retryable: true,
    },
    408,
  );
}

export async function uploadPaper(
  file: File,
  replaceDocId?: string,
  onStatus?: (task: PaperUploadTaskResponse) => void,
): Promise<PaperUploadResponse> {
  const form = new FormData();
  form.append('file', file);
  if (replaceDocId) {
    form.append('replace_doc_id', replaceDocId);
  }
  const task = await parseResponse<PaperUploadTaskResponse>(
    await apiFetch(`${API_PREFIX}/paper-uploads`, {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey() },
      body: form,
    }),
  );
  onStatus?.(task);
  const ready = await waitForUpload(task.status_url, onStatus);
  return uploadTaskToPaper(ready);
}

export async function retryPaperUpload(
  uploadId: string,
  onStatus?: (task: PaperUploadTaskResponse) => void,
): Promise<PaperUploadResponse> {
  const task = await parseResponse<PaperUploadTaskResponse>(
    await apiFetch(`${API_PREFIX}/paper-uploads/${encodeURIComponent(uploadId)}/retry`, {
      method: 'POST',
    }),
  );
  onStatus?.(task);
  const ready = await waitForUpload(task.status_url, onStatus);
  return uploadTaskToPaper(ready);
}

function uploadTaskToPaper(ready: PaperUploadTaskResponse): PaperUploadResponse {
  return {
    doc_id: ready.doc_id,
    title: ready.title,
    chunk_count: ready.chunk_count,
    warnings: ready.warnings,
    warning_codes: ready.warning_codes,
    reupload_required: false,
  };
}

export async function listPapers(): Promise<PaperListResponse> {
  return parseResponse<PaperListResponse>(await apiFetch(`${API_PREFIX}/papers`));
}

export async function analyzeGaps(topic: string, docIds: string[], modelConfig?: ModelConfig): Promise<GapAnalysisResponse> {
  return parseResponse<GapAnalysisResponse>(
    await apiFetch(`${API_PREFIX}/gaps/analyze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ topic, doc_ids: docIds, model_config: modelConfig }),
    }),
  );
}

export async function askPaper(question: string, docIds: string[], modelConfig?: ModelConfig): Promise<ReadingQAResponse> {
  return parseResponse<ReadingQAResponse>(
    await apiFetch(`${API_PREFIX}/reading/qa`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, doc_ids: docIds, top_k: 5, model_config: modelConfig }),
    }),
  );
}

export async function listGapHistory(): Promise<GapAnalysisResponse> {
  return parseResponse<GapAnalysisResponse>(await apiFetch(`${API_PREFIX}/gaps/history`));
}

export async function listExperimentHistory(gapId?: string): Promise<ExperimentSuggestResponse> {
  const params = gapId ? `?gap_id=${encodeURIComponent(gapId)}` : '';
  return parseResponse<ExperimentSuggestResponse>(await apiFetch(`${API_PREFIX}/experiments/history${params}`));
}

export async function suggestExperiments(gapId: string, topic?: string, modelConfig?: ModelConfig): Promise<ExperimentSuggestResponse> {
  return parseResponse<ExperimentSuggestResponse>(
    await apiFetch(`${API_PREFIX}/experiments/suggest`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ gap_id: gapId, topic, model_config: modelConfig }),
    }),
  );
}

export async function runResearchPlanAgent(request: ResearchPlanAgentRequest): Promise<ResearchPlanAgentResponse> {
  return parseResponse<ResearchPlanAgentResponse>(
    await apiFetch(`${API_PREFIX}/research-plan-agent/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    }),
  );
}

export async function runReproductionAgent(request: ReproductionAgentRequest): Promise<ReproductionAgentResponse> {
  return parseResponse<ReproductionAgentResponse>(
    await apiFetch(`${API_PREFIX}/reproduction-agent/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    }),
  );
}

export async function fetchCitationGraph(keyword: string, maxNodes: number): Promise<CitationGraphResponse> {
  const params = new URLSearchParams({ keyword, max_nodes: String(maxNodes) });
  return parseResponse<CitationGraphResponse>(await apiFetch(`${API_PREFIX}/citations/graph?${params.toString()}`));
}

export async function listKnowledgePapers(tag?: string, favoritesOnly = false): Promise<PaperRecord[]> {
  const params = new URLSearchParams();
  if (tag) params.set('tag', tag);
  if (favoritesOnly) params.set('favorites_only', 'true');
  const suffix = params.toString() ? `?${params.toString()}` : '';
  return parseResponse<PaperRecord[]>(await apiFetch(`${API_PREFIX}/knowledge/papers${suffix}`));
}

export async function updateKnowledgePaper(docId: string, request: PaperCollectionUpdateRequest): Promise<PaperRecord> {
  return parseResponse<PaperRecord>(
    await apiFetch(`${API_PREFIX}/knowledge/papers/${docId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    }),
  );
}

export async function deleteKnowledgePaper(docId: string): Promise<PaperDeleteResponse> {
  return parseResponse<PaperDeleteResponse>(
    await apiFetch(`${API_PREFIX}/knowledge/papers/${encodeURIComponent(docId)}`, {
      method: 'DELETE',
    }),
  );
}

export async function createKnowledgeNote(request: NoteCreateRequest): Promise<NoteRecord> {
  return parseResponse<NoteRecord>(
    await apiFetch(`${API_PREFIX}/knowledge/notes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    }),
  );
}

export async function searchKnowledge(query: string, tag?: string, favoritesOnly = false): Promise<KnowledgeSearchResponse> {
  const params = new URLSearchParams({ query });
  if (tag) params.set('tag', tag);
  if (favoritesOnly) params.set('favorites_only', 'true');
  return parseResponse<KnowledgeSearchResponse>(await apiFetch(`${API_PREFIX}/knowledge/search?${params.toString()}`));
}
