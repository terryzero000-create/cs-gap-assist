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

export interface CitationNode {
  id: string;
  title: string;
  year: number | null;
  importance_score: number;
  is_key: boolean;
}

export interface CitationLink {
  source: string;
  target: string;
  relation: string;
}

export interface CitationGraphResponse {
  nodes: CitationNode[];
  links: CitationLink[];
  warnings: string[];
}
