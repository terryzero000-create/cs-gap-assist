import { FormEvent, useMemo, useState } from 'react';
import './style.css';
import { fetchCitationGraph } from './api/client';
import { CitationForceGraph } from './components/CitationGraph/CitationForceGraph';
import type { CitationGraphResponse } from './types';

const DEFAULT_KEYWORD = 'retrieval augmented generation';
const NODE_LIMITS = [8, 15, 25, 40];

export function App() {
  const [keyword, setKeyword] = useState(DEFAULT_KEYWORD);
  const [maxNodes, setMaxNodes] = useState(15);
  const [graph, setGraph] = useState<CitationGraphResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const keyNodes = useMemo(
    () => (graph?.nodes ?? []).filter((node) => node.is_key).slice(0, 5),
    [graph],
  );

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedKeyword = keyword.trim();
    if (!trimmedKeyword) {
      setError('Enter a technical keyword.');
      return;
    }
    setIsLoading(true);
    setError(null);
    try {
      const result = await fetchCitationGraph(trimmedKeyword, maxNodes);
      setGraph(result);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Unable to load citation graph.');
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <main className="workspace">
      <section className="toolbar" aria-label="Citation graph search">
        <div>
          <p className="app-label">CS Gap Assist</p>
          <h1>Citation evolution graph</h1>
        </div>
        <form className="search-form" onSubmit={handleSubmit}>
          <label>
            Keyword
            <input
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
              placeholder="e.g. graph neural networks"
            />
          </label>
          <label>
            Node cap
            <select value={maxNodes} onChange={(event) => setMaxNodes(Number(event.target.value))}>
              {NODE_LIMITS.map((limit) => (
                <option value={limit} key={limit}>{limit} nodes</option>
              ))}
            </select>
          </label>
          <button type="submit" disabled={isLoading}>{isLoading ? 'Loading' : 'Build graph'}</button>
        </form>
      </section>

      {error ? <p className="alert error">{error}</p> : null}
      {graph?.warnings.map((warning) => (
        <p className="alert" key={warning}>{warning}</p>
      ))}

      <section className="content-grid">
        <div className="graph-panel" aria-busy={isLoading}>
          {isLoading ? <div className="loading-state">Loading citation graph...</div> : <CitationForceGraph nodes={graph?.nodes ?? []} links={graph?.links ?? []} />}
        </div>
        <aside className="summary-panel">
          <div className="stat-row">
            <span>Nodes</span>
            <strong>{graph?.nodes.length ?? 0}</strong>
          </div>
          <div className="stat-row">
            <span>Links</span>
            <strong>{graph?.links.length ?? 0}</strong>
          </div>
          <h2>Key papers</h2>
          <ul className="key-list">
            {keyNodes.map((node) => (
              <li key={node.id}>
                <strong>{node.title}</strong>
                <span>{node.year ?? 'Year unknown'} · score {node.importance_score.toFixed(2)}</span>
              </li>
            ))}
          </ul>
        </aside>
      </section>
    </main>
  );
}
