import type { GapItem } from '../../types';

interface GapListProps {
  gaps: GapItem[];
}

export function GapList({ gaps }: GapListProps) {
  if (gaps.length === 0) {
    return <p className="empty-state">分析完成后，研究空白会显示在这里。</p>;
  }
  return (
    <section className="gap-list">
      <h2>研究空白</h2>
      {gaps.map((gap) => (
        <article className="gap-item" key={gap.gap_id}>
          <div className="gap-item-header">
            <strong>{gap.title}</strong>
            <span className={`value-badge value-badge-${gap.value_level}`}>{gap.value_level === 'high' ? '高价值' : '中价值'}</span>
          </div>
          <p>{gap.description}</p>
          <div className="evidence-block">
            <span>证据论文</span>
            <ul>
              {gap.evidence_papers.map((paper) => (
                <li key={paper}>{paper}</li>
              ))}
            </ul>
          </div>
        </article>
      ))}
    </section>
  );
}
