import { lazy, Suspense } from 'react';

import { EvidenceStatusBadge } from '../components/EvidenceStatusBadge';
import type { CitationGraphResponse } from '../types';

const CitationForceGraph = lazy(() =>
  import('../components/CitationGraph/CitationForceGraph').then((module) => ({
    default: module.CitationForceGraph,
  })),
);

interface CitationModuleProps {
  error: string | null;
  graph: CitationGraphResponse | null;
  isLoading: boolean;
  keyword: string;
  maxNodes: number;
  onSearch: React.FormEventHandler<HTMLFormElement>;
  setKeyword: (value: string) => void;
  setMaxNodes: (value: number) => void;
}

const citationNodeLimits = [8, 15, 25, 40];

export function CitationModule(props: CitationModuleProps) {
  const keyNodes = (props.graph?.nodes ?? []).filter((node) => node.is_key).slice(0, 5);
  return (
    <section className="citation-workspace" aria-label="引用图谱">
      <section className="analysis-panel">
        <form className="citation-toolbar" onSubmit={props.onSearch}>
          <label>
            关键词
            <input
              value={props.keyword}
              onChange={(event) => props.setKeyword(event.target.value)}
              placeholder="例如：图神经网络"
            />
          </label>
          <label>
            节点上限
            <select value={props.maxNodes} onChange={(event) => props.setMaxNodes(Number(event.target.value))}>
              {citationNodeLimits.map((limit) => (
                <option value={limit} key={limit}>{limit} 个节点</option>
              ))}
            </select>
          </label>
          <button type="submit" disabled={props.isLoading}>{props.isLoading ? '加载中' : '生成图谱'}</button>
        </form>
        {props.error ? <p className="error-banner">{props.error}</p> : null}
        {(props.graph?.warnings ?? []).map((warning, index) => (
          <p className="warning" key={`${props.graph?.warning_codes[index]}:${warning}`}>
            <strong>{props.graph?.warning_codes[index] ?? 'UNCLASSIFIED_WARNING'}</strong> · {warning}
          </p>
        ))}
        <EvidenceStatusBadge status={props.graph?.evidence_status} />
        <div className="citation-grid">
          <div className="graph-panel" aria-busy={props.isLoading}>
            {props.isLoading ? (
              <div className="loading-state">正在加载引用图谱...</div>
            ) : (
              <Suspense fallback={<div className="loading-state">正在加载图谱模块...</div>}>
                <CitationForceGraph nodes={props.graph?.nodes ?? []} links={props.graph?.links ?? []} />
              </Suspense>
            )}
          </div>
          <aside className="summary-panel">
            <div className="stat-row"><span>节点数</span><strong>{props.graph?.nodes.length ?? 0}</strong></div>
            <div className="stat-row"><span>连接数</span><strong>{props.graph?.links.length ?? 0}</strong></div>
            <h2>关键论文</h2>
            <ul className="key-list">
              {keyNodes.map((node) => (
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
  );
}
