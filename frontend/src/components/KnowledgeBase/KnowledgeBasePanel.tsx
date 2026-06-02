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
  return new Intl.DateTimeFormat('en-US', { dateStyle: 'medium' }).format(new Date(value));
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
        <p className="empty-state">No results yet.</p>
      )}
    </div>
  );
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
  const [status, setStatus] = useState('Loading knowledge base...');
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
    setResults(await searchKnowledge(nextQuery.trim(), tag || undefined, favoriteFilter));
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
          setStatus(records.length ? 'Knowledge base ready.' : 'Upload a paper to start.');
        }
      } catch (error) {
        if (mounted) {
          setStatus(error instanceof Error ? error.message : 'Could not load knowledge base.');
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
      setStatus('Search updated.');
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Search failed.');
    } finally {
      setIsBusy(false);
    }
  }

  async function handleUpload(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!selectedFile) {
      setStatus('Choose a PDF first.');
      return;
    }
    setIsBusy(true);
    try {
      const uploaded = await uploadPaper(selectedFile);
      await refreshPapers();
      await runSearch('');
      setSelectedFile(null);
      setStatus(`Uploaded ${uploaded.title}.`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Upload failed.');
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
      setStatus(`Updated ${updated.title}.`);
      await refreshPapers();
      await runSearch();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Paper update failed.');
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
      setStatus('Notes need a title and body.');
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
      setStatus('Note saved.');
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Note save failed.');
    } finally {
      setIsBusy(false);
    }
  }

  return (
    <section className="knowledge-panel">
      <header className="panel-header">
        <h2>Knowledge Base</h2>
        <span className="status-line">{isBusy ? 'Working...' : status}</span>
      </header>

      <section className="knowledge-toolbar" aria-label="Knowledge base actions">
        <form className="search-form" onSubmit={(event) => void handleSearch(event)}>
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search papers, notes, gaps, experiments" />
          <select value={activeTag} onChange={(event) => setActiveTag(event.target.value)}>
            <option value="">All tags</option>
            {availableTags.map((tag) => (
              <option value={tag} key={tag}>
                {tag}
              </option>
            ))}
          </select>
          <label className="checkline">
            <input type="checkbox" checked={favoritesOnly} onChange={(event) => setFavoritesOnly(event.target.checked)} />
            Favorites
          </label>
          <button type="submit" disabled={isBusy}>
            Search
          </button>
        </form>

        <form className="upload-form" onSubmit={(event) => void handleUpload(event)}>
          <input type="file" accept="application/pdf" onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)} />
          <button type="submit" disabled={isBusy}>
            Upload PDF
          </button>
        </form>
      </section>

      <section className="knowledge-grid">
        <section className="paper-library" aria-label="Paper list">
          <div className="section-heading">
            <h2>Papers</h2>
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
                  {paper.is_favorite ? 'Saved' : 'Save'}
                </button>
              </div>
              <div className="tag-row">
                {paper.tags.length ? paper.tags.map((tag) => <span key={tag}>{tag}</span>) : <span>Untagged</span>}
              </div>
              <div className="inline-edit">
                <input
                  value={tagDrafts[paper.doc_id] ?? ''}
                  onChange={(event) => setTagDrafts((current) => ({ ...current, [paper.doc_id]: event.target.value }))}
                  placeholder="tag-a, tag-b"
                />
                <button type="button" onClick={() => void handleSavePaper(paper)}>
                  Save
                </button>
              </div>
            </article>
          ))}
        </section>

        <section className="note-panel" aria-label="Create note">
          <div className="section-heading">
            <h2>New Note</h2>
          </div>
          <form className="note-form" onSubmit={(event) => void handleCreateNote(event)}>
            <input value={noteTitle} onChange={(event) => setNoteTitle(event.target.value)} placeholder="Title" />
            <textarea value={noteContent} onChange={(event) => setNoteContent(event.target.value)} placeholder="Observation, question, or experiment idea" />
            <input value={noteTags} onChange={(event) => setNoteTags(event.target.value)} placeholder="Tags, comma separated" />
            <select value={relatedDocId} onChange={(event) => setRelatedDocId(event.target.value)}>
              <option value="">No related paper</option>
              {papers.map((paper) => (
                <option value={paper.doc_id} key={paper.doc_id}>
                  {paper.title}
                </option>
              ))}
            </select>
            <button type="submit" disabled={isBusy}>
              Save note
            </button>
          </form>
        </section>

        <section className="results-panel" aria-label="Search results">
          <div className="section-heading">
            <h2>Unified Search</h2>
            <span>{results.notes.length + results.chunks.length + results.gaps.length + results.experiments.length}</span>
          </div>
          <div className="result-columns">
            <ResultGroup title="Notes" items={results.notes.map((note) => ({ id: note.note_id, title: note.title, body: note.content }))} />
            <ResultGroup title="Chunks" items={results.chunks.map((chunk) => ({ id: chunk.chunk_id, title: `Page ${chunk.page}`, body: chunk.text }))} />
            <ResultGroup title="Gaps" items={results.gaps.map((gap) => ({ id: gap.gap_id, title: gap.title, body: gap.description }))} />
            <ResultGroup title="Experiments" items={results.experiments.map((experiment) => ({ id: experiment.experiment_id, title: experiment.objective, body: experiment.steps.join(' / ') }))} />
          </div>
        </section>
      </section>
    </section>
  );
}
