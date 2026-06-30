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

export interface PaperRecord {
  doc_id: string;
  title: string;
  created_at: string;
  is_favorite: boolean;
  tags: string[];
}

export interface PaperListResponse {
  papers: PaperRecord[];
}

export interface PaperCollectionUpdateRequest {
  tags: string[];
  is_favorite: boolean;
}

export interface PaperChunk {
  chunk_id: string;
  doc_id: string;
  page: number;
  text: string;
  score?: number | null;
}

export interface SourceParagraph {
  doc_id: string;
  chunk_id: string;
  page: number;
  text: string;
  score: number;
}

export interface ReadingQAResponse {
  answer: string;
  sources: SourceParagraph[];
  warnings: string[];
}

export interface ReadingQAHistoryItem {
  id: string;
  question: string;
  paperTitles: string[];
  createdAt: string;
  result: ReadingQAResponse;
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

export interface ExperimentSuggestResponse {
  experiments: ExperimentPlan[];
  warnings: string[];
}

export type ReproductionMode = 'standard' | 'focused' | 'template';

export interface ReproductionAgentRequest {
  paper_id: string;
  mode: ReproductionMode;
  user_requirement: string;
  model_config?: ModelConfig;
}

export interface ReproductionToolObservation {
  summary: string;
  evidence: string[];
  warnings: string[];
}

export interface ReproductionAgentStep {
  step_index: number;
  tool_name: string;
  thought: string;
  input_summary: string;
  observation: ReproductionToolObservation;
  next_decision: string;
}

export interface ReproductionReport {
  paper_id: string;
  mode: ReproductionMode;
  user_requirement: string;
  goal_understanding: string;
  available_evidence: string[];
  reproduction_targets: string[];
  datasets: string[];
  metrics: string[];
  baselines: string[];
  formula_or_algorithm_notes: string[];
  implementation_plan: string[];
  code_template: string;
  simulation_template: string;
  risks: string[];
  limitations: string[];
  non_claims: string[];
}

export interface ReproductionAgentResponse {
  agent_steps: ReproductionAgentStep[];
  report: ReproductionReport;
  warnings: string[];
}

export interface ResearchPlanAgentRequest {
  research_direction: string;
  selected_paper_ids: string[];
  experiment_result?: string | null;
  model_config?: ModelConfig;
}

export interface ResearchPlanAgentStep {
  step_index: number;
  tool_name: string;
  thought: string;
  observation: string;
  next_decision: string;
}

export interface ResearchPlanCard {
  title: string;
  background: string;
  research_gap: string;
  entry_point: string;
  experiment_suggestion: string;
  recommended_papers: string[];
  risks: string[];
  next_action: string;
}

export interface ResearchPlanRoute {
  gap: GapItem;
  experiments: ExperimentPlan[];
}

export interface ResearchPlanAgentResponse {
  agent_steps: ResearchPlanAgentStep[];
  routes: ResearchPlanRoute[];
  final_cards: ResearchPlanCard[];
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

export interface KnowledgeSearchResponse {
  papers: PaperRecord[];
  notes: NoteRecord[];
  chunks: PaperChunk[];
  gaps: GapItem[];
  experiments: ExperimentPlan[];
}
