import { ChangeEvent, FormEvent, useEffect, useState } from 'react';

import { askPaper, uploadPaper } from './api/client';
import { ReadingQA } from './components/PaperUpload/ReadingQA';
import './style.css';
import type { PaperUploadResponse, ReadingQAHistoryItem, ReadingQAResponse } from './types';

const historyStorageKey = 'cs-gap-assist-reading-qa-history';

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
  const [papers, setPapers] = useState<PaperUploadResponse[]>([]);
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([]);
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState<ReadingQAResponse | null>(null);
  const [history, setHistory] = useState<ReadingQAHistoryItem[]>(loadReadingQAHistory);
  const [isUploading, setIsUploading] = useState(false);
  const [isAsking, setIsAsking] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [qaError, setQaError] = useState<string | null>(null);

  useEffect(() => {
    window.localStorage.setItem(historyStorageKey, JSON.stringify(history));
  }, [history]);

  async function handleUpload(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    if (files.length === 0) {
      return;
    }

    setIsUploading(true);
    setUploadError(null);
    try {
      const uploaded = await Promise.all(files.map((file) => uploadPaper(file)));
      setPapers((current) => [...current, ...uploaded]);
      setSelectedDocIds((current) => [...current, ...uploaded.map((paper) => paper.doc_id)]);
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : '上传失败，请稍后重试。');
    } finally {
      setIsUploading(false);
      event.target.value = '';
    }
  }

  async function handleAsk(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedQuestion = question.trim();
    if (!trimmedQuestion || selectedDocIds.length === 0) {
      return;
    }

    setIsAsking(true);
    setQaError(null);
    try {
      const selectedPapers = papers.filter((paper) => selectedDocIds.includes(paper.doc_id));
      const response = await askPaper(trimmedQuestion, selectedDocIds);
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

  function handlePaperSelection(docId: string, checked: boolean) {
    setSelectedDocIds((current) => (checked ? [...current, docId] : current.filter((selectedDocId) => selectedDocId !== docId)));
    setAnswer(null);
  }

  function removePaper(docId: string) {
    setPapers((current) => current.filter((paper) => paper.doc_id !== docId));
    setSelectedDocIds((current) => current.filter((selectedDocId) => selectedDocId !== docId));
    setAnswer(null);
  }

  function selectAllPapers() {
    setSelectedDocIds(papers.map((paper) => paper.doc_id));
    setAnswer(null);
  }

  function clearPaperSelection() {
    setSelectedDocIds([]);
    setAnswer(null);
  }

  function restoreHistoryItem(item: ReadingQAHistoryItem) {
    setQuestion(item.question);
    setAnswer(item.result);
    setQaError(null);
  }

  function clearHistory() {
    setHistory([]);
  }

  return (
    <main className="shell">
      <header className="app-header">
        <p className="eyebrow">CS Gap Assist</p>
        <h1>论文精读问答</h1>
        <p>上传论文后，围绕全文提问，答案会附带可追溯的来源段落。</p>
      </header>

      <section className="workspace" aria-label="论文精读工作台">
        <aside className="upload-panel">
          <div>
            <h2>论文</h2>
            <p className="panel-copy">已上传 {papers.length} 篇，已选择 {selectedDocIds.length} 篇</p>
          </div>

          <label className="upload-dropzone">
            <span>{isUploading ? '上传中...' : '选择 PDF'}</span>
            <input accept="application/pdf" disabled={isUploading} multiple onChange={handleUpload} type="file" />
          </label>

          {uploadError ? <p className="alert" role="alert">{uploadError}</p> : null}

          {papers.length > 0 ? (
            <div className="selection-actions" aria-label="论文选择操作">
              <button className="secondary-button" onClick={selectAllPapers} type="button">全选</button>
              <button className="secondary-button" onClick={clearPaperSelection} type="button">清空选择</button>
            </div>
          ) : null}

          <ul className="paper-list">
            {papers.map((paper) => (
              <li key={paper.doc_id}>
                <label className="paper-option">
                  <input
                    checked={selectedDocIds.includes(paper.doc_id)}
                    onChange={(event) => handlePaperSelection(paper.doc_id, event.target.checked)}
                    type="checkbox"
                  />
                  <span>
                    <strong>{paper.title}</strong>
                    <small>{paper.chunk_count} 个段落</small>
                  </span>
                </label>
                <button className="remove-button" onClick={() => removePaper(paper.doc_id)} type="button" aria-label={`移除 ${paper.title}`}>
                  移除
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
          onClearHistory={clearHistory}
          onRestoreHistory={restoreHistoryItem}
          paperCount={papers.length}
          question={question}
          result={answer}
          selectedPaperCount={selectedDocIds.length}
          setQuestion={setQuestion}
        />
      </section>
    </main>
  );
}
