import type {
  GapAnalysisResponse,
  KnowledgeSearchResponse,
  ModelConfig,
  NoteCreateRequest,
  NoteRecord,
  PaperCollectionUpdateRequest,
  PaperRecord,
  PaperUploadResponse,
} from '../types';

const API_PREFIX = '/api/v1';

async function parseResponse<T>(response: Response): Promise<T> {
  const body: unknown = await response.json();
  if (!response.ok) {
    const message = typeof body === 'object' && body !== null && 'error' in body ? String((body as { error: unknown }).error) : 'Request failed';
    throw new Error(message);
  }
  return body as T;
}

export async function uploadPaper(file: File): Promise<PaperUploadResponse> {
  const form = new FormData();
  form.append('file', file);
  return parseResponse<PaperUploadResponse>(await fetch(`${API_PREFIX}/papers/upload`, { method: 'POST', body: form }));
}

export async function analyzeGaps(topic: string, docIds: string[], modelConfig?: ModelConfig): Promise<GapAnalysisResponse> {
  return parseResponse<GapAnalysisResponse>(
    await fetch(`${API_PREFIX}/gaps/analyze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ topic, doc_ids: docIds, model_config: modelConfig }),
    }),
  );
}

export async function listKnowledgePapers(tag?: string, favoritesOnly = false): Promise<PaperRecord[]> {
  const params = new URLSearchParams();
  if (tag) {
    params.set('tag', tag);
  }
  if (favoritesOnly) {
    params.set('favorites_only', 'true');
  }
  const suffix = params.toString() ? `?${params.toString()}` : '';
  return parseResponse<PaperRecord[]>(await fetch(`${API_PREFIX}/knowledge/papers${suffix}`));
}

export async function updateKnowledgePaper(docId: string, request: PaperCollectionUpdateRequest): Promise<PaperRecord> {
  return parseResponse<PaperRecord>(
    await fetch(`${API_PREFIX}/knowledge/papers/${docId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    }),
  );
}

export async function createKnowledgeNote(request: NoteCreateRequest): Promise<NoteRecord> {
  return parseResponse<NoteRecord>(
    await fetch(`${API_PREFIX}/knowledge/notes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    }),
  );
}

export async function searchKnowledge(query: string, tag?: string, favoritesOnly = false): Promise<KnowledgeSearchResponse> {
  const params = new URLSearchParams({ query });
  if (tag) {
    params.set('tag', tag);
  }
  if (favoritesOnly) {
    params.set('favorites_only', 'true');
  }
  return parseResponse<KnowledgeSearchResponse>(await fetch(`${API_PREFIX}/knowledge/search?${params.toString()}`));
}
