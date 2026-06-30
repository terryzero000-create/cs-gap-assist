import type {
  CitationGraphResponse,
  ExperimentSuggestResponse,
  GapAnalysisResponse,
  KnowledgeSearchResponse,
  ModelConfig,
  NoteCreateRequest,
  NoteRecord,
  PaperCollectionUpdateRequest,
  PaperListResponse,
  PaperRecord,
  PaperUploadResponse,
  ReadingQAResponse,
  ReproductionAgentRequest,
  ReproductionAgentResponse,
  ResearchPlanAgentRequest,
  ResearchPlanAgentResponse,
} from '../types';

const API_PREFIX = '/api/v1';

async function parseResponse<T>(response: Response): Promise<T> {
  const body: unknown = await response.json();
  if (!response.ok) {
    const message = typeof body === 'object' && body !== null && 'error' in body ? String((body as { error: unknown }).error) : '请求失败';
    throw new Error(message);
  }
  return body as T;
}

export async function uploadPaper(file: File): Promise<PaperUploadResponse> {
  const form = new FormData();
  form.append('file', file);
  return parseResponse<PaperUploadResponse>(await fetch(`${API_PREFIX}/papers/upload`, { method: 'POST', body: form }));
}

export async function listPapers(): Promise<PaperListResponse> {
  return parseResponse<PaperListResponse>(await fetch(`${API_PREFIX}/papers`));
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

export async function askPaper(question: string, docIds: string[], modelConfig?: ModelConfig): Promise<ReadingQAResponse> {
  return parseResponse<ReadingQAResponse>(
    await fetch(`${API_PREFIX}/reading/qa`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, doc_ids: docIds, top_k: 5, model_config: modelConfig }),
    }),
  );
}

export async function listGapHistory(): Promise<GapAnalysisResponse> {
  return parseResponse<GapAnalysisResponse>(await fetch(`${API_PREFIX}/gaps/history`));
}

export async function listExperimentHistory(gapId?: string): Promise<ExperimentSuggestResponse> {
  const params = gapId ? `?gap_id=${encodeURIComponent(gapId)}` : '';
  return parseResponse<ExperimentSuggestResponse>(await fetch(`${API_PREFIX}/experiments/history${params}`));
}

export async function suggestExperiments(gapId: string, topic?: string, modelConfig?: ModelConfig): Promise<ExperimentSuggestResponse> {
  return parseResponse<ExperimentSuggestResponse>(
    await fetch(`${API_PREFIX}/experiments/suggest`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ gap_id: gapId, topic, model_config: modelConfig }),
    }),
  );
}

export async function runResearchPlanAgent(request: ResearchPlanAgentRequest): Promise<ResearchPlanAgentResponse> {
  return parseResponse<ResearchPlanAgentResponse>(
    await fetch(`${API_PREFIX}/research-plan-agent/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    }),
  );
}

export async function runReproductionAgent(request: ReproductionAgentRequest): Promise<ReproductionAgentResponse> {
  return parseResponse<ReproductionAgentResponse>(
    await fetch(`${API_PREFIX}/reproduction-agent/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    }),
  );
}

export async function fetchCitationGraph(keyword: string, maxNodes: number): Promise<CitationGraphResponse> {
  const params = new URLSearchParams({ keyword, max_nodes: String(maxNodes) });
  return parseResponse<CitationGraphResponse>(await fetch(`${API_PREFIX}/citations/graph?${params.toString()}`));
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
