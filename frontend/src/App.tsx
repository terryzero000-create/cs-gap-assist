import { ChangeEvent, FormEvent, useEffect, useMemo, useState } from 'react';

import { analyzeGaps, askPaper, listGapHistory, listPapers, uploadPaper } from './api/client';
import { GapList } from './components/GapAnalysis/GapList';
import { ReadingQA } from './components/PaperUpload/ReadingQA';
import './style.css';
import type { GapItem, PaperUploadResponse, ReadingQAHistoryItem, ReadingQAResponse } from './types';

type ModuleKey = 'reading' | 'gaps';

interface UploadedPaper extends PaperUploadResponse {
  selected: boolean;
  created_at?: string;
}

const historyStorageKey = 'cs-gap-assist-reading-qa-history';

const modules: { key: ModuleKey; label: string }[] = [
  { key: 'reading', label: 'Reading QA' },
  { key: 'gaps', label: 'Research Gap' },
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
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [gapError, setGapError] = useState<string | null>(null);

  const selectedGapDocIds = useMemo(() => gapPapers.filter((paper) => paper.selected).map((paper) => paper.doc_id), [gapPapers]);
  const canAnalyze = topic.trim().length > 0 && selectedGapDocIds.length > 0 && !isAnalyzing;

  useEffect(() => {
    window.localStorage.setItem(historyStorageKey, JSON.stringify(history));
  }, [history]);

  useEffect(() => {
    void loadGapPapers();
    void loadGapHistory();
  }, []);

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
      setGapWarnings(result.warnings);
    } catch (caught) {
      setGapError(caught instanceof Error ? caught.message : 'Analysis failed');
    } finally {
      setIsAnalyzing(false);
    }
  }

  async function loadGapHistory(): Promise<void> {
    setIsLoadingHistory(true);
    setGapError(null);
    try {
      const result = await listGapHistory();
      setGaps(result.gaps);
      setGapWarnings(result.warnings);
    } catch (caught) {
      setGapError(caught instanceof Error ? caught.message : 'Could not load gap history');
    } finally {
      setIsLoadingHistory(false);
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
      ) : (
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
                <button className="secondary-button" type="button" onClick={() => void loadGapHistory()} disabled={isLoadingHistory}>
                  {isLoadingHistory ? 'Loading' : 'History'}
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
      )}
    </main>
  );
}
