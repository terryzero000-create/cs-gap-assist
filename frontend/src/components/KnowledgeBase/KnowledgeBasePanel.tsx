import { FormEvent, useEffect, useMemo, useState } from 'react';

import {
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

function parseTags(value: string): string[] {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium' }).format(new Date(value));
}

export function KnowledgeBasePanel() {
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
  const [status, setStatus] = useState('正在读取知识库...');
  const [isBusy, setIsBusy] = useState(false);

  const availableTags = useMemo(() => Array.from(new Set(papers.flatMap((paper) => paper.tags))).sort(), [papers]);
  const visibleResults = results.papers.length > 0 || query ? results : { ...results, papers };
  const visiblePapers = visibleResults.papers.slice(0, 24);

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
    const response = await searchKnowledge(nextQuery.trim(), tag || undefined, favoriteFilter);
    setResults(response);
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
          setStatus(records.length ? '知识库已就绪' : '还没有上传论文');
        }
      } catch (error) {
        if (mounted) {
          setStatus(error instanceof Error ? error.message : '知识库读取失败');
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
      setStatus('搜索已更新');
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '搜索失败');
    } finally {
      setIsBusy(false);
    }
  }

  async function handleUpload(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!selectedFile) {
      setStatus('请选择 PDF 文件');
      return;
    }
    setIsBusy(true);
    try {
      const uploaded = await uploadPaper(selectedFile);
      await refreshPapers();
      await runSearch('');
      setSelectedFile(null);
      setStatus(`已上传 ${uploaded.title}`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '上传失败');
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
      setStatus(`已更新 ${updated.title}`);
      await refreshPapers();
      await runSearch();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '论文更新失败');
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
      setStatus('笔记需要标题和正文');
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
      setStatus('笔记已保存');
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '笔记保存失败');
    } finally {
      setIsBusy(false);
    }
  }

  return (
    <main className="workspace-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">CS Gap Assist</p>
          <h1>个人研究知识库</h1>
        </div>
        <p className="status-line">{isBusy ? '处理中...' : status}</p>
      </header>

      <section className="toolbar" aria-label="知识库操作">
        <form className="search-form" onSubmit={(event) => void handleSearch(event)}>
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索论文、笔记、Gap、实验计划" />
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
            只看收藏
          </label>
          <button type="submit" disabled={isBusy}>
            ↻ 搜索
          </button>
        </form>

        <form className="upload-form" onSubmit={(event) => void handleUpload(event)}>
          <input type="file" accept="application/pdf" onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)} />
          <button type="submit" disabled={isBusy}>
            + 上传论文
          </button>
        </form>
      </section>

      <section className="content-grid">
        <section className="paper-list" aria-label="论文列表">
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
                <button type="button" className="icon-button" onClick={() => void handleSavePaper(paper, !paper.is_favorite)}>
                  {paper.is_favorite ? '★' : '☆'}
                </button>
              </div>
              <div className="tag-row">
                {paper.tags.length ? paper.tags.map((tag) => <span key={tag}>{tag}</span>) : <span>未标注</span>}
              </div>
              <div className="inline-edit">
                <input
                  value={tagDrafts[paper.doc_id] ?? ''}
                  onChange={(event) => setTagDrafts((current) => ({ ...current, [paper.doc_id]: event.target.value }))}
                  placeholder="tag-a, tag-b"
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
            <h2>新笔记</h2>
          </div>
          <form className="note-form" onSubmit={(event) => void handleCreateNote(event)}>
            <input value={noteTitle} onChange={(event) => setNoteTitle(event.target.value)} placeholder="标题" />
            <textarea value={noteContent} onChange={(event) => setNoteContent(event.target.value)} placeholder="记录观察、疑问或后续实验想法" />
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
              + 保存笔记
            </button>
          </form>
        </section>

        <section className="results-panel" aria-label="搜索结果">
          <div className="section-heading">
            <h2>统一搜索</h2>
            <span>{results.notes.length + results.chunks.length + results.gaps.length + results.experiments.length}</span>
          </div>
          <div className="result-columns">
            <ResultGroup title="笔记" items={results.notes.map((note) => ({ id: note.note_id, title: note.title, body: note.content }))} />
            <ResultGroup title="论文片段" items={results.chunks.map((chunk) => ({ id: chunk.chunk_id, title: `第 ${chunk.page} 页`, body: chunk.text }))} />
            <ResultGroup title="Gap" items={results.gaps.map((gap) => ({ id: gap.gap_id, title: gap.title, body: gap.description }))} />
            <ResultGroup title="实验计划" items={results.experiments.map((experiment) => ({ id: experiment.experiment_id, title: experiment.objective, body: experiment.steps.join(' / ') }))} />
          </div>
        </section>
      </section>
    </main>
  );
}

interface ResultItem {
  id: string;
  title: string;
  body: string;
}

function ResultGroup({ title, items }: { title: string; items: ResultItem[] }) {
  return (
    <div className="result-group">
      <h3>{title}</h3>
      {items.length ? (
        items.slice(0, 5).map((item) => (
          <article key={item.id}>
            <strong>{item.title}</strong>
            <p>{item.body}</p>
          </article>
        ))
      ) : (
        <p className="empty-state">暂无结果</p>
      )}
    </div>
  );
}
