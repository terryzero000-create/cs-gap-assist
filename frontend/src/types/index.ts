export interface ApiErrorPayload {
  error: string;
  code: number;
}

export interface ModelConfig {
  chat_provider?: string;
  chat_model?: string;
  embedding_provider?: string;
  embedding_model?: string;
}

export interface PaperUploadResponse {
  doc_id: string;
  title: string;
  chunk_count: number;
  warnings: string[];
}

export interface SourceParagraph {
  doc_id: string;
  chunk_id: string;
  page: number;
  text: string;
  score: number;
}

export interface GapItem {
  gap_id: string;
  title: string;
  value_level: 'high' | 'mid';
  description: string;
  evidence_papers: string[];
  created_at: string;
}

export interface GapAnalysisResponse {
  gaps: GapItem[];
  warnings: string[];
}

export interface PaperRecord {
  doc_id: string;
  title: string;
  created_at: string;
  is_favorite: boolean;
  tags: string[];
}

export interface PaperChunk {
  chunk_id: string;
  doc_id: string;
  page: number;
  text: string;
  score?: number | null;
}

export interface NoteCreateRequest {
  title: string;
  content: string;
  tags: string[];
  related_doc_id?: string | null;
  related_gap_id?: string | null;
}

export interface NoteRecord extends NoteCreateRequest {
  note_id: string;
  created_at: string;
}

export interface PaperCollectionUpdateRequest {
  tags: string[];
  is_favorite: boolean;
}

export interface ExperimentPlan {
  experiment_id: string;
  gap_id: string;
  objective: string;
  datasets: string[];
  metrics: string[];
  baselines: string[];
  steps: string[];
  risks: string[];
  support_papers: string[];
}

export interface KnowledgeSearchResponse {
  papers: PaperRecord[];
  notes: NoteRecord[];
  chunks: PaperChunk[];
  gaps: GapItem[];
  experiments: ExperimentPlan[];
}
