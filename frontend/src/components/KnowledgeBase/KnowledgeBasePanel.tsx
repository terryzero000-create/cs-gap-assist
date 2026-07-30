import { DragEvent, FormEvent, useEffect, useMemo, useState } from 'react';

import {
  ApiClientError,
  createKnowledgeNote,
  listKnowledgePapers,
  searchKnowledge,
  updateKnowledgePaper,
  uploadPaper,
} from '../../api/client';
import type { KnowledgeSearchResponse, NoteCreateRequest, PaperRecord } from '../../types';

const emptyResults: KnowledgeSearchResponse = {
  papers: [],
  notes: [],
  chunks: [],
  gaps: [],
  experiments: [],
};

interface ResultItem {
  id: string;
  title: string;
  body: string;
}

function parseTags(value: string): string[] {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium' }).format(new Date(value));
}

function readableError(error: unknown, fallback: string): string {
  if (error instanceof ApiClientError) {
    return `${fallback}（${error.errorCode}）${error.message}${error.retryable ? ' 可稍后重试。' : ''}`;
  }
  if (!(error instanceof Error)) {
    return fallback;
  }
  return error.message;
}

function ResultGroup({ title, items }: { title: string; items: ResultItem[] }) {
  return (
    <div className="result-group">
      <div className="result-group-head">
        <h3>{title}</h3>
        <span>{items.length}</span>
      </div>
      {items.length ? (
        items.slice(0, 3).map((item) => (
          <article key={item.id}>
            <strong>{item.title}</strong>
            <p>{item.body}</p>
          </article>
        ))
      ) : (
        <p className="empty-state">暂无结果。</p>
      )}
      {items.length > 3 ? <small className="result-more">当前展示 3 条摘要，缩小关键词可进一步聚焦。</small> : null}
    </div>
  );
}

interface KnowledgeBasePanelProps {
  onAskWithPaper: (docId: string) => void;
}

export function KnowledgeBasePanel({ onAskWithPaper }: KnowledgeBasePanelProps) {
  const [papers, setPapers] = useState<PaperRecord[]>([]);
  const [results, setResults] = useState<KnowledgeSearchResponse>(emptyResults);
  const [query, setQuery] = useState('');
  const [activeTag, setActiveTag] = useState('');
  const [favoritesOnly, setFavoritesOnly] = useState(false);
  const [tagDrafts, setTagDrafts] = useState<Record<string, string>>({});
  const [noteTitle, setNoteTitle] = useState('');
  const [noteContent, setNoteContent] = useState('');
  const [noteTags, setNoteTags] = useState('');
  const [relatedDocId, setRelatedDocId] = useState('');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [status, setStatus] = useState('正在加载知识库...');
  const [isBusy, setIsBusy] = useState(false);

  const availableTags = useMemo(() => Array.from(new Set(papers.flatMap((paper) => paper.tags))).sort(), [papers]);
  const visibleResults = results.papers.length > 0 || query ? results : { ...results, papers };
  const visiblePapers = visibleResults.papers.slice(0, 24);
  const searchGroups = [
    { title: '笔记', items: results.notes.map((note) => ({ id: note.note_id, title: note.title, body: note.content })) },
    { title: '论文片段', items: results.chunks.map((chunk) => ({ id: chunk.chunk_id, title: `第 ${chunk.page} 页`, body: chunk.text })) },
    { title: '研究空白', items: results.gaps.map((gap) => ({ id: gap.gap_id, title: gap.title, body: gap.description })) },
    {
      title: '实验方案',
      items: results.experiments.map((experiment) => ({
        id: experiment.experiment_id,
        title: experiment.objective,
        body: experiment.steps.join(' / '),
      })),
    },
  ].filter((group) => group.items.length > 0);
  const searchResultCount = searchGroups.reduce((total, group) => total + group.items.length, 0);

  async function refreshPapers(tag = activeTag, favoriteFilter = favoritesOnly): Promise<PaperRecord[]> {
    const records = await listKnowledgePapers(tag || undefined, favoriteFilter);
    setPapers(records);
    setTagDrafts((current) => {
      const next = { ...current };
      records.forEach((paper) => {
        if (!(paper.doc_id in next)) {
          next[paper.doc_id] = paper.tags.join(', ');
        }
      });
      return next;
    });
    return records;
  }

  async function runSearch(nextQuery = query, tag = activeTag, favoriteFilter = favoritesOnly): Promise<void> {
    setResults(await searchKnowledge(nextQuery.trim(), tag || undefined, favoriteFilter));
  }

  function chooseUploadFile(file: File | undefined): void {
    if (!file) {
      return;
    }
    if (file.type !== 'application/pdf' && !file.name.toLowerCase().endsWith('.pdf')) {
      setSelectedFile(null);
      setStatus('请选择 PDF 文件。');
      return;
    }
    setSelectedFile(file);
  }

  function handleDrop(event: DragEvent<HTMLLabelElement>): void {
    event.preventDefault();
    chooseUploadFile(event.dataTransfer.files[0]);
  }

  useEffect(() => {
    let mounted = true;
    async function loadInitialState(): Promise<void> {
      try {
        const records = await listKnowledgePapers();
        const response = await searchKnowledge('');
        if (mounted) {
          setPapers(records);
          setResults(response);
          setTagDrafts(Object.fromEntries(records.map((paper) => [paper.doc_id, paper.tags.join(', ')])));
          setStatus(records.length ? '知识库已就绪。' : '上传一篇论文开始。');
        }
      } catch (error) {
        if (mounted) {
          setStatus(readableError(error, '无法加载知识库。'));
        }
      }
    }
    void loadInitialState();
    return () => {
      mounted = false;
    };
  }, []);

  async function handleSearch(event?: FormEvent<HTMLFormElement>): Promise<void> {
    event?.preventDefault();
    setIsBusy(true);
    try {
      await refreshPapers();
      await runSearch();
      setStatus('搜索结果已更新。');
    } catch (error) {
      setStatus(readableError(error, '搜索失败。'));
    } finally {
      setIsBusy(false);
    }
  }

  async function handleUpload(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!selectedFile) {
      setStatus('请先选择 PDF。');
      return;
    }
    setIsBusy(true);
    try {
      const uploaded = await uploadPaper(selectedFile);
      await refreshPapers();
      await runSearch('');
      setSelectedFile(null);
      setStatus(`已上传 ${uploaded.title}。`);
    } catch (error) {
      setStatus(readableError(error, '上传失败。'));
    } finally {
      setIsBusy(false);
    }
  }

  async function handleSavePaper(paper: PaperRecord, isFavorite = paper.is_favorite): Promise<void> {
    setIsBusy(true);
    try {
      const updated = await updateKnowledgePaper(paper.doc_id, {
        tags: parseTags(tagDrafts[paper.doc_id] ?? ''),
        is_favorite: isFavorite,
      });
      setStatus(`已更新 ${updated.title}。`);
      await refreshPapers();
      await runSearch();
    } catch (error) {
      setStatus(readableError(error, '论文更新失败。'));
    } finally {
      setIsBusy(false);
    }
  }

  async function handleCreateNote(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    const request: NoteCreateRequest = {
      title: noteTitle.trim(),
      content: noteContent.trim(),
      tags: parseTags(noteTags),
      related_doc_id: relatedDocId || null,
    };
    if (!request.title || !request.content) {
      setStatus('笔记需要标题和正文。');
      return;
    }
    setIsBusy(true);
    try {
      await createKnowledgeNote(request);
      setNoteTitle('');
      setNoteContent('');
      setNoteTags('');
      setRelatedDocId('');
      await runSearch(query || request.title);
      setStatus('笔记已保存。');
    } catch (error) {
      setStatus(readableError(error, '笔记保存失败。'));
    } finally {
      setIsBusy(false);
    }
  }

  return (
    <section className="knowledge-panel">
      <header className="panel-header">
        <h2>知识库</h2>
        <span className="status-line">{isBusy ? '处理中...' : status}</span>
      </header>

      <section className="knowledge-toolbar" aria-label="知识库操作">
        <form className="search-form" onSubmit={(event) => void handleSearch(event)}>
          <div className="toolbar-heading">
            <strong>检索资料</strong>
            <span>按关键词、标签与收藏状态快速筛选</span>
          </div>
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索论文、笔记、研究空白、实验方案" />
          <select value={activeTag} onChange={(event) => setActiveTag(event.target.value)}>
            <option value="">全部标签</option>
            {availableTags.map((tag) => (
              <option value={tag} key={tag}>
                {tag}
              </option>
            ))}
          </select>
          <label className="checkline">
            <input type="checkbox" checked={favoritesOnly} onChange={(event) => setFavoritesOnly(event.target.checked)} />
            仅收藏
          </label>
          <button type="submit" disabled={isBusy}>
            搜索
          </button>
          <p className="toolbar-help">论文匹配会更新下方列表，其他关联内容集中显示在统一搜索中。</p>
        </form>

        <form className="upload-form" onSubmit={(event) => void handleUpload(event)}>
          <div className="toolbar-heading">
            <strong>导入论文</strong>
            <span>支持 PDF，拖拽或选择文件后上传</span>
          </div>
          <input
            id="knowledge-upload-input"
            className="file-input-hidden"
            type="file"
            accept="application/pdf"
            onChange={(event) => chooseUploadFile(event.target.files?.[0])}
          />
          <label
            className="upload-dropzone"
            htmlFor="knowledge-upload-input"
            onDragOver={(event) => event.preventDefault()}
            onDrop={handleDrop}
          >
            <strong>拖拽 PDF 到这里</strong>
            <span>{selectedFile ? selectedFile.name : '松开即可选择文件'}</span>
          </label>
          <div className="upload-actions">
            <label className="file-button upload-picker" htmlFor="knowledge-upload-input">
              选择文件
            </label>
            <button type="submit" disabled={isBusy}>
              上传 PDF
            </button>
          </div>
        </form>
      </section>

      <section className="knowledge-grid">
        <div className="knowledge-library-row">
          <section className="paper-library" aria-label="论文列表">
          <div className="section-heading">
            <h2>论文</h2>
            <span>{visibleResults.papers.length}</span>
          </div>
          {visiblePapers.map((paper) => (
            <article className="record-card" key={paper.doc_id}>
              <div className="record-head">
                <div>
                  <h3>{paper.title}</h3>
                  <p>{formatDate(paper.created_at)}</p>
                </div>
                <div className="record-actions">
                  <button type="button" className="secondary-button" onClick={() => onAskWithPaper(paper.doc_id)}>
                    用于问答
                  </button>
                  <button type="button" className="icon-button" onClick={() => void handleSavePaper(paper, !paper.is_favorite)}>
                    {paper.is_favorite ? '已收藏' : '收藏'}
                  </button>
                </div>
              </div>
              <div className="tag-row">
                {paper.tags.length ? paper.tags.map((tag) => <span key={tag}>{tag}</span>) : <span>未打标签</span>}
              </div>
              <div className="inline-edit">
                <input
                  value={tagDrafts[paper.doc_id] ?? ''}
                  onChange={(event) => setTagDrafts((current) => ({ ...current, [paper.doc_id]: event.target.value }))}
                  placeholder="标签一, 标签二"
                />
                <button type="button" onClick={() => void handleSavePaper(paper)}>
                  保存
                </button>
              </div>
            </article>
          ))}
          </section>

          <section className="note-panel" aria-label="创建笔记">
            <div className="section-heading">
              <h2>新建笔记</h2>
            </div>
            <form className="note-form" onSubmit={(event) => void handleCreateNote(event)}>
              <input value={noteTitle} onChange={(event) => setNoteTitle(event.target.value)} placeholder="标题" />
              <textarea value={noteContent} onChange={(event) => setNoteContent(event.target.value)} placeholder="观察、问题或实验想法" />
              <input value={noteTags} onChange={(event) => setNoteTags(event.target.value)} placeholder="标签，用逗号分隔" />
              <select value={relatedDocId} onChange={(event) => setRelatedDocId(event.target.value)}>
                <option value="">不关联论文</option>
                {papers.map((paper) => (
                  <option value={paper.doc_id} key={paper.doc_id}>
                    {paper.title}
                  </option>
                ))}
              </select>
              <button type="submit" disabled={isBusy}>
                保存笔记
              </button>
            </form>
          </section>
        </div>

        <section className="results-panel" aria-label="搜索结果">
          <div className="section-heading">
            <div>
              <p className="section-kicker">CROSS-LIBRARY RESULTS</p>
              <h2>统一搜索</h2>
            </div>
            <span className="result-total">共 {searchResultCount} 条</span>
          </div>
          <p className="results-hint">论文结果会同步到上方列表，其余内容按类型归档，便于继续整理。</p>
          {searchResultCount > 0 ? (
            <div className="result-columns">
              {searchGroups.map((group) => <ResultGroup key={group.title} title={group.title} items={group.items} />)}
            </div>
          ) : (
            <div className="unified-empty-state">
              <span aria-hidden="true">检</span>
              <div>
                <strong>{query.trim() ? '没有找到关联内容' : '从一次跨库检索开始'}</strong>
                <p>{query.trim() ? '可以减少关键词，或切换标签与收藏条件后重试。' : '输入关键词后，将在笔记、论文片段、研究空白和实验方案中同时查找。'}</p>
              </div>
            </div>
          )}
        </section>
      </section>
    </section>
  );
}
