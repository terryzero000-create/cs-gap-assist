import { ChangeEvent, FormEvent, useEffect, useMemo, useState } from 'react';

import {
  analyzeGaps,
  askPaper,
  fetchCitationGraph,
  listExperimentHistory,
  listGapHistory,
  listPapers,
  suggestExperiments,
  uploadPaper,
} from './api/client';
import { CitationForceGraph } from './components/CitationGraph/CitationForceGraph';
import { ExperimentPlanCard } from './components/ExperimentSuggest/ExperimentPlanCard';
import { GapList } from './components/GapAnalysis/GapList';
import { ReadingQA } from './components/PaperUpload/ReadingQA';
import './style.css';
import type {
  CitationGraphResponse,
  ExperimentPlan,
  GapItem,
  PaperUploadResponse,
  ReadingQAHistoryItem,
  ReadingQAResponse,
} from './types';

type ModuleKey = 'reading' | 'gaps' | 'experiments' | 'citations';

interface UploadedPaper extends PaperUploadResponse {
  selected: boolean;
  created_at?: string;
}

const historyStorageKey = 'cs-gap-assist-reading-qa-history';
const citationNodeLimits = [8, 15, 25, 40];

const modules: { key: ModuleKey; label: string }[] = [
  { key: 'reading', label: 'Reading QA' },
  { key: 'gaps', label: 'Research Gap' },
  { key: 'experiments', label: 'Experiment Suggest' },
  { key: 'citations', label: 'Citation Graph' },
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
  const keyCitationNodes = useMemo(
    () => (citationGraph?.nodes ?? []).filter((node) => node.is_key).slice(0, 5),
    [citationGraph],
  );

  useEffect(() => {
    window.localStorage.setItem(historyStorageKey, JSON.stringify(history));
  }, [history]);

  useEffect(() => {
    void loadGapPapers();
    void loadGapHistory();
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
      setReadingPapers((current) => [...current, ...uploaded]);
      setSelectedReadingDocIds((current) => [...current, ...uploaded.map((paper) => paper.doc_id)]);
    } catch (error) {
      setReadingUploadError(error instanceof Error ? error.message : 'Upload failed. Please try again.');
    } finally {
      setIsUploadingReadingPaper(false);
      event.target.value = '';
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
          createdAt: new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' }),
          result: response,
        },
        ...current,
      ].slice(0, 8));
    } catch (error) {
      setQaError(error instanceof Error ? error.message : 'Question failed. Please try again.');
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
      setGapError(caught instanceof Error ? caught.message : 'Upload failed');
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
      setGapError(caught instanceof Error ? caught.message : 'Analysis failed');
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
      setGapError(caught instanceof Error ? caught.message : 'Could not load gap history');
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
      setGapError(caught instanceof Error ? caught.message : 'Could not load papers');
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
      setExperimentError(caught instanceof Error ? caught.message : 'Could not suggest experiments');
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
      setExperimentError(caught instanceof Error ? caught.message : 'Could not load experiment history');
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

  async function handleCitationSearch(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const keyword = citationKeyword.trim();
    if (!keyword) {
      setCitationError('Enter a technical keyword.');
      return;
    }
    setIsLoadingCitationGraph(true);
    setCitationError(null);
    try {
      setCitationGraph(await fetchCitationGraph(keyword, citationMaxNodes));
    } catch (caught) {
      setCitationError(caught instanceof Error ? caught.message : 'Could not load citation graph');
    } finally {
      setIsLoadingCitationGraph(false);
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">CS Gap Assist</p>
          <h1>Research workflow MVP</h1>
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
        <section className="workspace" aria-label="Reading QA workspace">
          <aside className="sidebar">
            <div className="panel-header">
              <h2>Papers</h2>
              <span className="status-pill">{selectedReadingDocIds.length} selected</span>
            </div>
            <label className="file-button full-width">
              {isUploadingReadingPaper ? 'Uploading' : 'Upload PDFs'}
              <input accept="application/pdf" disabled={isUploadingReadingPaper} multiple onChange={handleReadingUpload} type="file" />
            </label>
            {readingUploadError ? <p className="error-banner" role="alert">{readingUploadError}</p> : null}
            <div className="selection-actions">
              <button className="secondary-button" onClick={() => setSelectedReadingDocIds(readingPapers.map((paper) => paper.doc_id))} type="button">
                Select all
              </button>
              <button className="secondary-button" onClick={() => setSelectedReadingDocIds([])} type="button">
                Clear
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
                      <small>{paper.chunk_count} chunks</small>
                    </span>
                  </label>
                  <button className="link-button" onClick={() => removeReadingPaper(paper.doc_id)} type="button">
                    Remove
                  </button>
                  {paper.warnings.map((warning) => (
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
          <aside className="sidebar" aria-label="Papers">
            <div className="panel-header">
              <h2>Papers</h2>
              <div className="paper-actions">
                <button className="secondary-button" type="button" onClick={() => void loadGapPapers()} disabled={isLoadingPapers}>
                  {isLoadingPapers ? 'Loading' : 'Refresh'}
                </button>
                <label className="file-button">
                  {isUploadingGapPaper ? 'Uploading' : 'Upload PDF'}
                  <input type="file" accept="application/pdf" onChange={(event) => void handleGapUpload(event.target.files)} />
                </label>
              </div>
            </div>
            <div className="paper-list">
              {gapPapers.length === 0 ? (
                <p className="muted">No papers uploaded yet.</p>
              ) : (
                gapPapers.map((paper) => (
                  <label className="paper-row" key={paper.doc_id}>
                    <input type="checkbox" checked={paper.selected} onChange={() => toggleGapPaper(paper.doc_id)} />
                    <span>
                      <strong>{paper.title}</strong>
                      <small>{paper.chunk_count > 0 ? `${paper.chunk_count} chunks` : `created ${new Date(paper.created_at ?? '').toLocaleDateString()}`}</small>
                    </span>
                  </label>
                ))
              )}
            </div>
          </aside>
          <section className="analysis-panel" aria-label="Gap analysis">
            <div className="analysis-form">
              <div className="form-heading">
                <label htmlFor="topic">Research topic</label>
                <button className="secondary-button" type="button" onClick={() => void loadGapHistory()} disabled={isLoadingGapHistory}>
                  {isLoadingGapHistory ? 'Loading' : 'History'}
                </button>
              </div>
              <div className="topic-row">
                <input
                  id="topic"
                  value={topic}
                  onChange={(event) => setTopic(event.target.value)}
                  placeholder="retrieval augmented generation robustness"
                />
                <button type="button" onClick={() => void handleAnalyze()} disabled={!canAnalyze}>
                  {isAnalyzing ? 'Analyzing' : 'Analyze'}
                </button>
              </div>
            </div>
            {gapError ? <p className="error-banner">{gapError}</p> : null}
            {gapWarnings.length > 0 ? (
              <ul className="warning-list">
                {gapWarnings.map((warning) => (
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
          <aside className="sidebar" aria-label="Gap history">
            <div className="panel-header">
              <h2>Stored gaps</h2>
              <button className="secondary-button" type="button" onClick={() => void loadGapHistory()} disabled={isLoadingGapHistory}>
                {isLoadingGapHistory ? 'Loading' : 'Refresh'}
              </button>
            </div>
            <div className="gap-list compact">
              {gaps.length === 0 ? (
                <p className="muted">No stored gaps found.</p>
              ) : (
                gaps.map((gap) => (
                  <button
                    className={gap.gap_id === selectedGapId ? 'gap-row selected' : 'gap-row'}
                    key={gap.gap_id}
                    type="button"
                    onClick={() => selectGap(gap.gap_id)}
                  >
                    <span className="value-level">{gap.value_level}</span>
                    <strong>{gap.title}</strong>
                    <small>{gap.description}</small>
                  </button>
                ))
              )}
            </div>
            <div className="manual-gap">
              <label htmlFor="manual-gap-id">Gap ID</label>
              <input
                id="manual-gap-id"
                value={manualGapId}
                onChange={(event) => updateManualGapId(event.target.value)}
                placeholder="gap-123"
              />
            </div>
          </aside>
          <section className="analysis-panel" aria-label="Experiment suggestions">
            <section className="selected-gap">
              <div>
                <p className="eyebrow">Selected gap</p>
                <h2>{selectedGap?.title ?? (activeGapId || 'No gap selected')}</h2>
                {selectedGap ? <p>{selectedGap.description}</p> : null}
              </div>
              {selectedGap ? <span className="value-badge value-badge-mid">{selectedGap.value_level}</span> : null}
            </section>
            <div className="plan-toolbar">
              <span>{plans.length} saved plan{plans.length === 1 ? '' : 's'}</span>
              <button className="secondary-button" type="button" onClick={() => void loadPlans(activeGapId)} disabled={!activeGapId || isLoadingPlans}>
                {isLoadingPlans ? 'Loading' : 'Reload plans'}
              </button>
            </div>
            <div className="suggest-form">
              <label htmlFor="experiment-topic">Optional topic context</label>
              <textarea
                id="experiment-topic"
                value={experimentTopic}
                onChange={(event) => setExperimentTopic(event.target.value)}
                placeholder="Longitudinal RAG robustness under deployment drift"
              />
              <button type="button" onClick={() => void handleSuggest()} disabled={!canSuggest}>
                {isSuggesting ? 'Generating' : 'Suggest experiments'}
              </button>
            </div>
            {experimentError ? <p className="error-banner">{experimentError}</p> : null}
            {experimentWarnings.length > 0 ? (
              <ul className="warning-list">
                {experimentWarnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            ) : null}
            <div className="plans">
              {plans.length === 0 ? (
                <p className="muted">Experiment plans will appear here.</p>
              ) : (
                plans.map((plan) => <ExperimentPlanCard key={plan.experiment_id} plan={plan} />)
              )}
            </div>
          </section>
        </section>
      ) : null}

      {activeModule === 'citations' ? (
        <section className="citation-workspace" aria-label="Citation graph">
          <section className="analysis-panel">
            <form className="citation-toolbar" onSubmit={(event) => void handleCitationSearch(event)}>
              <label>
                Keyword
                <input
                  value={citationKeyword}
                  onChange={(event) => setCitationKeyword(event.target.value)}
                  placeholder="graph neural networks"
                />
              </label>
              <label>
                Node cap
                <select value={citationMaxNodes} onChange={(event) => setCitationMaxNodes(Number(event.target.value))}>
                  {citationNodeLimits.map((limit) => (
                    <option value={limit} key={limit}>{limit} nodes</option>
                  ))}
                </select>
              </label>
              <button type="submit" disabled={isLoadingCitationGraph}>{isLoadingCitationGraph ? 'Loading' : 'Build graph'}</button>
            </form>
            {citationError ? <p className="error-banner">{citationError}</p> : null}
            {citationGraph?.warnings.map((warning) => (
              <p className="warning" key={warning}>{warning}</p>
            ))}
            <div className="citation-grid">
              <div className="graph-panel" aria-busy={isLoadingCitationGraph}>
                {isLoadingCitationGraph ? (
                  <div className="loading-state">Loading citation graph...</div>
                ) : (
                  <CitationForceGraph nodes={citationGraph?.nodes ?? []} links={citationGraph?.links ?? []} />
                )}
              </div>
              <aside className="summary-panel">
                <div className="stat-row">
                  <span>Nodes</span>
                  <strong>{citationGraph?.nodes.length ?? 0}</strong>
                </div>
                <div className="stat-row">
                  <span>Links</span>
                  <strong>{citationGraph?.links.length ?? 0}</strong>
                </div>
                <h2>Key papers</h2>
                <ul className="key-list">
                  {keyCitationNodes.map((node) => (
                    <li key={node.id}>
                      <strong>{node.title}</strong>
                      <span>{node.year ?? 'Year unknown'} · score {node.importance_score.toFixed(2)}</span>
                    </li>
                  ))}
                </ul>
              </aside>
            </div>
          </section>
        </section>
      ) : null}
    </main>
  );
}
