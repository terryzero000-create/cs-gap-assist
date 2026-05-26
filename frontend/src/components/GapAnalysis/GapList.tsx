import type { GapItem } from '../../types';

interface GapListProps {
  gaps: GapItem[];
}

export function GapList({ gaps }: GapListProps) {
  if (gaps.length === 0) {
    return <p>输入研究方向并选择论文后，这里会展示高/中价值Research Gap。</p>;
  }
  return (
    <section>
      <h2>Research Gap 分析</h2>
      {gaps.map((gap) => (
        <article key={gap.gap_id}>
          <strong>{gap.value_level === 'high' ? '高价值' : '中价值'}</strong>
          <h3>{gap.title}</h3>
          <p>{gap.description}</p>
        </article>
      ))}
    </section>
  );
}
