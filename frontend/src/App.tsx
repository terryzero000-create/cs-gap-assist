import { ChangeEvent, FormEvent, useEffect, useState } from 'react';

import {
  ApiClientError,
  askPaper,
  fetchCitationGraph,
  getStoredApiKey,
  listPapers,
  retryPaperUpload,
  runResearchPlanAgent,
  setStoredApiKey,
  uploadPaper,
} from './api/client';
import { CitationModule } from './modules/CitationModule';
import { KnowledgeModule } from './modules/KnowledgeModule';
import { ReadingModule } from './modules/ReadingModule';
import { ReproductionModule } from './modules/ReproductionModule';
import { ResearchPlanModule } from './modules/ResearchPlanModule';
import './style.css';
import type {
  CitationGraphResponse,
  PaperRecord,
  PaperUploadResponse,
  ReadingQAHistoryItem,
  ReadingQAResponse,
  ResearchPlanAgentResponse,
} from './types';

type ModuleKey = 'reading' | 'research-plan' | 'reproduction' | 'citations' | 'knowledge';

function paperRecordToUploadResponse(
  paper: Pick<PaperRecord, 'doc_id' | 'title' | 'reupload_required'>,
): PaperUploadResponse {
  return {
    doc_id: paper.doc_id,
    title: paper.title,
    chunk_count: 0,
    warnings: [],
    warning_codes: [],
    reupload_required: paper.reupload_required,
  };
}

function mergeReadingPapers(current: PaperUploadResponse[], next: PaperUploadResponse[]): PaperUploadResponse[] {
  const byDocId = new Map(current.map((paper) => [paper.doc_id, paper]));
  next.forEach((paper) => {
    byDocId.set(paper.doc_id, { ...byDocId.get(paper.doc_id), ...paper });
  });
  return Array.from(byDocId.values());
}

function mergeDocIds(current: string[], next: string[]): string[] {
  return Array.from(new Set([...current, ...next]));
}

const historyStorageKey = 'jiandu-reading-qa-history-v2';

const modules: { key: ModuleKey; label: string; note: string; description: string }[] = [
  {
    key: 'reading',
    label: '论文问答',
    note: '基于来源的精读',
    description: '选中论文，用带引用的问答快速定位方法、结论与关键证据。',
  },
  {
    key: 'research-plan',
    label: '研究路线',
    note: '从问题到选题',
    description: '串联现有论文、研究空白与实验方向，形成一条可执行的研究路线。',
  },
  {
    key: 'reproduction',
    label: '复现实验室',
    note: '把论文变成步骤',
    description: '拆解实现依赖、关键公式与实验配置，让复现过程更有把握。',
  },
  {
    key: 'citations',
    label: '引用图谱',
    note: '追踪方法演化',
    description: '从关键词出发观察关键论文、引用关系与技术脉络。',
  },
  {
    key: 'knowledge',
    label: '知识库',
    note: '沉淀研究资产',
    description: '集中管理论文、笔记、标签与历史结果，随时检索和继续研读。',
  },
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

function readableClientError(error: unknown, fallback: string): string {
  if (error instanceof ApiClientError) {
    const suffix = error.retryable ? ' 可稍后重试。' : '';
    return `${fallback}（${error.errorCode}）${error.message}${suffix}`;
  }
  if (!(error instanceof Error)) {
    return fallback;
  }
  return error.message;
}

function ApiKeySetup({ onSave }: { onSave: (value: string) => void }) {
  const [value, setValue] = useState('');
  return (
    <main className="auth-shell">
      <form
        className="auth-card"
        onSubmit={(event) => {
          event.preventDefault();
          if (value.trim()) {
            onSave(value);
          }
        }}
      >
        <p className="eyebrow">LOCAL ACCESS</p>
        <h1>连接本地研究工作台</h1>
        <p>请输入后端环境变量 <code>APP_API_KEY</code> 的值。密钥只保存在当前浏览器标签页。</p>
        <label htmlFor="api-key">API Key</label>
        <input
          id="api-key"
          type="password"
          autoComplete="off"
          value={value}
          onChange={(event) => setValue(event.target.value)}
        />
        <button type="submit" disabled={!value.trim()}>进入工作台</button>
      </form>
    </main>
  );
}

export function App() {
  const [apiKey, setApiKey] = useState(getStoredApiKey);
  const [activeModule, setActiveModule] = useState<ModuleKey>('reading');
  const [readingPapers, setReadingPapers] = useState<PaperUploadResponse[]>([]);
  const [selectedReadingDocIds, setSelectedReadingDocIds] = useState<string[]>([]);
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState<ReadingQAResponse | null>(null);
  const [history, setHistory] = useState<ReadingQAHistoryItem[]>(loadReadingQAHistory);
  const [isUploadingReadingPaper, setIsUploadingReadingPaper] = useState(false);
  const [isAsking, setIsAsking] = useState(false);
  const [readingUploadError, setReadingUploadError] = useState<string | null>(null);
  const [readingUploadStage, setReadingUploadStage] = useState<string | null>(null);
  const [failedUploadId, setFailedUploadId] = useState<string | null>(null);
  const [qaError, setQaError] = useState<string | null>(null);

  const [isLoadingPapers, setIsLoadingPapers] = useState(false);

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

  const canRunResearchPlan = researchDirection.trim().length > 0 && selectedPlanDocIds.length > 0 && !isRunningResearchPlan;
  const activeModuleDetail = modules.find((module) => module.key === activeModule) ?? modules[0];
  const activeModuleIndex = modules.findIndex((module) => module.key === activeModule) + 1;

  useEffect(() => {
    window.localStorage.setItem(historyStorageKey, JSON.stringify(history));
  }, [history]);

  useEffect(() => {
    if (apiKey) {
      void loadSharedPapers();
    }
  }, [apiKey]);

  async function handleReadingUpload(
    event: ChangeEvent<HTMLInputElement>,
    replaceDocId?: string,
  ) {
    const files = Array.from(event.target.files ?? []);
    if (files.length === 0) {
      return;
    }
    setIsUploadingReadingPaper(true);
    setReadingUploadError(null);
    setFailedUploadId(null);
    try {
      const uploaded = await Promise.all(files.map((file) => uploadPaper(
        file,
        replaceDocId,
        (task) => setReadingUploadStage(task.status),
      )));
      setReadingPapers((current) => mergeReadingPapers(current, uploaded));
      setSelectedReadingDocIds((current) => mergeDocIds(current, uploaded.map((paper) => paper.doc_id)));
    } catch (error) {
      setReadingUploadError(readableClientError(error, '上传失败，请稍后重试。'));
      if (error instanceof ApiClientError && typeof error.details.upload_id === 'string' && error.retryable) {
        setFailedUploadId(error.details.upload_id);
      }
    } finally {
      setIsUploadingReadingPaper(false);
      setReadingUploadStage(null);
      event.target.value = '';
    }
  }

  async function handleRetryUpload(): Promise<void> {
    if (!failedUploadId) return;
    setIsUploadingReadingPaper(true);
    setReadingUploadError(null);
    try {
      const uploaded = await retryPaperUpload(
        failedUploadId,
        (task) => setReadingUploadStage(task.status),
      );
      setReadingPapers((current) => mergeReadingPapers(current, [uploaded]));
      setSelectedReadingDocIds((current) => mergeDocIds(current, [uploaded.doc_id]));
      setFailedUploadId(null);
    } catch (error) {
      setReadingUploadError(readableClientError(error, '重试上传失败。'));
    } finally {
      setIsUploadingReadingPaper(false);
      setReadingUploadStage(null);
    }
  }

  async function loadReadingPapers(): Promise<PaperUploadResponse[]> {
    try {
      const result = await listPapers();
      const storedPapers = result.papers.map(paperRecordToUploadResponse);
      setReadingPapers((current) => mergeReadingPapers(current, storedPapers));
      return storedPapers;
    } catch (error) {
      setReadingUploadError(readableClientError(error, '无法读取论文列表。'));
      return [];
    }
  }

  async function loadSharedPapers(): Promise<void> {
    setIsLoadingPapers(true);
    setIsLoadingPlanPapers(true);
    try {
      const result = await listPapers();
      const storedPapers = result.papers.map(paperRecordToUploadResponse);
      setReadingPapers(storedPapers);
      setPlanPapers(result.papers);
      setSelectedPlanDocIds((current) => (
        current.length > 0
          ? current
          : result.papers
            .filter((paper) => !paper.reupload_required)
            .map((paper) => paper.doc_id)
      ));
    } catch (error) {
      setReadingUploadError(readableClientError(error, '无法读取论文列表。'));
    } finally {
      setIsLoadingPapers(false);
      setIsLoadingPlanPapers(false);
    }
  }

  async function selectPaperForReading(docId: string): Promise<void> {
    const storedPapers = await loadReadingPapers();
    if (
      storedPapers.some((paper) => paper.doc_id === docId && !paper.reupload_required)
      || readingPapers.some((paper) => paper.doc_id === docId && !paper.reupload_required)
    ) {
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
      setQaError(readableClientError(error, '提问失败，请稍后重试。'));
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

  async function loadPlanPapers(): Promise<void> {
    setIsLoadingPlanPapers(true);
    setResearchPlanError(null);
    try {
      const result = await listPapers();
      setPlanPapers(result.papers);
      setSelectedPlanDocIds((current) => (
        current.length > 0
          ? current
          : result.papers
            .filter((paper) => !paper.reupload_required)
            .map((paper) => paper.doc_id)
      ));
    } catch (caught) {
      setResearchPlanError(readableClientError(caught, '无法加载论文列表。'));
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
      setResearchPlanError(readableClientError(caught, '无法运行研究路线 Agent。'));
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
      setCitationError(readableClientError(caught, '无法加载引用图谱。'));
    } finally {
      setIsLoadingCitationGraph(false);
    }
  }

  function clearApiKey(): void {
    setStoredApiKey('');
    setApiKey('');
  }

  if (!apiKey) {
    return <ApiKeySetup onSave={(value) => {
      setStoredApiKey(value);
      setApiKey(value.trim());
    }} />;
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand-lockup">
          <span className="brand-mark" aria-hidden="true">简</span>
          <div>
            <p className="eyebrow">JIANDU / RESEARCH OS</p>
            <h1>计算机论文研读<br />与选题助手</h1>
          </div>
        </div>
        <nav className="module-tabs" aria-label="Modules">
          <p className="nav-label">研究工作流</p>
          {modules.map((module, index) => (
            <button
              aria-pressed={activeModule === module.key}
              className={activeModule === module.key ? 'module-tab active' : 'module-tab'}
              key={module.key}
              onClick={() => setActiveModule(module.key)}
              type="button"
            >
              <span className="module-index" aria-hidden="true">{String(index + 1).padStart(2, '0')}</span>
              <span className="module-tab-copy">
                <strong>{module.label}</strong>
                <small>{module.note}</small>
              </span>
            </button>
          ))}
        </nav>
        <div className="rail-status">
          <span className="status-dot" aria-hidden="true" />
          <span><strong>Local-first</strong> 本地知识工作台</span>
          <button className="secondary-button" type="button" onClick={clearApiKey}>更换 API Key</button>
        </div>
      </header>

      <section className="page-intro" aria-labelledby="active-module-title">
        <div>
          <p className="page-kicker">WORKSPACE / {String(activeModuleIndex).padStart(2, '0')}</p>
          <h2 id="active-module-title">{activeModuleDetail.label}</h2>
          <p>{activeModuleDetail.description}</p>
        </div>
        <div className="page-meta" aria-label="工作区特性">
          <span>来源可追溯</span>
          <span>本地优先</span>
        </div>
      </section>

      {activeModule === 'reading' ? (
        <ReadingModule
          answer={answer}
          failedUploadId={failedUploadId}
          history={history}
          isAsking={isAsking}
          isUploading={isUploadingReadingPaper}
          onAsk={handleAsk}
          onClearHistory={() => setHistory([])}
          onClearSelection={() => setSelectedReadingDocIds([])}
          onRemove={removeReadingPaper}
          onRestoreHistory={restoreHistoryItem}
          onRetry={() => void handleRetryUpload()}
          onReupload={(docId, event) => void handleReadingUpload(event, docId)}
          onSelect={handleReadingPaperSelection}
          onSelectAll={() => setSelectedReadingDocIds(
            readingPapers
              .filter((paper) => !paper.reupload_required)
              .map((paper) => paper.doc_id),
          )}
          onUpload={handleReadingUpload}
          papers={readingPapers}
          qaError={qaError}
          question={question}
          selectedDocIds={selectedReadingDocIds}
          setQuestion={setQuestion}
          uploadError={readingUploadError}
          uploadStage={readingUploadStage}
        />
      ) : null}

      {activeModule === 'research-plan' ? (
        <ResearchPlanModule
          canRun={canRunResearchPlan}
          currentExperimentResult={currentExperimentResult}
          error={researchPlanError}
          isLoadingPapers={isLoadingPlanPapers}
          isRunning={isRunningResearchPlan}
          onClearSelection={() => setSelectedPlanDocIds([])}
          onRefresh={() => void loadPlanPapers()}
          onRun={() => void handleRunResearchPlan()}
          onSelectAll={() => setSelectedPlanDocIds(
            planPapers
              .filter((paper) => !paper.reupload_required)
              .map((paper) => paper.doc_id),
          )}
          onTogglePaper={togglePlanPaper}
          papers={planPapers.filter((paper) => !paper.reupload_required)}
          researchDirection={researchDirection}
          result={researchPlanResult}
          selectedDocIds={selectedPlanDocIds}
          setCurrentExperimentResult={setCurrentExperimentResult}
          setResearchDirection={setResearchDirection}
        />
      ) : null}

      {activeModule === 'reproduction' ? (
        <ReproductionModule
          isLoadingPapers={isLoadingPapers}
          onRefresh={loadSharedPapers}
          papers={planPapers}
        />
      ) : null}

      {activeModule === 'citations' ? (
        <CitationModule
          error={citationError}
          graph={citationGraph}
          isLoading={isLoadingCitationGraph}
          keyword={citationKeyword}
          maxNodes={citationMaxNodes}
          onSearch={(event) => void handleCitationSearch(event)}
          setKeyword={setCitationKeyword}
          setMaxNodes={setCitationMaxNodes}
        />
      ) : null}

      {activeModule === 'knowledge' ? (
        <KnowledgeModule onAskWithPaper={selectPaperForReading} />
      ) : null}
    </main>
  );
}
