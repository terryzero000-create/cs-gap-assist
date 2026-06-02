import { useEffect, useMemo, useState } from 'react';

import { analyzeGaps, listGapHistory, uploadPaper } from './api/client';
import { GapList } from './components/GapAnalysis/GapList';
import './style.css';
import type { GapItem, PaperUploadResponse } from './types';

interface UploadedPaper extends PaperUploadResponse {
  selected: boolean;
}

export function App() {
  const [topic, setTopic] = useState('');
  const [papers, setPapers] = useState<UploadedPaper[]>([]);
  const [gaps, setGaps] = useState<GapItem[]>([]);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedDocIds = useMemo(() => papers.filter((paper) => paper.selected).map((paper) => paper.doc_id), [papers]);
  const canAnalyze = topic.trim().length > 0 && selectedDocIds.length > 0 && !isAnalyzing;

  useEffect(() => {
    void loadHistory();
  }, []);

  async function handleUpload(fileList: FileList | null): Promise<void> {
    const file = fileList?.[0];
    if (!file) {
      return;
    }
    setIsUploading(true);
    setError(null);
    try {
      const result = await uploadPaper(file);
      setPapers((current) => [{ ...result, selected: true }, ...current]);
      setWarnings(result.warnings);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Upload failed');
    } finally {
      setIsUploading(false);
    }
  }

  async function handleAnalyze(): Promise<void> {
    setIsAnalyzing(true);
    setError(null);
    try {
      const result = await analyzeGaps(topic.trim(), selectedDocIds);
      setGaps(result.gaps);
      setWarnings(result.warnings);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Analysis failed');
    } finally {
      setIsAnalyzing(false);
    }
  }

  async function loadHistory(): Promise<void> {
    setIsLoadingHistory(true);
    setError(null);
    try {
      const result = await listGapHistory();
      setGaps(result.gaps);
      setWarnings(result.warnings);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load gap history');
    } finally {
      setIsLoadingHistory(false);
    }
  }

  function togglePaper(docId: string): void {
    setPapers((current) => current.map((paper) => (paper.doc_id === docId ? { ...paper, selected: !paper.selected } : paper)));
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">CS Gap Assist</p>
          <h1>Research Gap Workbench</h1>
        </div>
        <span className="status-pill">{selectedDocIds.length} selected</span>
      </header>

      <section className="workspace">
        <aside className="sidebar" aria-label="Papers">
          <div className="panel-header">
            <h2>Papers</h2>
            <label className="file-button">
              {isUploading ? 'Uploading' : 'Upload PDF'}
              <input type="file" accept="application/pdf" onChange={(event) => void handleUpload(event.target.files)} />
            </label>
          </div>
          <div className="paper-list">
            {papers.length === 0 ? (
              <p className="muted">No papers uploaded in this session.</p>
            ) : (
              papers.map((paper) => (
                <label className="paper-row" key={paper.doc_id}>
                  <input type="checkbox" checked={paper.selected} onChange={() => togglePaper(paper.doc_id)} />
                  <span>
                    <strong>{paper.title}</strong>
                    <small>{paper.chunk_count} chunks</small>
                  </span>
                </label>
              ))
            )}
          </div>
        </aside>

        <section className="analysis-panel" aria-label="Gap analysis">
          <div className="analysis-form">
            <div className="form-heading">
              <label htmlFor="topic">Research Topic</label>
              <button className="secondary-button" type="button" onClick={() => void loadHistory()} disabled={isLoadingHistory}>
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

          {error ? <p className="error-banner">{error}</p> : null}
          {warnings.length > 0 ? (
            <ul className="warning-list">
              {warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          ) : null}

          <GapList gaps={gaps} />
        </section>
      </section>
    </main>
  );
}
