import type { ExperimentSuggestResponse, GapAnalysisResponse, ModelConfig, PaperUploadResponse } from '../types';

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

export async function listGapHistory(): Promise<GapAnalysisResponse> {
  return parseResponse<GapAnalysisResponse>(await fetch(`${API_PREFIX}/gaps/history`));
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
