import { ChangeEvent, FormEvent, useEffect, useMemo, useState } from 'react';

import {
  analyzeGaps,
  askPaper,
  fetchCitationGraph,
  listExperimentHistory,
  listGapHistory,
  listPapers,
  runReproductionAgent,
  runResearchPlanAgent,
  suggestExperiments,
  uploadPaper,
} from './api/client';
import { CitationForceGraph } from './components/CitationGraph/CitationForceGraph';
import { ExperimentPlanCard } from './components/ExperimentSuggest/ExperimentPlanCard';
import { GapList } from './components/GapAnalysis/GapList';
import { KnowledgeBasePanel } from './components/KnowledgeBase/KnowledgeBasePanel';
import { ReadingQA } from './components/PaperUpload/ReadingQA';
import './style.css';
import type {
  CitationGraphResponse,
  ExperimentPlan,
  GapItem,
  PaperRecord,
  PaperUploadResponse,
  ReadingQAHistoryItem,
  ReadingQAResponse,
  ReproductionAgentResponse,
  ReproductionMode,
  ResearchPlanAgentResponse,
} from './types';

type ModuleKey = 'reading' | 'gaps' | 'experiments' | 'research-plan' | 'reproduction' | 'citations' | 'knowledge';

interface UploadedPaper extends PaperUploadResponse {
  selected: boolean;
  created_at?: string;
}

function paperRecordToUploadResponse(paper: { doc_id: string; title: string }): PaperUploadResponse {
  return {
    doc_id: paper.doc_id,
    title: paper.title,
    chunk_count: 0,
    warnings: [],
  };
}

function mergeReadingPapers(current: PaperUploadResponse[], next: PaperUploadResponse[]): PaperUploadResponse[] {
  const byDocId = new Map(current.map((paper) => [paper.doc_id, paper]));
  next.forEach((paper) => {
    byDocId.set(paper.doc_id, { ...paper, ...byDocId.get(paper.doc_id) });
  });
  return Array.from(byDocId.values());
}

function mergeDocIds(current: string[], next: string[]): string[] {
  return Array.from(new Set([...current, ...next]));
}

const historyStorageKey = 'jiandu-reading-qa-history-v2';
const citationNodeLimits = [8, 15, 25, 40];
const reproductionModes: ReproductionMode[] = ['standard', 'focused', 'template'];
const reproductionModeLabels: Record<ReproductionMode, string> = {
  standard: '标准复现',
  focused: '聚焦公式/算法',
  template: '模板优先',
};

const modules: { key: ModuleKey; label: string }[] = [
  { key: 'reading', label: '论文问答' },
  { key: 'research-plan', label: '研究路线规划' },
  { key: 'reproduction', label: '复现实验室' },
  { key: 'citations', label: '引用图谱' },
  { key: 'knowledge', label: '知识库' },
];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function isReadingQAHistoryItem(value: unknown): value is ReadingQAHistoryItem {
  if (!isRecord(value) || !isRecord(value.result)) {
    return false;
  }
  return (
    typeof value.id === 'string'
    && typeof value.question === 'string'
    && Array.isArray(value.paperTitles)
    && value.paperTitles.every((title) => typeof title === 'string')
    && typeof value.createdAt === 'string'
    && typeof value.result.answer === 'string'
    && Array.isArray(value.result.sources)
    && Array.isArray(value.result.warnings)
  );
}

function loadReadingQAHistory(): ReadingQAHistoryItem[] {
  try {
    const rawHistory = window.localStorage.getItem(historyStorageKey);
    const parsed: unknown = rawHistory ? JSON.parse(rawHistory) : [];
    return Array.isArray(parsed) ? parsed.filter(isReadingQAHistoryItem).slice(0, 8) : [];
  } catch {
    return [];
  }
}

function formatSystemWarning(warning: string): string {
  if (warning.includes('Xfyun Spark embedding failed')) {
    return '';
  }
  if (warning.includes('Local bge-m3 embedding request failed')) {
    return '本地 bge-m3 暂不可用。请启动 Ollama 并运行 `ollama pull bge-m3`，以启用本地语义检索。';
  }
  if (warning.includes('OPENAI_API_KEY missing') || warning.includes('mock embeddings') || warning.includes('mock vectors')) {
    return '当前使用本地测试向量。配置 OPENAI_API_KEY 后可启用生产级语义检索。';
  }
  if (warning.includes('DEEPSEEK_API_KEY missing') || warning.includes('mock chat')) {
    return '当前使用本地测试回答。配置 DEEPSEEK_API_KEY 后可启用真实模型输出。';
  }
  return warning;
}

function uniqueFormattedWarnings(warnings: string[]): string[] {
  return Array.from(new Set(warnings.map(formatSystemWarning).filter(Boolean)));
}

export function App() {
  const [activeModule, setActiveModule] = useState<ModuleKey>('reading');
  const [readingPapers, setReadingPapers] = useState<PaperUploadResponse[]>([]);
  const [selectedReadingDocIds, setSelectedReadingDocIds] = useState<string[]>([]);
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState<ReadingQAResponse | null>(null);
  const [history, setHistory] = useState<ReadingQAHistoryItem[]>(loadReadingQAHistory);
  const [isUploadingReadingPaper, setIsUploadingReadingPaper] = useState(false);
  const [isAsking, setIsAsking] = useState(false);
  const [readingUploadError, setReadingUploadError] = useState<string | null>(null);
  const [qaError, setQaError] = useState<string | null>(null);

  const [topic, setTopic] = useState('');
  const [gapPapers, setGapPapers] = useState<UploadedPaper[]>([]);
  const [gaps, setGaps] = useState<GapItem[]>([]);
  const [gapWarnings, setGapWarnings] = useState<string[]>([]);
  const [isUploadingGapPaper, setIsUploadingGapPaper] = useState(false);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isLoadingPapers, setIsLoadingPapers] = useState(false);
  const [isLoadingGapHistory, setIsLoadingGapHistory] = useState(false);
  const [gapError, setGapError] = useState<string | null>(null);

  const [selectedGapId, setSelectedGapId] = useState('');
  const [manualGapId, setManualGapId] = useState('');
  const [experimentTopic, setExperimentTopic] = useState('');
  const [plans, setPlans] = useState<ExperimentPlan[]>([]);
  const [experimentWarnings, setExperimentWarnings] = useState<string[]>([]);
  const [experimentError, setExperimentError] = useState<string | null>(null);
  const [isLoadingPlans, setIsLoadingPlans] = useState(false);
  const [isSuggesting, setIsSuggesting] = useState(false);

  const [planPapers, setPlanPapers] = useState<PaperRecord[]>([]);
  const [selectedPlanDocIds, setSelectedPlanDocIds] = useState<string[]>([]);
  const [researchDirection, setResearchDirection] = useState('');
  const [currentExperimentResult, setCurrentExperimentResult] = useState('');
  const [researchPlanResult, setResearchPlanResult] = useState<ResearchPlanAgentResponse | null>(null);
  const [researchPlanError, setResearchPlanError] = useState<string | null>(null);
  const [isLoadingPlanPapers, setIsLoadingPlanPapers] = useState(false);
  const [isRunningResearchPlan, setIsRunningResearchPlan] = useState(false);

  const [citationKeyword, setCitationKeyword] = useState('retrieval augmented generation');
  const [citationMaxNodes, setCitationMaxNodes] = useState(15);
  const [citationGraph, setCitationGraph] = useState<CitationGraphResponse | null>(null);
  const [citationError, setCitationError] = useState<string | null>(null);
  const [isLoadingCitationGraph, setIsLoadingCitationGraph] = useState(false);

  const selectedGapDocIds = useMemo(() => gapPapers.filter((paper) => paper.selected).map((paper) => paper.doc_id), [gapPapers]);
  const canAnalyze = topic.trim().length > 0 && selectedGapDocIds.length > 0 && !isAnalyzing;
  const selectedGap = useMemo(() => gaps.find((gap) => gap.gap_id === selectedGapId), [gaps, selectedGapId]);
  const activeGapId = selectedGap?.gap_id ?? manualGapId.trim();
  const canSuggest = activeGapId.length > 0 && !isSuggesting;
  const canRunResearchPlan = researchDirection.trim().length > 0 && selectedPlanDocIds.length > 0 && !isRunningResearchPlan;
  const keyCitationNodes = useMemo(
    () => (citationGraph?.nodes ?? []).filter((node) => node.is_key).slice(0, 5),
    [citationGraph],
  );

  useEffect(() => {
    window.localStorage.setItem(historyStorageKey, JSON.stringify(history));
  }, [history]);

  useEffect(() => {
    void loadReadingPapers();
    void loadGapPapers();
    void loadGapHistory();
    void loadPlanPapers();
  }, []);

  useEffect(() => {
    if (activeGapId) {
      void loadPlans(activeGapId);
    } else {
      setPlans([]);
    }
  }, [activeGapId]);

  async function handleReadingUpload(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    if (files.length === 0) {
      return;
    }
    setIsUploadingReadingPaper(true);
    setReadingUploadError(null);
    try {
      const uploaded = await Promise.all(files.map((file) => uploadPaper(file)));
      setReadingPapers((current) => mergeReadingPapers(current, uploaded));
      setSelectedReadingDocIds((current) => mergeDocIds(current, uploaded.map((paper) => paper.doc_id)));
    } catch (error) {
      setReadingUploadError(error instanceof Error ? error.message : '上传失败，请稍后重试。');
    } finally {
      setIsUploadingReadingPaper(false);
      event.target.value = '';
    }
  }

  async function loadReadingPapers(): Promise<PaperUploadResponse[]> {
    try {
      const result = await listPapers();
      const storedPapers = result.papers.map(paperRecordToUploadResponse);
      setReadingPapers((current) => mergeReadingPapers(current, storedPapers));
      return storedPapers;
    } catch (error) {
      setReadingUploadError(error instanceof Error ? error.message : '无法加载论文列表。');
      return [];
    }
  }

  async function selectPaperForReading(docId: string): Promise<void> {
    const storedPapers = await loadReadingPapers();
    if (storedPapers.some((paper) => paper.doc_id === docId) || readingPapers.some((paper) => paper.doc_id === docId)) {
      setSelectedReadingDocIds([docId]);
      setAnswer(null);
      setQaError(null);
      setActiveModule('reading');
    }
  }

  async function handleAsk(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedQuestion = question.trim();
    if (!trimmedQuestion || selectedReadingDocIds.length === 0) {
      return;
    }
    setIsAsking(true);
    setQaError(null);
    try {
      const selectedPapers = readingPapers.filter((paper) => selectedReadingDocIds.includes(paper.doc_id));
      const response = await askPaper(trimmedQuestion, selectedReadingDocIds);
      setAnswer(response);
      setHistory((current) => [
        {
          id: `${Date.now()}`,
          question: trimmedQuestion,
          paperTitles: selectedPapers.map((paper) => paper.title),
          createdAt: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
          result: response,
        },
        ...current,
      ].slice(0, 8));
    } catch (error) {
      setQaError(error instanceof Error ? error.message : '提问失败，请稍后重试。');
    } finally {
      setIsAsking(false);
    }
  }

  function handleReadingPaperSelection(docId: string, checked: boolean) {
    setSelectedReadingDocIds((current) => (checked ? [...current, docId] : current.filter((selectedDocId) => selectedDocId !== docId)));
    setAnswer(null);
  }

  function removeReadingPaper(docId: string) {
    setReadingPapers((current) => current.filter((paper) => paper.doc_id !== docId));
    setSelectedReadingDocIds((current) => current.filter((selectedDocId) => selectedDocId !== docId));
    setAnswer(null);
  }

  function restoreHistoryItem(item: ReadingQAHistoryItem) {
    setQuestion(item.question);
    setAnswer(item.result);
    setQaError(null);
  }

  async function handleGapUpload(fileList: FileList | null): Promise<void> {
    const file = fileList?.[0];
    if (!file) {
      return;
    }
    setIsUploadingGapPaper(true);
    setGapError(null);
    try {
      const result = await uploadPaper(file);
      setGapPapers((current) => [{ ...result, selected: true }, ...current]);
      setGapWarnings(result.warnings);
    } catch (caught) {
      setGapError(caught instanceof Error ? caught.message : '上传失败');
    } finally {
      setIsUploadingGapPaper(false);
    }
  }

  async function handleAnalyze(): Promise<void> {
    setIsAnalyzing(true);
    setGapError(null);
    try {
      const result = await analyzeGaps(topic.trim(), selectedGapDocIds);
      setGaps(result.gaps);
      setSelectedGapId((current) => current || result.gaps[0]?.gap_id || '');
      setGapWarnings(result.warnings);
    } catch (caught) {
      setGapError(caught instanceof Error ? caught.message : '分析失败');
    } finally {
      setIsAnalyzing(false);
    }
  }

  async function loadGapHistory(): Promise<void> {
    setIsLoadingGapHistory(true);
    setGapError(null);
    try {
      const result = await listGapHistory();
      setGaps(result.gaps);
      setSelectedGapId((current) => current || result.gaps[0]?.gap_id || '');
      setGapWarnings(result.warnings);
    } catch (caught) {
      setGapError(caught instanceof Error ? caught.message : '无法加载研究空白历史');
    } finally {
      setIsLoadingGapHistory(false);
    }
  }

  async function loadGapPapers(): Promise<void> {
    setIsLoadingPapers(true);
    setGapError(null);
    try {
      const result = await listPapers();
      setGapPapers(
        result.papers.map((paper) => ({
          doc_id: paper.doc_id,
          title: paper.title,
          chunk_count: 0,
          warnings: [],
          selected: true,
          created_at: paper.created_at,
        })),
      );
    } catch (caught) {
      setGapError(caught instanceof Error ? caught.message : '无法加载论文列表');
    } finally {
      setIsLoadingPapers(false);
    }
  }

  function toggleGapPaper(docId: string): void {
    setGapPapers((current) => current.map((paper) => (paper.doc_id === docId ? { ...paper, selected: !paper.selected } : paper)));
  }

  async function handleSuggest(): Promise<void> {
    if (!activeGapId) {
      return;
    }
    setIsSuggesting(true);
    setExperimentError(null);
    try {
      const trimmedTopic = experimentTopic.trim();
      const result = await suggestExperiments(activeGapId, trimmedTopic.length > 0 ? trimmedTopic : undefined);
      setPlans(result.experiments);
      setExperimentWarnings(result.warnings);
    } catch (caught) {
      setExperimentError(caught instanceof Error ? caught.message : '无法生成实验建议');
    } finally {
      setIsSuggesting(false);
    }
  }

  async function loadPlans(gapId: string): Promise<void> {
    setIsLoadingPlans(true);
    setExperimentError(null);
    try {
      const result = await listExperimentHistory(gapId);
      setPlans(result.experiments);
      setExperimentWarnings(result.warnings);
    } catch (caught) {
      setExperimentError(caught instanceof Error ? caught.message : '无法加载实验历史');
    } finally {
      setIsLoadingPlans(false);
    }
  }

  function selectGap(gapId: string): void {
    setSelectedGapId(gapId);
    setManualGapId('');
    setExperimentTopic('');
  }

  function updateManualGapId(value: string): void {
    setManualGapId(value);
    if (value.trim()) {
      setSelectedGapId('');
    }
  }

  async function loadPlanPapers(): Promise<void> {
    setIsLoadingPlanPapers(true);
    setResearchPlanError(null);
    try {
      const result = await listPapers();
      setPlanPapers(result.papers);
      setSelectedPlanDocIds((current) => (current.length > 0 ? current : result.papers.map((paper) => paper.doc_id)));
    } catch (caught) {
      setResearchPlanError(caught instanceof Error ? caught.message : 'Could not load papers');
    } finally {
      setIsLoadingPlanPapers(false);
    }
  }

  function togglePlanPaper(docId: string): void {
    setSelectedPlanDocIds((current) => (current.includes(docId) ? current.filter((item) => item !== docId) : [...current, docId]));
  }

  async function handleRunResearchPlan(): Promise<void> {
    if (!canRunResearchPlan) {
      return;
    }
    setIsRunningResearchPlan(true);
    setResearchPlanError(null);
    setResearchPlanResult(null);
    try {
      setResearchPlanResult(
        await runResearchPlanAgent({
          research_direction: researchDirection.trim(),
          selected_paper_ids: selectedPlanDocIds,
          experiment_result: currentExperimentResult.trim() || null,
        }),
      );
    } catch (caught) {
      setResearchPlanError(caught instanceof Error ? caught.message : 'Could not run research plan agent');
    } finally {
      setIsRunningResearchPlan(false);
    }
  }

  async function handleCitationSearch(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const keyword = citationKeyword.trim();
    if (!keyword) {
      setCitationError('请输入一个技术关键词。');
      return;
    }
    setIsLoadingCitationGraph(true);
    setCitationError(null);
    try {
      setCitationGraph(await fetchCitationGraph(keyword, citationMaxNodes));
    } catch (caught) {
      setCitationError(caught instanceof Error ? caught.message : '无法加载引用图谱');
    } finally {
      setIsLoadingCitationGraph(false);
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">简牍</p>
          <h1>计算机论文研读与选题助手</h1>
        </div>
        <nav className="module-tabs" aria-label="Modules">
          {modules.map((module) => (
            <button
              aria-pressed={activeModule === module.key}
              className={activeModule === module.key ? 'module-tab active' : 'module-tab'}
              key={module.key}
              onClick={() => setActiveModule(module.key)}
              type="button"
            >
              {module.label}
            </button>
          ))}
        </nav>
      </header>

      {activeModule === 'reading' ? (
        <section className="workspace" aria-label="论文问答工作区">
          <aside className="sidebar">
            <div className="panel-header">
              <h2>论文</h2>
              <span className="status-pill">已选 {selectedReadingDocIds.length} 篇</span>
            </div>
            <label className="file-button full-width">
              {isUploadingReadingPaper ? '上传中' : '上传 PDF'}
              <input accept="application/pdf" disabled={isUploadingReadingPaper} multiple onChange={handleReadingUpload} type="file" />
            </label>
            {readingUploadError ? <p className="error-banner" role="alert">{readingUploadError}</p> : null}
            <div className="selection-actions">
              <button className="secondary-button" onClick={() => setSelectedReadingDocIds(readingPapers.map((paper) => paper.doc_id))} type="button">
                全选
              </button>
              <button className="secondary-button" onClick={() => setSelectedReadingDocIds([])} type="button">
                清空
              </button>
            </div>
            <ul className="paper-list">
              {readingPapers.map((paper) => (
                <li className="paper-list-item" key={paper.doc_id}>
                  <label className="paper-row">
                    <input
                      checked={selectedReadingDocIds.includes(paper.doc_id)}
                      onChange={(event) => handleReadingPaperSelection(paper.doc_id, event.target.checked)}
                      type="checkbox"
                    />
                    <span>
                      <strong>{paper.title}</strong>
                      <small>{paper.chunk_count > 0 ? `${paper.chunk_count} 个片段` : '已在知识库'}</small>
                    </span>
                  </label>
                  <button className="link-button" onClick={() => removeReadingPaper(paper.doc_id)} type="button">
                    移除
                  </button>
                  {uniqueFormattedWarnings(paper.warnings).map((warning) => (
                    <small className="paper-warning" key={warning}>{warning}</small>
                  ))}
                </li>
              ))}
            </ul>
          </aside>
          <ReadingQA
            error={qaError}
            history={history}
            isAsking={isAsking}
            onAsk={handleAsk}
            onClearHistory={() => setHistory([])}
            onRestoreHistory={restoreHistoryItem}
            paperCount={readingPapers.length}
            question={question}
            result={answer}
            selectedPaperCount={selectedReadingDocIds.length}
            setQuestion={setQuestion}
          />
        </section>
      ) : null}

      {activeModule === 'gaps' ? (
        <section className="workspace">
          <aside className="sidebar" aria-label="论文">
            <div className="panel-header">
              <h2>论文</h2>
              <div className="paper-actions">
                <button className="secondary-button" type="button" onClick={() => void loadGapPapers()} disabled={isLoadingPapers}>
                  {isLoadingPapers ? '加载中' : '刷新'}
                </button>
                <label className="file-button">
                  {isUploadingGapPaper ? '上传中' : '上传 PDF'}
                  <input type="file" accept="application/pdf" onChange={(event) => void handleGapUpload(event.target.files)} />
                </label>
              </div>
            </div>
            <div className="paper-list">
              {gapPapers.length === 0 ? (
                <p className="muted">还没有上传论文。</p>
              ) : (
                gapPapers.map((paper) => (
                  <label className="paper-row" key={paper.doc_id}>
                    <input type="checkbox" checked={paper.selected} onChange={() => toggleGapPaper(paper.doc_id)} />
                    <span>
                      <strong>{paper.title}</strong>
                      <small>{paper.chunk_count > 0 ? `${paper.chunk_count} 个片段` : `创建于 ${new Date(paper.created_at ?? '').toLocaleDateString('zh-CN')}`}</small>
                    </span>
                  </label>
                ))
              )}
            </div>
          </aside>
          <section className="analysis-panel" aria-label="研究空白分析">
            <div className="analysis-form">
              <div className="form-heading">
                <label htmlFor="topic">研究方向</label>
                <button className="secondary-button" type="button" onClick={() => void loadGapHistory()} disabled={isLoadingGapHistory}>
                  {isLoadingGapHistory ? '加载中' : '历史记录'}
                </button>
              </div>
              <div className="topic-row">
                <input
                  id="topic"
                  value={topic}
                  onChange={(event) => setTopic(event.target.value)}
                  placeholder="例如：检索增强生成的鲁棒性评估"
                />
                <button type="button" onClick={() => void handleAnalyze()} disabled={!canAnalyze}>
                  {isAnalyzing ? '分析中' : '开始分析'}
                </button>
              </div>
            </div>
            {gapError ? <p className="error-banner">{gapError}</p> : null}
            {gapWarnings.length > 0 ? (
              <ul className="warning-list">
                {uniqueFormattedWarnings(gapWarnings).map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            ) : null}
            <GapList gaps={gaps} />
          </section>
        </section>
      ) : null}

      {activeModule === 'experiments' ? (
        <section className="workspace">
          <aside className="sidebar" aria-label="研究空白历史">
            <div className="panel-header">
              <h2>已保存的研究空白</h2>
              <button className="secondary-button" type="button" onClick={() => void loadGapHistory()} disabled={isLoadingGapHistory}>
                {isLoadingGapHistory ? '加载中' : '刷新'}
              </button>
            </div>
            <div className="gap-list compact">
              {gaps.length === 0 ? (
                <p className="muted">还没有保存的研究空白。</p>
              ) : (
                gaps.map((gap) => (
                  <button
                    className={gap.gap_id === selectedGapId ? 'gap-row selected' : 'gap-row'}
                    key={gap.gap_id}
                    type="button"
                    onClick={() => selectGap(gap.gap_id)}
                  >
                    <span className="value-level">{gap.value_level === 'high' ? '高价值' : '中价值'}</span>
                    <strong>{gap.title}</strong>
                    <small>{gap.description}</small>
                  </button>
                ))
              )}
            </div>
            <div className="manual-gap">
              <label htmlFor="manual-gap-id">研究空白 ID</label>
              <input
                id="manual-gap-id"
                value={manualGapId}
                onChange={(event) => updateManualGapId(event.target.value)}
                placeholder="gap-123"
              />
            </div>
          </aside>
          <section className="analysis-panel" aria-label="实验建议">
            <section className="selected-gap">
              <div>
                <p className="eyebrow">当前研究空白</p>
                <h2>{selectedGap?.title ?? (activeGapId || '尚未选择研究空白')}</h2>
                {selectedGap ? <p>{selectedGap.description}</p> : null}
              </div>
              {selectedGap ? <span className={`value-badge value-badge-${selectedGap.value_level}`}>{selectedGap.value_level === 'high' ? '高价值' : '中价值'}</span> : null}
            </section>
            <div className="plan-toolbar">
              <span>{plans.length} 个已保存方案</span>
              <button className="secondary-button" type="button" onClick={() => void loadPlans(activeGapId)} disabled={!activeGapId || isLoadingPlans}>
                {isLoadingPlans ? '加载中' : '重新加载'}
              </button>
            </div>
            <div className="suggest-form">
              <label htmlFor="experiment-topic">补充研究背景，可选</label>
              <textarea
                id="experiment-topic"
                value={experimentTopic}
                onChange={(event) => setExperimentTopic(event.target.value)}
                placeholder="例如：部署漂移下的 RAG 长期鲁棒性"
              />
              <button type="button" onClick={() => void handleSuggest()} disabled={!canSuggest}>
                {isSuggesting ? '生成中' : '生成实验建议'}
              </button>
            </div>
            {experimentError ? <p className="error-banner">{experimentError}</p> : null}
            {experimentWarnings.length > 0 ? (
              <ul className="warning-list">
                {uniqueFormattedWarnings(experimentWarnings).map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            ) : null}
            <div className="plans">
              {plans.length === 0 ? (
                <p className="muted">实验方案会显示在这里。</p>
              ) : (
                plans.map((plan) => <ExperimentPlanCard key={plan.experiment_id} plan={plan} />)
              )}
            </div>
          </section>
        </section>
      ) : null}


      {activeModule === 'research-plan' ? (
        <section className="workspace" aria-label="研究路线规划 Agent">
          <aside className="sidebar">
            <div className="panel-header">
              <h2>已选论文</h2>
              <button className="secondary-button" type="button" onClick={() => void loadPlanPapers()} disabled={isLoadingPlanPapers}>
                {isLoadingPlanPapers ? '加载中' : '刷新'}
              </button>
            </div>
            <div className="selection-actions">
              <button className="secondary-button" type="button" onClick={() => setSelectedPlanDocIds(planPapers.map((paper) => paper.doc_id))}>全选</button>
              <button className="secondary-button" type="button" onClick={() => setSelectedPlanDocIds([])}>清空</button>
            </div>
            <div className="paper-list">
              {planPapers.length === 0 ? (
                <p className="muted">还没有上传论文。</p>
              ) : (
                planPapers.map((paper) => (
                  <label className="paper-row" key={paper.doc_id}>
                    <input type="checkbox" checked={selectedPlanDocIds.includes(paper.doc_id)} onChange={() => togglePlanPaper(paper.doc_id)} />
                    <span><strong>{paper.title}</strong><small>{new Date(paper.created_at).toLocaleDateString('zh-CN')}</small></span>
                  </label>
                ))
              )}
            </div>
          </aside>
          <section className="analysis-panel" aria-label="研究路线规划 Agent">
            <div className="research-plan-form">
              <label htmlFor="research-direction">研究方向</label>
              <textarea id="research-direction" value={researchDirection} onChange={(event) => setResearchDirection(event.target.value)} placeholder="例如：面向生产漂移场景的 RAG 鲁棒性评估" />
              <label htmlFor="experiment-result">当前实验结果（可选）</label>
              <textarea id="experiment-result" value={currentExperimentResult} onChange={(event) => setCurrentExperimentResult(event.target.value)} placeholder="例如：BM25 baseline 在跨领域测试集上 F1 明显下降" />
              <button type="button" onClick={() => void handleRunResearchPlan()} disabled={!canRunResearchPlan}>{isRunningResearchPlan ? 'Agent 运行中' : '运行 Agent'}</button>
            </div>
            {researchPlanError ? <p className="error-banner">{researchPlanError}</p> : null}
            {researchPlanResult?.warnings.length ? (
              <ul className="warning-list">{uniqueFormattedWarnings(researchPlanResult.warnings).map((warning) => <li key={warning}>{warning}</li>)}</ul>
            ) : null}
            <div className="agent-grid">
              <section className="summary-panel">
                <h2>Agent 执行过程</h2>
                {researchPlanResult ? (
                  <ol className="agent-step-list">
                    {researchPlanResult.agent_steps.map((step) => (
                      <li key={step.step_index}><strong>{step.step_index}. {step.tool_name}</strong><p>{step.thought}</p><small>{step.observation}</small><em>{step.next_decision}</em></li>
                    ))}
                  </ol>
                ) : <p className="muted">运行后这里会显示工具调用、观察结果和下一步决策。</p>}
              </section>
              <section className="research-card-list">
                <h2>研究路线</h2>
                {researchPlanResult?.routes.length ? (
                  researchPlanResult.routes.map((route) => (
                    <article className="route-card" key={route.gap.gap_id}>
                      <div className="route-card-header">
                        <div>
                          <p className="eyebrow">Research Gap</p>
                          <h3>{route.gap.title}</h3>
                        </div>
                        <span className={`value-badge value-badge-${route.gap.value_level}`}>{route.gap.value_level === 'high' ? '高价值' : '中价值'}</span>
                      </div>
                      <p>{route.gap.description}</p>
                      {route.experiments.map((experiment) => (
                        <section className="route-experiment" key={experiment.experiment_id}>
                          <h4>{experiment.objective}</h4>
                          <div className="plan-grid">
                            <section><h4>数据集</h4><ul>{experiment.datasets.map((dataset) => <li key={dataset}>{dataset}</li>)}</ul></section>
                            <section><h4>指标</h4><ul>{experiment.metrics.map((metric) => <li key={metric}>{metric}</li>)}</ul></section>
                            <section><h4>Baseline</h4><ul>{experiment.baselines.map((baseline) => <li key={baseline}>{baseline}</li>)}</ul></section>
                            <section><h4>风险</h4><ul>{experiment.risks.map((risk) => <li key={risk}>{risk}</li>)}</ul></section>
                          </div>
                          <section className="steps"><h4>实验步骤</h4><ol>{experiment.steps.map((step) => <li key={step}>{step}</li>)}</ol></section>
                          <div className="support-papers">{experiment.support_papers.map((paper) => <span key={paper}>{paper}</span>)}</div>
                        </section>
                      ))}
                    </article>
                  ))
                ) : <p className="muted">Agent 会在这里输出串联 Gap 与实验建议后的研究路线。</p>}
                <h2>课题执行卡</h2>
                {researchPlanResult ? (
                  researchPlanResult.final_cards.map((card) => (
                    <article className="research-card" key={card.title}>
                      <h3>{card.title}</h3>
                      <p><strong>研究背景：</strong>{card.background}</p>
                      <p><strong>Research Gap: </strong>{card.research_gap}</p>
                      <p><strong>可行切入点：</strong>{card.entry_point}</p>
                      <p><strong>实验建议：</strong>{card.experiment_suggestion}</p>
                      <p><strong>下一步行动：</strong>{card.next_action}</p>
                      <h4>推荐阅读论文</h4><ul>{card.recommended_papers.map((paper) => <li key={paper}>{paper}</li>)}</ul>
                      <h4>风险提示</h4><ul>{card.risks.map((risk) => <li key={risk}>{risk}</li>)}</ul>
                    </article>
                  ))
                ) : <p className="muted">课题执行卡会在 Agent 完成后生成。</p>}
              </section>
            </div>
          </section>
        </section>
      ) : null}

      {activeModule === 'reproduction' ? <ReproductionLab /> : null}

      {activeModule === 'citations' ? (
        <section className="citation-workspace" aria-label="引用图谱">
          <section className="analysis-panel">
            <form className="citation-toolbar" onSubmit={(event) => void handleCitationSearch(event)}>
              <label>
                关键词
                <input
                  value={citationKeyword}
                  onChange={(event) => setCitationKeyword(event.target.value)}
                  placeholder="例如：图神经网络"
                />
              </label>
              <label>
                节点上限
                <select value={citationMaxNodes} onChange={(event) => setCitationMaxNodes(Number(event.target.value))}>
                  {citationNodeLimits.map((limit) => (
                    <option value={limit} key={limit}>{limit} 个节点</option>
                  ))}
                </select>
              </label>
              <button type="submit" disabled={isLoadingCitationGraph}>{isLoadingCitationGraph ? '加载中' : '生成图谱'}</button>
            </form>
            {citationError ? <p className="error-banner">{citationError}</p> : null}
            {uniqueFormattedWarnings(citationGraph?.warnings ?? []).map((warning) => (
              <p className="warning" key={warning}>{warning}</p>
            ))}
            <div className="citation-grid">
              <div className="graph-panel" aria-busy={isLoadingCitationGraph}>
                {isLoadingCitationGraph ? (
                  <div className="loading-state">正在加载引用图谱...</div>
                ) : (
                  <CitationForceGraph nodes={citationGraph?.nodes ?? []} links={citationGraph?.links ?? []} />
                )}
              </div>
              <aside className="summary-panel">
                <div className="stat-row">
                  <span>节点数</span>
                  <strong>{citationGraph?.nodes.length ?? 0}</strong>
                </div>
                <div className="stat-row">
                  <span>连接数</span>
                  <strong>{citationGraph?.links.length ?? 0}</strong>
                </div>
                <h2>关键论文</h2>
                <ul className="key-list">
                  {keyCitationNodes.map((node) => (
                    <li key={node.id}>
                      <strong>{node.title}</strong>
                      <span>{node.year ?? '年份未知'} · 重要性 {node.importance_score.toFixed(2)}</span>
                    </li>
                  ))}
                </ul>
              </aside>
            </div>
          </section>
        </section>
      ) : null}

      {activeModule === 'knowledge' ? (
        <section className="citation-workspace" aria-label="知识库">
          <KnowledgeBasePanel onAskWithPaper={selectPaperForReading} />
        </section>
      ) : null}
    </main>
  );
}

function ReproductionLab() {
  const [papers, setPapers] = useState<PaperRecord[]>([]);
  const [selectedPaperId, setSelectedPaperId] = useState('');
  const [mode, setMode] = useState<ReproductionMode>('standard');
  const [requirement, setRequirement] = useState('请辅助我复现论文的主要实验。');
  const [result, setResult] = useState<ReproductionAgentResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoadingPapers, setIsLoadingPapers] = useState(false);
  const [isRunning, setIsRunning] = useState(false);

  useEffect(() => {
    void loadReproductionPapers();
  }, []);

  async function loadReproductionPapers(): Promise<void> {
    setIsLoadingPapers(true);
    setError(null);
    try {
      const response = await listPapers();
      setPapers(response.papers);
      setSelectedPaperId((current) => current || response.papers[0]?.doc_id || '');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '无法加载论文列表');
    } finally {
      setIsLoadingPapers(false);
    }
  }

  async function handleRunReproduction(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!selectedPaperId) {
      setError('请先选择一篇已上传论文。');
      return;
    }
    setIsRunning(true);
    setError(null);
    setResult(null);
    try {
      setResult(
        await runReproductionAgent({
          paper_id: selectedPaperId,
          mode,
          user_requirement: requirement.trim() || '请辅助我复现论文的主要实验。',
        }),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '无法运行复现实验室 Agent');
    } finally {
      setIsRunning(false);
    }
  }

  return (
    <section className="workspace" aria-label="复现实验室">
      <aside className="sidebar">
        <div className="panel-header">
          <h2>复现实验室</h2>
          <button className="secondary-button" type="button" onClick={() => void loadReproductionPapers()} disabled={isLoadingPapers}>
            {isLoadingPapers ? '加载中' : '刷新'}
          </button>
        </div>
        <form className="reproduction-form" onSubmit={(event) => void handleRunReproduction(event)}>
          <label htmlFor="reproduction-paper">选择论文</label>
          <select
            id="reproduction-paper"
            value={selectedPaperId}
            onChange={(event) => setSelectedPaperId(event.target.value)}
            disabled={isLoadingPapers || papers.length === 0}
          >
            {papers.length === 0 ? <option value="">还没有上传论文</option> : null}
            {papers.map((paper) => (
              <option value={paper.doc_id} key={paper.doc_id}>{paper.title}</option>
            ))}
          </select>

          <label htmlFor="reproduction-mode">复现模式</label>
          <select id="reproduction-mode" value={mode} onChange={(event) => setMode(event.target.value as ReproductionMode)}>
            {reproductionModes.map((item) => (
              <option value={item} key={item}>{reproductionModeLabels[item]}</option>
            ))}
          </select>

          <label htmlFor="reproduction-requirement">复现需求</label>
          <textarea
            id="reproduction-requirement"
            value={requirement}
            onChange={(event) => setRequirement(event.target.value)}
            placeholder="例如：请整理主要实验的复现目标、数据集、指标和代码模板。"
          />

          <button type="submit" disabled={isRunning || !selectedPaperId}>
            {isRunning ? 'Agent 运行中' : '运行复现 Agent'}
          </button>
        </form>
        {!isLoadingPapers && papers.length === 0 ? <p className="muted">请先在论文问答或知识库中上传论文。</p> : null}
      </aside>

      <section className="analysis-panel" aria-label="复现实验室结果">
        {error ? <p className="error-banner">{error}</p> : null}
        {result?.warnings.length ? (
          <ul className="warning-list">
            {uniqueFormattedWarnings(result.warnings).map((warning) => <li key={warning}>{warning}</li>)}
          </ul>
        ) : null}

        <div className="agent-grid">
          <section className="summary-panel">
            <h2>Agent 执行过程</h2>
            {result ? (
              <ol className="agent-step-list">
                {result.agent_steps.map((step) => (
                  <li key={step.step_index}>
                    <strong>{step.step_index}. {step.tool_name}</strong>
                    <p>{step.thought}</p>
                    <small>{step.observation.summary}</small>
                    <em>{step.next_decision}</em>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="muted">运行后这里会显示工具调用、观察结果和下一步决策。</p>
            )}
          </section>

          <section className="research-card">
            <h2>复现报告</h2>
            {result ? <ReproductionReportView result={result} /> : <p className="muted">报告会在 Agent 完成后生成。</p>}
          </section>
        </div>
      </section>
    </section>
  );
}

function ReproductionReportView({ result }: { result: ReproductionAgentResponse }) {
  const report = result.report;
  return (
    <div className="report-sections">
      <p>{report.goal_understanding}</p>
      <ReportList title="复现目标" items={report.reproduction_targets} />
      <ReportList title="数据集" items={report.datasets} />
      <ReportList title="指标" items={report.metrics} />
      <ReportList title="Baseline" items={report.baselines} />
      <ReportList title="公式/算法线索" items={report.formula_or_algorithm_notes} />
      <ReportList title="实施计划" items={report.implementation_plan} />
      <ReportList title="风险" items={report.risks} />
      <ReportList title="限制" items={report.limitations} />
      <ReportList title="不做承诺" items={report.non_claims} />
      {report.code_template ? (
        <section>
          <h3>代码模板</h3>
          <pre>{report.code_template}</pre>
        </section>
      ) : null}
      {report.simulation_template ? (
        <section>
          <h3>仿真模板</h3>
          <pre>{report.simulation_template}</pre>
        </section>
      ) : null}
    </div>
  );
}

function ReportList({ title, items }: { title: string; items: string[] }) {
  return (
    <section>
      <h3>{title}</h3>
      <ul>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </section>
  );
}
